import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import CurrentUser, require_role
from core.db import get_db
from core.errors import NotFound
from models.enums import CorrectionStatus, Role
from repositories import correction_requests as correction_requests_repo
from repositories import order_snapshots as order_snapshots_repo
from schemas.correction_requests import CorrectionRequestResponse
from services import correction_service

router = APIRouter(prefix="/correction-requests", tags=["correction-requests"])

_trading_console = require_role(Role.OWNER, Role.ACCOUNTANT)


@router.get("", response_model=list[CorrectionRequestResponse])
async def list_correction_requests(
    status: CorrectionStatus | None = Query(default=None),
    snapshot_id: uuid.UUID | None = Query(default=None),
    current: CurrentUser = Depends(_trading_console),
    db: AsyncSession = Depends(get_db),
) -> list[CorrectionRequestResponse]:
    """§11.6 — the Correction Requests queue. Internal only: there is no
    filter, field, or route anywhere that sends one of these to the
    abattoir (§2.1.1)."""
    requests = await correction_requests_repo.list_for_org(db, current.org_id, status=status, snapshot_id=snapshot_id)
    return [CorrectionRequestResponse.model_validate(r) for r in requests]


@router.post("/{request_id}/withdraw", response_model=CorrectionRequestResponse)
async def withdraw(
    request_id: uuid.UUID, current: CurrentUser = Depends(_trading_console), db: AsyncSession = Depends(get_db)
) -> CorrectionRequestResponse:
    existing = await correction_requests_repo.get_by_id(db, request_id)
    if existing is None:
        raise NotFound("Correction request")
    snapshot = await order_snapshots_repo.get_by_id(db, existing.snapshot_id)
    if snapshot is None or snapshot.org_id != current.org_id:
        raise NotFound("Correction request")

    request = await correction_service.withdraw(db, request_id=request_id, actor_id=current.user_id)
    await db.commit()
    return CorrectionRequestResponse.model_validate(request)
