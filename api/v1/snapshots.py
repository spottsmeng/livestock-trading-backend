import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, File, Query, UploadFile
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import CurrentUser, redis_dep, require_role
from core.db import get_db
from core.errors import Conflict, NotFound
from core.object_storage import ObjectStorage, get_object_storage
from domain.engine.issues import Severity
from domain.engine.workings import Lifecycle
from models.enums import Role, SnapshotStatus
from repositories import order_lines as order_lines_repo
from repositories import order_snapshots as order_snapshots_repo
from repositories import order_workings as order_workings_repo
from repositories import validation_issues as validation_issues_repo
from schemas.order_lines import OrderLineResponse, OrderWorkingsResponse
from schemas.snapshots import (
    CalculateResponse,
    CommitSnapshotRequest,
    IssueResponse,
    SnapshotResponse,
    UploadPreviewResponse,
)
from services import audit_service, calculate_service, ingestion_service

router = APIRouter(prefix="/snapshots", tags=["snapshots"])

# §9.2 — snapshot/ingestion routes are OWNER + ACCOUNTANT only. Both may
# upload (§11.2) — the abattoir's email may land with either of them.
_trading_console = require_role(Role.OWNER, Role.ACCOUNTANT)


def _storage_dep() -> ObjectStorage:
    return get_object_storage()


def _to_line_response(line) -> OrderLineResponse:
    return OrderLineResponse(
        id=line.id,
        snapshot_id=line.snapshot_id,
        line_no=line.line_no,
        lifecycle=line.lifecycle.value,
        contract_no=line.contract_no,
        customer_name=line.customer_name,
        species=line.species,
        loadout_date=line.loadout_date,
        qty_kg=line.qty_kg,
        avg_price_aud=line.avg_price_aud,
        amount_aud=line.amount_aud,
        product_type=line.product_type,
        incoterm=line.incoterm.value if line.incoterm else None,
        nrv_per_kg=line.nrv_per_kg,
        expected_livestock_cost_per_kg=line.expected_livestock_cost_per_kg,
        pack_cost_ph=line.pack_cost_ph,
        offal_return_ph=line.offal_return_ph,
        skin_return_ph=line.skin_return_ph,
        avg_weight_kg=line.avg_weight_kg,
        mom_ph=line.mom_ph,
        deposit_received=line.deposit_received,
        comments=line.comments,
        dnbp_benchmark=line.dnbp_benchmark,
        benchmark_method=line.benchmark_method.value if line.benchmark_method else None,
        estimated_heads=line.estimated_heads,
        total_livestock_cost=line.total_livestock_cost,
        value_sources=line.value_sources,
    )


async def _get_owned_snapshot(db: AsyncSession, snapshot_id: uuid.UUID, org_id: uuid.UUID):
    snapshot = await order_snapshots_repo.get_by_id(db, snapshot_id)
    if snapshot is None or snapshot.org_id != org_id:
        raise NotFound("Snapshot")
    return snapshot


@router.post("/upload", response_model=UploadPreviewResponse)
async def upload(
    file: UploadFile = File(...),
    current: CurrentUser = Depends(_trading_console),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(redis_dep),
) -> UploadPreviewResponse:
    file_bytes = await file.read()
    preview = await ingestion_service.create_upload_preview(
        db, redis, org_id=current.org_id, file_bytes=file_bytes, filename=file.filename or "upload.xlsx"
    )
    return UploadPreviewResponse(**preview)


@router.post("", response_model=SnapshotResponse, status_code=201)
async def commit(
    body: CommitSnapshotRequest,
    current: CurrentUser = Depends(_trading_console),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(redis_dep),
    storage: ObjectStorage = Depends(_storage_dep),
) -> SnapshotResponse:
    snapshot = await ingestion_service.commit_snapshot(
        db, redis, storage, org_id=current.org_id, uploaded_by=current.user_id, preview_id=body.preview_id
    )
    await db.commit()
    return SnapshotResponse.model_validate(snapshot)


@router.get("", response_model=list[SnapshotResponse])
async def list_snapshots(
    current: CurrentUser = Depends(_trading_console), db: AsyncSession = Depends(get_db)
) -> list[SnapshotResponse]:
    snapshots = await order_snapshots_repo.list_for_org(db, current.org_id)
    return [SnapshotResponse.model_validate(s) for s in snapshots]


@router.get("/{snapshot_id}", response_model=SnapshotResponse)
async def get_snapshot(
    snapshot_id: uuid.UUID, current: CurrentUser = Depends(_trading_console), db: AsyncSession = Depends(get_db)
) -> SnapshotResponse:
    snapshot = await _get_owned_snapshot(db, snapshot_id, current.org_id)
    return SnapshotResponse.model_validate(snapshot)


@router.get("/{snapshot_id}/diff/{other_id}")
async def diff(
    snapshot_id: uuid.UUID,
    other_id: uuid.UUID,
    current: CurrentUser = Depends(_trading_console),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await _get_owned_snapshot(db, snapshot_id, current.org_id)
    await _get_owned_snapshot(db, other_id, current.org_id)
    return await ingestion_service.diff_snapshots(db, other_id, snapshot_id)


@router.get("/{snapshot_id}/lines", response_model=list[OrderLineResponse])
async def list_lines(
    snapshot_id: uuid.UUID,
    lifecycle: Lifecycle | None = Query(default=None),
    species: str | None = Query(default=None),
    current: CurrentUser = Depends(_trading_console),
    db: AsyncSession = Depends(get_db),
) -> list[OrderLineResponse]:
    await _get_owned_snapshot(db, snapshot_id, current.org_id)
    lines = await order_lines_repo.list_by_snapshot(db, snapshot_id, lifecycle=lifecycle, species=species)
    return [_to_line_response(line) for line in lines]


@router.get("/{snapshot_id}/workings", response_model=list[OrderWorkingsResponse])
async def list_workings(
    snapshot_id: uuid.UUID,
    current: CurrentUser = Depends(_trading_console),
    db: AsyncSession = Depends(get_db),
) -> list[OrderWorkingsResponse]:
    await _get_owned_snapshot(db, snapshot_id, current.org_id)
    workings = await order_workings_repo.list_by_snapshot_id(db, snapshot_id)
    return [OrderWorkingsResponse.model_validate(w) for w in workings]


@router.post("/{snapshot_id}/calculate", response_model=CalculateResponse)
async def calculate(
    snapshot_id: uuid.UUID, current: CurrentUser = Depends(_trading_console), db: AsyncSession = Depends(get_db)
) -> CalculateResponse:
    snapshot = await _get_owned_snapshot(db, snapshot_id, current.org_id)
    summary = await calculate_service.calculate_snapshot(db, snapshot, actor_id=current.user_id)
    snapshot.status = SnapshotStatus.CALCULATED
    await db.commit()
    return CalculateResponse(**summary)


@router.get("/{snapshot_id}/issues", response_model=list[IssueResponse])
async def list_issues(
    snapshot_id: uuid.UUID, current: CurrentUser = Depends(_trading_console), db: AsyncSession = Depends(get_db)
) -> list[IssueResponse]:
    await _get_owned_snapshot(db, snapshot_id, current.org_id)
    issues = await validation_issues_repo.list_by_snapshot(db, snapshot_id)
    return [IssueResponse.model_validate(i) for i in issues]


@router.post("/{snapshot_id}/issues/{issue_id}/acknowledge", response_model=IssueResponse)
async def acknowledge_issue(
    snapshot_id: uuid.UUID,
    issue_id: uuid.UUID,
    current: CurrentUser = Depends(_trading_console),
    db: AsyncSession = Depends(get_db),
) -> IssueResponse:
    """§5.7's publication gate, the other half of it: a WARN/CORRECTION
    issue on an active line must be explicitly acknowledged, with the
    acknowledger's id and a timestamp, before a publication can proceed
    (services/publication_service.py enforces this). Deferred from Phase 2
    by design — tied to publication, which didn't exist yet (§18)."""
    await _get_owned_snapshot(db, snapshot_id, current.org_id)
    issue = await validation_issues_repo.get_by_id(db, issue_id)
    if issue is None:
        raise NotFound("Issue")
    order_line = await order_lines_repo.get_by_id(db, issue.order_line_id)
    if order_line is None or order_line.snapshot_id != snapshot_id:
        raise NotFound("Issue")
    if issue.severity is Severity.BLOCK:
        raise Conflict(
            "CANNOT_ACKNOWLEDGE_BLOCK",
            "A BLOCK issue cannot be acknowledged away — it can only be resolved by a corrected submission.",
        )

    issue.acknowledged_by = current.user_id
    issue.acknowledged_at = datetime.now(UTC)

    await audit_service.write(
        db,
        actor_id=current.user_id,
        action="issue.acknowledged",
        entity="validation_issue",
        entity_id=issue.id,
        after={"code": issue.code, "severity": issue.severity.value},
    )
    await db.commit()
    return IssueResponse.model_validate(issue)
