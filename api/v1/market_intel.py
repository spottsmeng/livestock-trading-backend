"""Market intelligence — competitor bid observations, ringside logging of
another buyer's successful bid for benchmarking/analytics/ML. Mixes two
role gates in one router (same pattern as api/v1/buy_instructions.py and
api/v1/publications.py): a BUYER may only submit and correct their own
observations, never list or read anyone's back; only OWNER/ACCOUNTANT can
list or aggregate this table. Kept entirely separate from api/v1/buyer.py
so tests/test_buyer_response_isolation.py's scope (which only introspects
that router) stays correct.
"""

import uuid
from datetime import date as date_cls

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import CurrentUser, require_role
from core.db import get_db
from core.errors import NotFound
from models.enums import Role
from repositories import market_observations as market_observations_repo
from repositories import users as users_repo
from schemas.market_intel import (
    BulkObservationSyncItemResult,
    MarketIntelSummaryResponse,
    MarketIntelSummaryRow,
    MarketObservationAck,
    MarketObservationBulkRequest,
    MarketObservationCreateRequest,
    MarketObservationPatchRequest,
    MarketObservationResponse,
)
from services import market_observation_service
from services.market_observation_service import MarketObservationInput

router = APIRouter(prefix="/market-intel", tags=["market-intel"])

_buyer_only = require_role(Role.BUYER)
_trading_console = require_role(Role.OWNER, Role.ACCOUNTANT)


def _to_input(body: MarketObservationCreateRequest) -> MarketObservationInput:
    return MarketObservationInput(
        saleyard=body.saleyard,
        trade_date=body.trade_date,
        species=body.species,
        competitor_name=body.competitor_name,
        agent=body.agent,
        pen=body.pen,
        head_count=body.head_count,
        price_per_head=body.price_per_head,
        weight_kg=body.weight_kg,
        description=body.description,
        is_estimated=body.is_estimated,
        client_uuid=body.client_uuid,
        client_created_at=body.client_created_at,
    )


def _to_ack(observation, *, is_possible_duplicate: bool = False) -> MarketObservationAck:
    return MarketObservationAck(
        id=observation.id,
        saleyard=observation.saleyard,
        trade_date=observation.trade_date,
        species=observation.species,
        competitor_name=observation.competitor_name,
        agent=observation.agent,
        pen=observation.pen,
        head_count=observation.head_count,
        price_per_head=observation.price_per_head,
        weight_kg=observation.weight_kg,
        description=observation.description,
        implied_price_per_kg=observation.implied_price_per_kg,
        is_estimated=observation.is_estimated,
        client_uuid=observation.client_uuid,
        client_created_at=observation.client_created_at,
        synced_at=observation.synced_at,
        is_possible_duplicate=is_possible_duplicate,
    )


@router.post("/observations", response_model=MarketObservationAck, status_code=201)
async def create_observation(
    body: MarketObservationCreateRequest,
    current: CurrentUser = Depends(_buyer_only),
    db: AsyncSession = Depends(get_db),
) -> MarketObservationAck:
    result = await market_observation_service.create_or_sync_observation(
        db, observer_id=current.user_id, org_id=current.org_id, payload=_to_input(body)
    )
    await db.commit()
    return _to_ack(result.observation, is_possible_duplicate=result.is_possible_duplicate)


@router.post("/observations/bulk", response_model=list[BulkObservationSyncItemResult])
async def bulk_sync_observations(
    body: MarketObservationBulkRequest,
    current: CurrentUser = Depends(_buyer_only),
    db: AsyncSession = Depends(get_db),
) -> list[BulkObservationSyncItemResult]:
    items = [_to_input(item) for item in body.observations]
    results = await market_observation_service.bulk_sync(
        db, observer_id=current.user_id, org_id=current.org_id, items=items
    )
    await db.commit()
    return [BulkObservationSyncItemResult(**r) for r in results]


@router.patch("/observations/{observation_id}", response_model=MarketObservationAck)
async def patch_observation(
    observation_id: uuid.UUID,
    body: MarketObservationPatchRequest,
    current: CurrentUser = Depends(_buyer_only),
    db: AsyncSession = Depends(get_db),
) -> MarketObservationAck:
    observation = await market_observations_repo.get_by_id(db, observation_id)
    if observation is None or observation.observer_id != current.user_id or observation.is_deleted:
        raise NotFound("Market observation")

    for field in ("competitor_name", "pen", "description", "head_count", "is_estimated"):
        value = getattr(body, field)
        if value is not None:
            setattr(observation, field, value)

    rescore = body.price_per_head is not None or body.weight_kg is not None
    if body.price_per_head is not None:
        observation.price_per_head = body.price_per_head
    if body.weight_kg is not None:
        observation.weight_kg = body.weight_kg
    if rescore:
        observation.implied_price_per_kg = (
            observation.price_per_head / observation.weight_kg if observation.weight_kg else None
        )

    await db.commit()
    return _to_ack(observation)


@router.delete("/observations/{observation_id}", status_code=204)
async def delete_observation(
    observation_id: uuid.UUID, current: CurrentUser = Depends(_buyer_only), db: AsyncSession = Depends(get_db)
) -> None:
    observation = await market_observations_repo.get_by_id(db, observation_id)
    if observation is None or observation.observer_id != current.user_id:
        raise NotFound("Market observation")
    observation.is_deleted = True
    await db.commit()


@router.get("/observations", response_model=list[MarketObservationResponse])
async def list_observations(
    from_: str | None = Query(default=None, alias="from"),
    to: str | None = Query(default=None),
    saleyard: str | None = Query(default=None),
    species: str | None = Query(default=None),
    competitor_name: str | None = Query(default=None),
    current: CurrentUser = Depends(_trading_console),
    db: AsyncSession = Depends(get_db),
) -> list[MarketObservationResponse]:
    since = date_cls.fromisoformat(from_) if from_ else None
    until = date_cls.fromisoformat(to) if to else None
    rows = await market_observations_repo.list_for_org(
        db,
        current.org_id,
        trade_date_from=since,
        trade_date_to=until,
        saleyard=saleyard,
        species=species,
        competitor_name=competitor_name,
    )
    emails: dict[uuid.UUID, str] = {}
    responses = []
    for row in rows:
        if row.observer_id not in emails:
            user = await users_repo.get_by_id(db, row.observer_id)
            emails[row.observer_id] = user.email if user is not None else "unknown"
        responses.append(
            MarketObservationResponse(
                id=row.id,
                observer_id=row.observer_id,
                observer_email=emails[row.observer_id],
                saleyard=row.saleyard,
                trade_date=row.trade_date,
                species=row.species,
                competitor_name=row.competitor_name,
                agent=row.agent,
                pen=row.pen,
                head_count=row.head_count,
                price_per_head=row.price_per_head,
                weight_kg=row.weight_kg,
                description=row.description,
                implied_price_per_kg=row.implied_price_per_kg,
                is_estimated=row.is_estimated,
                client_created_at=row.client_created_at,
            )
        )
    return responses


@router.get("/summary", response_model=MarketIntelSummaryResponse)
async def summary(
    from_: str | None = Query(default=None, alias="from"),
    to: str | None = Query(default=None),
    saleyard: str | None = Query(default=None),
    species: str | None = Query(default=None),
    current: CurrentUser = Depends(_trading_console),
    db: AsyncSession = Depends(get_db),
) -> MarketIntelSummaryResponse:
    since = date_cls.fromisoformat(from_) if from_ else None
    until = date_cls.fromisoformat(to) if to else None
    rows = await market_observation_service.summarize(
        db, current.org_id, trade_date_from=since, trade_date_to=until, saleyard=saleyard, species=species
    )
    return MarketIntelSummaryResponse(
        from_=from_,
        to=to,
        rows=[
            MarketIntelSummaryRow(
                competitor_name=r.competitor_name,
                species=r.species,
                entry_count=r.entry_count,
                heads_observed=r.heads_observed,
                avg_price_per_kg=r.avg_price_per_kg,
                last_observed_at=r.last_observed_at,
            )
            for r in rows
        ],
    )
