import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import NotFound
from models.order_line_removal import OrderLineRemoval
from repositories import order_line_removals as removals_repo
from services import audit_service


async def list_removals(db: AsyncSession, *, unacknowledged_only: bool = False) -> list[OrderLineRemoval]:
    return await removals_repo.list_all(db, unacknowledged_only=unacknowledged_only)


async def acknowledge(
    db: AsyncSession, removal_id: uuid.UUID, *, actor_id: uuid.UUID, reason: str | None
) -> OrderLineRemoval:
    removal = await removals_repo.get_by_id(db, removal_id)
    if removal is None:
        raise NotFound("Order line removal")

    await removals_repo.acknowledge(db, removal, acknowledged_by=actor_id, reason=reason)
    await audit_service.write(
        db,
        actor_id=actor_id,
        action="order_line_removal.acknowledged",
        entity="order_line_removal",
        entity_id=removal.id,
        after={"contract_no": removal.contract_no, "species": removal.species, "reason": reason},
    )
    return removal
