"""§2.1.1, §9.3 — raising and withdrawing a correction request. There is no
function anywhere in this module (or this codebase) that sends anything to
the abattoir — see models/correction_request.py's docstring. Auto-resolve
lives in services/calculate_service.py, next to the calculation step that
detects a later valid value.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import Conflict, NotFound
from models.correction_request import CorrectionRequest
from models.enums import CorrectionStatus
from repositories import correction_requests as correction_requests_repo
from repositories import order_lines as order_lines_repo
from services import audit_service


async def raise_request(
    db: AsyncSession,
    *,
    order_line_id: uuid.UUID,
    column_ref: str,
    issue_code: str,
    detail: str | None,
    raised_by: uuid.UUID,
) -> CorrectionRequest:
    order_line = await order_lines_repo.get_by_id(db, order_line_id)
    if order_line is None:
        raise NotFound("Order line")

    request = CorrectionRequest(
        snapshot_id=order_line.snapshot_id,
        order_line_id=order_line_id,
        raised_by=raised_by,
        column_ref=column_ref,
        issue_code=issue_code,
        detail=detail,
        status=CorrectionStatus.OPEN,
    )
    await correction_requests_repo.create(db, request)

    await audit_service.write(
        db,
        actor_id=raised_by,
        action="correction_request.raised",
        entity="correction_request",
        entity_id=request.id,
        after={"column_ref": column_ref, "issue_code": issue_code, "order_line_id": str(order_line_id)},
    )
    return request


async def withdraw(db: AsyncSession, *, request_id: uuid.UUID, actor_id: uuid.UUID) -> CorrectionRequest:
    request = await correction_requests_repo.get_by_id(db, request_id)
    if request is None:
        raise NotFound("Correction request")
    if request.status != CorrectionStatus.OPEN:
        raise Conflict("NOT_OPEN", "Only an OPEN correction request can be withdrawn.")

    request.status = CorrectionStatus.WITHDRAWN
    request.resolved_at = datetime.now(UTC)

    await audit_service.write(
        db,
        actor_id=actor_id,
        action="correction_request.withdrawn",
        entity="correction_request",
        entity_id=request.id,
        before={"status": CorrectionStatus.OPEN.value},
        after={"status": CorrectionStatus.WITHDRAWN.value},
    )
    return request
