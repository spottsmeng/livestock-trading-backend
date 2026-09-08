"""§9.5, §2.2 — every route here is BUYER-only and every response model in
schemas/buyer.py is buyer-safe by construction. Row-level scoping (a buyer
only ever sees their own `buy_entries`) lives in the repository layer
(repositories/buy_entries.py always filters by `buyer_id`), never
reconstructed ad hoc in a route handler (§14).
"""

import uuid
from datetime import date as date_cls

from fastapi import APIRouter, Depends, Query, Request
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import CurrentUser, redis_dep, require_role
from core.db import get_db
from core.errors import NotFound
from core.reference_data import get_operational_constants, get_saleyard_calendar, resolve_saleyard_for_date
from domain.buyer.bidcheck import score_bid
from models.enums import Role
from repositories import buy_entries as buy_entries_repo
from repositories import buy_instructions as buy_instructions_repo
from repositories import publications as publications_repo
from repositories import push_subscriptions as push_subscriptions_repo
from schemas.buyer import (
    AckRequest,
    BulkSyncItemResult,
    BuyEntryBulkRequest,
    BuyEntryCreateRequest,
    BuyEntryPatchRequest,
    BuyEntryResponse,
    DnbpCurrentResponse,
    InstructionLineResponse,
    InstructionResponse,
    PushSubscriptionRequest,
    ScorecardResponse,
)
from services import buy_entry_service, buy_instruction_service, delivery_service, scorecard_service
from services.buy_entry_service import BuyEntryInput

router = APIRouter(prefix="/buyer", tags=["buyer"])

_buyer_only = require_role(Role.BUYER)


def _to_input(body: BuyEntryCreateRequest) -> BuyEntryInput:
    return BuyEntryInput(
        saleyard=body.saleyard,
        trade_date=body.trade_date,
        species=body.species,
        agent=body.agent,
        pen=body.pen,
        head_count=body.head_count,
        price_per_head=body.price_per_head,
        weight_kg=body.weight_kg,
        description=body.description,
        eid_ref=body.eid_ref,
        freight_per_head=body.freight_per_head,
        other_cost_per_kg=body.other_cost_per_kg,
        breach_reason=body.breach_reason,
        client_uuid=body.client_uuid,
        client_created_at=body.client_created_at,
    )


def _to_entry_response(entry, *, is_possible_duplicate: bool = False) -> BuyEntryResponse:
    return BuyEntryResponse(
        id=entry.id,
        saleyard=entry.saleyard,
        trade_date=entry.trade_date,
        species=entry.species,
        agent=entry.agent,
        pen=entry.pen,
        head_count=entry.head_count,
        price_per_head=entry.price_per_head,
        weight_kg=entry.weight_kg,
        description=entry.description,
        eid_ref=entry.eid_ref,
        freight_per_head=entry.freight_per_head,
        other_cost_per_kg=entry.other_cost_per_kg,
        implied_price_per_kg=entry.implied_price_per_kg,
        dnbp_at_entry=entry.dnbp_at_entry,
        variance_per_kg=entry.variance_per_kg,
        is_breach=entry.is_breach,
        breach_reason=entry.breach_reason,
        client_uuid=entry.client_uuid,
        client_created_at=entry.client_created_at,
        synced_at=entry.synced_at,
        is_possible_duplicate=is_possible_duplicate,
    )


@router.get("/dnbp/current", response_model=DnbpCurrentResponse)
async def dnbp_current(
    current: CurrentUser = Depends(_buyer_only), db: AsyncSession = Depends(get_db)
) -> DnbpCurrentResponse:
    publication = await publications_repo.get_current_for_org(db, current.org_id)
    if publication is None:
        raise NotFound("Published DNBP")
    lines = await publications_repo.list_lines(db, publication.id)
    return DnbpCurrentResponse(**delivery_service.buyer_safe_payload(publication, lines))


@router.post("/dnbp/ack", status_code=204)
async def dnbp_ack(
    body: AckRequest,
    current: CurrentUser = Depends(_buyer_only),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(redis_dep),
) -> None:
    """§10's mandatory delivery confirmation — called by the PWA the moment
    it renders a publication, whichever channel (WS, a tapped push
    notification, or a poll) got it there (see delivery_service's module
    docstring for why "delivered" and "acknowledged" are one event here)."""
    publication = await publications_repo.get_by_id(db, body.publication_id)
    if publication is None or publication.org_id != current.org_id:
        raise NotFound("Publication")
    await delivery_service.acknowledge(db, redis, publication=publication, buyer_id=current.user_id)
    await db.commit()


@router.post("/entries", response_model=BuyEntryResponse, status_code=201)
async def create_entry(
    body: BuyEntryCreateRequest, current: CurrentUser = Depends(_buyer_only), db: AsyncSession = Depends(get_db)
) -> BuyEntryResponse:
    result = await buy_entry_service.create_or_sync_entry(
        db, buyer_id=current.user_id, org_id=current.org_id, payload=_to_input(body)
    )
    await db.commit()
    return _to_entry_response(result.entry, is_possible_duplicate=result.is_possible_duplicate)


@router.post("/entries/bulk", response_model=list[BulkSyncItemResult])
async def bulk_sync_entries(
    body: BuyEntryBulkRequest, current: CurrentUser = Depends(_buyer_only), db: AsyncSession = Depends(get_db)
) -> list[BulkSyncItemResult]:
    """§9.5, §12.7 — the offline queue flush. Per-item results: one failed
    item never fails the whole batch, so the PWA knows exactly which queued
    entries to keep retrying."""
    items = [_to_input(entry) for entry in body.entries]
    results = await buy_entry_service.bulk_sync(db, buyer_id=current.user_id, org_id=current.org_id, items=items)
    await db.commit()
    return [BulkSyncItemResult(**r) for r in results]


@router.get("/entries", response_model=list[BuyEntryResponse])
async def list_entries(
    trade_date: str | None = Query(default=None),
    saleyard: str | None = Query(default=None),
    current: CurrentUser = Depends(_buyer_only),
    db: AsyncSession = Depends(get_db),
) -> list[BuyEntryResponse]:
    parsed_date = date_cls.fromisoformat(trade_date) if trade_date else None
    entries = await buy_entries_repo.list_for_buyer(db, current.user_id, trade_date=parsed_date, saleyard=saleyard)
    return [_to_entry_response(e) for e in entries]


@router.patch("/entries/{entry_id}", response_model=BuyEntryResponse)
async def patch_entry(
    entry_id: uuid.UUID,
    body: BuyEntryPatchRequest,
    current: CurrentUser = Depends(_buyer_only),
    db: AsyncSession = Depends(get_db),
) -> BuyEntryResponse:
    entry = await buy_entries_repo.get_by_id(db, entry_id)
    if entry is None or entry.buyer_id != current.user_id or entry.is_deleted:
        raise NotFound("Buy entry")

    for field in ("pen", "description", "breach_reason", "head_count"):
        value = getattr(body, field)
        if value is not None:
            setattr(entry, field, value)

    rescored = body.price_per_head is not None or body.weight_kg is not None
    if body.price_per_head is not None:
        entry.price_per_head = body.price_per_head
    if body.weight_kg is not None:
        entry.weight_kg = body.weight_kg

    if rescored:
        # Rescored against the FROZEN dnbp_at_entry, never a re-fetched
        # publication (§12.4's non-negotiable) — this is only correcting a
        # typo in what was bid/weighed, not re-litigating which DNBP applied.
        close_threshold = get_operational_constants().bid_check_close_threshold_pct
        result = score_bid(
            price_per_head=entry.price_per_head,
            weight_kg=entry.weight_kg,
            dnbp_per_kg=entry.dnbp_at_entry,
            close_threshold_pct=close_threshold,
        )
        entry.implied_price_per_kg = result.implied_price_per_kg
        entry.variance_per_kg = result.variance_per_kg
        entry.is_breach = result.is_breach

    await db.commit()
    return _to_entry_response(entry)


@router.delete("/entries/{entry_id}", status_code=204)
async def delete_entry(
    entry_id: uuid.UUID, current: CurrentUser = Depends(_buyer_only), db: AsyncSession = Depends(get_db)
) -> None:
    entry = await buy_entries_repo.get_by_id(db, entry_id)
    if entry is None or entry.buyer_id != current.user_id:
        raise NotFound("Buy entry")
    entry.is_deleted = True
    await db.commit()


@router.get("/instruction/current", response_model=InstructionResponse)
async def instruction_current(
    current: CurrentUser = Depends(_buyer_only), db: AsyncSession = Depends(get_db)
) -> InstructionResponse:
    """§12.5, §9.5 — buyer-safe view of the live Buy Instruction. Built by
    hand from `BuyInstructionLine`/`SaleyardCalendarEntry` field-by-field
    (never `model_validate`d off the trading-console model), the same
    discipline every other route in this module already follows, so a
    forbidden field can never leak just because a future column gets added
    upstream."""
    instruction = await buy_instructions_repo.get_current_for_org(db, current.org_id)
    if instruction is None:
        raise NotFound("Buy instruction")
    lines = await buy_instructions_repo.list_lines(db, instruction.id)
    saleyard_entry = resolve_saleyard_for_date(instruction.trade_date, get_saleyard_calendar())
    return InstructionResponse(
        instruction_id=str(instruction.id),
        instruction_no=instruction.instruction_no,
        trade_date=instruction.trade_date.isoformat(),
        status=instruction.status.value,
        saleyard=saleyard_entry.saleyard if saleyard_entry else None,
        prepayment_note=saleyard_entry.note if saleyard_entry else None,
        lines=[
            InstructionLineResponse(
                contract_no=line.contract_no,
                species=line.species,
                target_heads=str(line.expected_heads),
                weight_requirement_kg=str(line.weight_requirement_kg),
                dnbp_per_kg=str(line.dnbp_per_kg),
            )
            for line in lines
        ],
    )


@router.post("/instruction/{instruction_id}/acknowledge", status_code=204)
async def instruction_acknowledge(
    instruction_id: uuid.UUID, current: CurrentUser = Depends(_buyer_only), db: AsyncSession = Depends(get_db)
) -> None:
    instruction = await buy_instructions_repo.get_by_id(db, instruction_id)
    if instruction is None or instruction.org_id != current.org_id:
        raise NotFound("Buy instruction")
    await buy_instruction_service.acknowledge(db, instruction, buyer_id=current.user_id)
    await db.commit()


@router.get("/scorecard", response_model=ScorecardResponse)
async def scorecard(
    from_: str | None = Query(default=None, alias="from"),
    to: str | None = Query(default=None),
    current: CurrentUser = Depends(_buyer_only),
    db: AsyncSession = Depends(get_db),
) -> ScorecardResponse:
    """§12.6, §9.5 — own performance only. `buyer_id=current.user_id` is
    hard-coded here, not taken from a query param, the same row-level-
    scoping discipline every other route in this module already follows —
    there is no way to ask for another buyer's scorecard through this
    endpoint."""
    since = date_cls.fromisoformat(from_) if from_ else None
    until = date_cls.fromisoformat(to) if to else None
    return await scorecard_service.build_scorecard(
        db, org_id=current.org_id, buyer_id=current.user_id, since=since, until=until
    )


@router.post("/push-subscriptions", status_code=204)
async def subscribe_push(
    body: PushSubscriptionRequest,
    request: Request,
    current: CurrentUser = Depends(_buyer_only),
    db: AsyncSession = Depends(get_db),
) -> None:
    await push_subscriptions_repo.upsert(
        db,
        user_id=current.user_id,
        endpoint=body.endpoint,
        p256dh=body.p256dh,
        auth=body.auth,
        ua=body.ua or request.headers.get("user-agent"),
    )
    await db.commit()


@router.delete("/push-subscriptions", status_code=204)
async def unsubscribe_push(
    endpoint: str = Query(...), current: CurrentUser = Depends(_buyer_only), db: AsyncSession = Depends(get_db)
) -> None:
    await push_subscriptions_repo.delete_by_endpoint(db, endpoint)
    await db.commit()
