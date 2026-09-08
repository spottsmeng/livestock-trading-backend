import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.correction_request import CorrectionRequest
from models.enums import CorrectionStatus
from models.order_line import OrderLine
from models.order_snapshot import OrderSnapshot


async def create(db: AsyncSession, request: CorrectionRequest) -> CorrectionRequest:
    db.add(request)
    await db.flush()
    return request


async def get_by_id(db: AsyncSession, request_id: uuid.UUID) -> CorrectionRequest | None:
    return await db.get(CorrectionRequest, request_id)


async def list_open_for_org(db: AsyncSession, org_id: uuid.UUID) -> list[CorrectionRequest]:
    """Every OPEN request against this org's data — the candidate set an
    auto-resolve pass checks after each new snapshot's calculate step
    (§9.3)."""
    result = await db.execute(
        select(CorrectionRequest)
        .join(OrderSnapshot, OrderSnapshot.id == CorrectionRequest.snapshot_id)
        .where(CorrectionRequest.status == CorrectionStatus.OPEN, OrderSnapshot.org_id == org_id)
    )
    return list(result.scalars().all())


async def list_for_org(
    db: AsyncSession,
    org_id: uuid.UUID,
    *,
    status: CorrectionStatus | None = None,
    snapshot_id: uuid.UUID | None = None,
) -> list[CorrectionRequest]:
    stmt = (
        select(CorrectionRequest)
        .join(OrderSnapshot, OrderSnapshot.id == CorrectionRequest.snapshot_id)
        .where(OrderSnapshot.org_id == org_id)
    )
    if status is not None:
        stmt = stmt.where(CorrectionRequest.status == status)
    if snapshot_id is not None:
        stmt = stmt.where(CorrectionRequest.snapshot_id == snapshot_id)
    result = await db.execute(stmt.order_by(CorrectionRequest.raised_at.desc()))
    return list(result.scalars().all())


async def order_line_for(db: AsyncSession, request: CorrectionRequest) -> OrderLine | None:
    return await db.get(OrderLine, request.order_line_id)
