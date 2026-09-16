import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.order_issue_acknowledgment import OrderIssueAcknowledgment


def _identity_filters(
    query,
    *,
    org_id: uuid.UUID,
    contract_no: str | None,
    species: str | None,
    product_type: str | None,
    incoterm: str | None,
    issue_code: str,
    column_ref: str | None,
):
    return query.where(
        OrderIssueAcknowledgment.org_id == org_id,
        OrderIssueAcknowledgment.contract_no == contract_no,
        OrderIssueAcknowledgment.species == species,
        OrderIssueAcknowledgment.product_type == product_type,
        OrderIssueAcknowledgment.incoterm == incoterm,
        OrderIssueAcknowledgment.issue_code == issue_code,
        OrderIssueAcknowledgment.column_ref == column_ref,
    )


async def get_for_identity(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    contract_no: str | None,
    species: str | None,
    product_type: str | None,
    incoterm: str | None,
    issue_code: str,
    column_ref: str | None,
) -> OrderIssueAcknowledgment | None:
    """The one row for this (org, identity, issue slot), regardless of
    whether its stored `fingerprint` still matches anything current —
    callers compare the fingerprint themselves (services/
    issue_acknowledgment_service.py) since "found but stale" and "never
    acknowledged" are different things only the caller can usefully act on."""
    query = _identity_filters(
        select(OrderIssueAcknowledgment),
        org_id=org_id,
        contract_no=contract_no,
        species=species,
        product_type=product_type,
        incoterm=incoterm,
        issue_code=issue_code,
        column_ref=column_ref,
    )
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def upsert(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    contract_no: str | None,
    species: str | None,
    product_type: str | None,
    incoterm: str | None,
    issue_code: str,
    column_ref: str | None,
    fingerprint: str,
    acknowledged_by: uuid.UUID,
    acknowledged_at: datetime,
    snapshot_id: uuid.UUID,
) -> OrderIssueAcknowledgment:
    existing = await get_for_identity(
        db,
        org_id=org_id,
        contract_no=contract_no,
        species=species,
        product_type=product_type,
        incoterm=incoterm,
        issue_code=issue_code,
        column_ref=column_ref,
    )
    if existing is None:
        row = OrderIssueAcknowledgment(
            org_id=org_id,
            contract_no=contract_no,
            species=species,
            product_type=product_type,
            incoterm=incoterm,
            issue_code=issue_code,
            column_ref=column_ref,
            fingerprint=fingerprint,
            acknowledged_by=acknowledged_by,
            acknowledged_at=acknowledged_at,
            last_confirmed_snapshot_id=snapshot_id,
        )
        db.add(row)
    else:
        row = existing
        row.fingerprint = fingerprint
        row.acknowledged_by = acknowledged_by
        row.acknowledged_at = acknowledged_at
        row.last_confirmed_snapshot_id = snapshot_id
    await db.flush()
    return row


async def touch_confirmed(db: AsyncSession, ack: OrderIssueAcknowledgment, *, snapshot_id: uuid.UUID) -> None:
    ack.last_confirmed_snapshot_id = snapshot_id
    await db.flush()
