import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import CurrentUser, require_role
from core.db import get_db
from models.enums import Role
from schemas.order_line_removals import AcknowledgeRemovalRequest, OrderLineRemovalResponse
from services import order_line_removal_service

router = APIRouter(prefix="/order-line-removals", tags=["order-line-removals"])

_trading_console = require_role(Role.OWNER, Role.ACCOUNTANT)


@router.get("", response_model=list[OrderLineRemovalResponse])
async def list_removals(
    unacknowledged: bool = Query(default=False),
    current: CurrentUser = Depends(_trading_console),
    db: AsyncSession = Depends(get_db),
):
    return await order_line_removal_service.list_removals(db, unacknowledged_only=unacknowledged)


@router.post("/{removal_id}/acknowledge", response_model=OrderLineRemovalResponse)
async def acknowledge_removal(
    removal_id: uuid.UUID,
    body: AcknowledgeRemovalRequest,
    current: CurrentUser = Depends(_trading_console),
    db: AsyncSession = Depends(get_db),
):
    removal = await order_line_removal_service.acknowledge(
        db, removal_id, actor_id=current.user_id, reason=body.reason
    )
    await db.commit()
    return removal
