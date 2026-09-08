import uuid

from fastapi import APIRouter, Depends
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import CurrentUser, redis_dep, require_role
from core.db import get_db
from core.errors import NotFound
from models.dnbp_publication import DnbpPublication
from models.enums import Role
from repositories import order_snapshots as order_snapshots_repo
from repositories import publications as publications_repo
from schemas.publications import PublicationDetailResponse, PublicationLineResponse, PublicationResponse, PublishRequest
from services import delivery_service, publication_service

router = APIRouter(prefix="/publications", tags=["publications"])

# §9.4 — publication is OWNER/ACCOUNTANT only, same as the rest of the
# trading-console surface (§2.1 — Bobby and Bing are collaborators, not
# approver and preparer, so neither is gated ahead of the other here).
_trading_console = require_role(Role.OWNER, Role.ACCOUNTANT)


def _publication_fields(publication: DnbpPublication) -> dict:
    """DnbpPublication carries no ORM relationship to its lines (this
    codebase's repositories always query children explicitly rather than
    via `relationship()` — see order_snapshots/order_lines) so the two are
    always assembled by hand rather than via a single `model_validate`."""
    return {
        "id": publication.id,
        "org_id": publication.org_id,
        "snapshot_id": publication.snapshot_id,
        "published_by": publication.published_by,
        "published_at": publication.published_at,
        "effective_from": publication.effective_from,
        "engine_version": publication.engine_version,
        "notes": publication.notes,
        "superseded_by": publication.superseded_by,
        "superseded_at": publication.superseded_at,
    }


async def _to_response(db: AsyncSession, publication: DnbpPublication) -> PublicationResponse:
    lines = await publications_repo.list_lines(db, publication.id)
    return PublicationResponse(
        **_publication_fields(publication), lines=[PublicationLineResponse.model_validate(line) for line in lines]
    )


async def _to_detail(db: AsyncSession, publication: DnbpPublication) -> PublicationDetailResponse:
    lines = await publications_repo.list_lines(db, publication.id)
    deliveries = await delivery_service.delivery_states(db, publication)
    return PublicationDetailResponse(
        **_publication_fields(publication),
        lines=[PublicationLineResponse.model_validate(line) for line in lines],
        deliveries=deliveries,
    )


@router.post("", response_model=PublicationDetailResponse, status_code=201)
async def publish(
    body: PublishRequest,
    current: CurrentUser = Depends(_trading_console),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(redis_dep),
) -> PublicationDetailResponse:
    snapshot = await order_snapshots_repo.get_by_id(db, body.snapshot_id)
    if snapshot is None or snapshot.org_id != current.org_id:
        raise NotFound("Snapshot")

    publication, lines = await publication_service.publish(db, snapshot, actor_id=current.user_id, notes=body.notes)
    await db.commit()

    # Fan-out happens after commit — a buyer receiving a publish event for a
    # row that then failed to commit would be worse than a buyer who
    # briefly sees nothing (§10's redundancy exists to cover the reverse
    # failure mode, not this one).
    await delivery_service.fan_out(db, redis, publication=publication, lines=lines)
    await db.commit()

    return await _to_detail(db, publication)


@router.get("", response_model=list[PublicationResponse])
async def list_publications(
    current: CurrentUser = Depends(_trading_console), db: AsyncSession = Depends(get_db)
) -> list[PublicationResponse]:
    publications = await publications_repo.list_for_org(db, current.org_id)
    return [await _to_response(db, pub) for pub in publications]


@router.get("/current", response_model=PublicationDetailResponse)
async def get_current(
    current: CurrentUser = Depends(_trading_console), db: AsyncSession = Depends(get_db)
) -> PublicationDetailResponse:
    publication = await publications_repo.get_current_for_org(db, current.org_id)
    if publication is None:
        raise NotFound("Publication")
    return await _to_detail(db, publication)


@router.get("/{publication_id}", response_model=PublicationDetailResponse)
async def get_publication(
    publication_id: uuid.UUID, current: CurrentUser = Depends(_trading_console), db: AsyncSession = Depends(get_db)
) -> PublicationDetailResponse:
    publication = await publications_repo.get_by_id(db, publication_id)
    if publication is None or publication.org_id != current.org_id:
        raise NotFound("Publication")
    return await _to_detail(db, publication)
