"""Content-addressed acknowledgment carry-forward — the fix for the design
flaw where every daily snapshot recreates every OrderLine from scratch
(services/ingestion_service.py's commit_snapshot), so a WARN/CORRECTION
issue's acknowledgment — scoped to that ephemeral row — could never survive
to the next day's snapshot even when nothing about the order changed.

`find_matching` is called from services/calculate_service.py for every
WARN/CORRECTION issue it raises, before persisting the new
ValidationIssueRecord: if this exact order (by identity_key) had this exact
issue (by code + column_ref) acknowledged against this exact content (by
domain.ingestion.diff.line_content_fingerprint), the new issue row is
pre-stamped acknowledged instead of reopened. `record` is called from the
manual acknowledge endpoint (api/v1/snapshots.py) to persist that fact
durably, keyed by identity rather than by the row being acknowledged.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from domain.ingestion.diff import line_content_fingerprint
from models.order_issue_acknowledgment import OrderIssueAcknowledgment
from models.order_line import OrderLine
from repositories import order_issue_acknowledgments as acks_repo


def _identity(order_line: OrderLine) -> tuple[str | None, str | None, str | None, str | None]:
    incoterm = order_line.incoterm.value if order_line.incoterm else None
    return (order_line.contract_no, order_line.species, order_line.product_type, incoterm)


async def find_matching(
    db: AsyncSession, order_line: OrderLine, *, org_id: uuid.UUID, code: str, column_ref: str | None
) -> OrderIssueAcknowledgment | None:
    """None if never acknowledged, or if acknowledged against a fingerprint
    that no longer matches this line's current content (i.e. the order
    changed since — a fresh review is required, not a carry-forward)."""
    contract_no, species, product_type, incoterm = _identity(order_line)
    ack = await acks_repo.get_for_identity(
        db,
        org_id=org_id,
        contract_no=contract_no,
        species=species,
        product_type=product_type,
        incoterm=incoterm,
        issue_code=code,
        column_ref=column_ref,
    )
    if ack is None or ack.fingerprint != line_content_fingerprint(order_line):
        return None
    return ack


async def confirm_still_valid(db: AsyncSession, ack: OrderIssueAcknowledgment, *, snapshot_id: uuid.UUID) -> None:
    await acks_repo.touch_confirmed(db, ack, snapshot_id=snapshot_id)


async def record(
    db: AsyncSession,
    order_line: OrderLine,
    *,
    org_id: uuid.UUID,
    code: str,
    column_ref: str | None,
    acknowledged_by: uuid.UUID,
    snapshot_id: uuid.UUID,
) -> OrderIssueAcknowledgment:
    contract_no, species, product_type, incoterm = _identity(order_line)
    return await acks_repo.upsert(
        db,
        org_id=org_id,
        contract_no=contract_no,
        species=species,
        product_type=product_type,
        incoterm=incoterm,
        issue_code=code,
        column_ref=column_ref,
        fingerprint=line_content_fingerprint(order_line),
        acknowledged_by=acknowledged_by,
        acknowledged_at=datetime.now(UTC),
        snapshot_id=snapshot_id,
    )
