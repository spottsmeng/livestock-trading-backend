import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import NotFound
from models.reference_data import ReferenceDataDrift
from repositories import reference_data_drift as drift_repo
from services import audit_service


async def list_drift(db: AsyncSession, *, unacknowledged_only: bool = False) -> list[ReferenceDataDrift]:
    return await drift_repo.list_all(db, unacknowledged_only=unacknowledged_only)


async def acknowledge(db: AsyncSession, drift_id: uuid.UUID, *, actor_id: uuid.UUID) -> ReferenceDataDrift:
    drift = await drift_repo.get_by_id(db, drift_id)
    if drift is None:
        raise NotFound("Reference data drift")

    await drift_repo.acknowledge(db, drift, acknowledged_by=actor_id)
    await audit_service.write(
        db,
        actor_id=actor_id,
        action="reference_data_drift.acknowledged",
        entity="reference_data_drift",
        entity_id=drift.id,
        after={"table_key": drift.table_key, "key1": drift.key1},
    )
    return drift
