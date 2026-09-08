import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import CurrentUser, require_role
from core.db import get_db
from core.errors import NotFound
from models.audit_log import AuditLog
from models.enums import Role
from repositories import order_lines as order_lines_repo
from repositories import order_snapshots as order_snapshots_repo
from repositories import order_workings as order_workings_repo
from schemas.correction_requests import CorrectionRequestResponse, CreateCorrectionRequest
from schemas.order_lines import DnbpProofResponse, OrderWorkingsResponse
from schemas.snapshots import IssueResponse
from schemas.users import AuditEntryResponse
from services import correction_service

router = APIRouter(prefix="/order-lines", tags=["order-lines"])

_trading_console = require_role(Role.OWNER, Role.ACCOUNTANT)


async def _get_owned_line(db: AsyncSession, order_line_id: uuid.UUID, org_id: uuid.UUID):
    line = await order_lines_repo.get_by_id(db, order_line_id)
    if line is None:
        raise NotFound("Order line")
    snapshot = await order_snapshots_repo.get_by_id(db, line.snapshot_id)
    if snapshot is None or snapshot.org_id != org_id:
        raise NotFound("Order line")
    return line


@router.get("/{order_line_id}")
async def get_line(
    order_line_id: uuid.UUID, current: CurrentUser = Depends(_trading_console), db: AsyncSession = Depends(get_db)
):
    from api.v1.snapshots import _to_line_response  # local import avoids a route-module import cycle

    line = await _get_owned_line(db, order_line_id, current.org_id)
    return _to_line_response(line)


@router.get("/{order_line_id}/workings", response_model=OrderWorkingsResponse)
async def get_workings(
    order_line_id: uuid.UUID, current: CurrentUser = Depends(_trading_console), db: AsyncSession = Depends(get_db)
) -> OrderWorkingsResponse:
    await _get_owned_line(db, order_line_id, current.org_id)
    workings = await order_workings_repo.get_by_order_line_id(db, order_line_id)
    if workings is None:
        raise NotFound("Order workings")
    return OrderWorkingsResponse.model_validate(workings)


@router.get("/{order_line_id}/dnbp-proof", response_model=DnbpProofResponse)
async def get_dnbp_proof(
    order_line_id: uuid.UUID, current: CurrentUser = Depends(_trading_console), db: AsyncSession = Depends(get_db)
) -> DnbpProofResponse:
    """§11.3's DNBP proof panel — the isolated AC derivation shown as one
    line, exactly what earns Bing's trust (§9.3)."""
    line = await _get_owned_line(db, order_line_id, current.org_id)
    workings = await order_workings_repo.get_by_order_line_id(db, order_line_id)
    if workings is None or workings.bing_dnbp is None or line.avg_price_aud is None:
        raise NotFound("DNBP proof")

    cif_buffer = workings.bing_dnbp_inputs.get("cif_buffer_per_kg")
    factor = workings.bing_dnbp_factor_used
    formula = f"({line.avg_price_aud} − {cif_buffer}) × {factor} = {workings.bing_dnbp}"

    return DnbpProofResponse(
        order_line_id=order_line_id,
        avg_price_aud=line.avg_price_aud,
        cif_buffer_per_kg=cif_buffer,
        dnbp_factor=factor,
        bing_dnbp=workings.bing_dnbp,
        engine_version=workings.engine_version,
        ref_data_version=workings.ref_data_version,
        computed_at=workings.computed_at,
        formula=formula,
    )


@router.get("/{order_line_id}/issues", response_model=list[IssueResponse])
async def get_issues(
    order_line_id: uuid.UUID, current: CurrentUser = Depends(_trading_console), db: AsyncSession = Depends(get_db)
) -> list[IssueResponse]:
    from repositories import validation_issues as validation_issues_repo

    await _get_owned_line(db, order_line_id, current.org_id)
    issues = await validation_issues_repo.list_by_order_line(db, order_line_id)
    return [IssueResponse.model_validate(i) for i in issues]


@router.get("/{order_line_id}/audit", response_model=list[AuditEntryResponse])
async def get_audit(
    order_line_id: uuid.UUID, current: CurrentUser = Depends(_trading_console), db: AsyncSession = Depends(get_db)
) -> list[AuditEntryResponse]:
    """Every audited action concerning this line: any correction request
    raised/withdrawn/auto-resolved against it (order_lines themselves are
    never mutated, so no "order_line"-entity audit rows exist yet, but the
    query already covers that entity type for when a future action needs
    one)."""
    from models.correction_request import CorrectionRequest

    await _get_owned_line(db, order_line_id, current.org_id)
    correction_request_ids = (
        await db.execute(select(CorrectionRequest.id).where(CorrectionRequest.order_line_id == order_line_id))
    ).scalars().all()

    result = await db.execute(
        select(AuditLog)
        .where(
            (AuditLog.entity == "order_line") & (AuditLog.entity_id == order_line_id)
            | (AuditLog.entity == "correction_request") & AuditLog.entity_id.in_(correction_request_ids)
        )
        .order_by(AuditLog.at.desc())
    )
    return list(result.scalars().all())


@router.post("/{order_line_id}/correction-requests", response_model=CorrectionRequestResponse, status_code=201)
async def create_correction_request(
    order_line_id: uuid.UUID,
    body: CreateCorrectionRequest,
    current: CurrentUser = Depends(_trading_console),
    db: AsyncSession = Depends(get_db),
) -> CorrectionRequestResponse:
    """§2.1.1, §9.3, §11.6 — the only sanctioned way to flag a defect in
    received A-V data. Internal only: this never notifies the abattoir."""
    await _get_owned_line(db, order_line_id, current.org_id)
    request = await correction_service.raise_request(
        db,
        order_line_id=order_line_id,
        column_ref=body.column_ref,
        issue_code=body.issue_code,
        detail=body.detail,
        raised_by=current.user_id,
    )
    await db.commit()
    return CorrectionRequestResponse.model_validate(request)
