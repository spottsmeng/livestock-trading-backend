"""§9.9 — real-time delivery. `POST /ws/ticket` is an ordinary authenticated
route (any role) that hands out a single-use ticket for the WS handshake
(see ws/tickets.py's module docstring for why). `/ws/buyer` and
`/ws/console` are NOT walked by tests/test_rbac_deny_by_default.py's
`_all_api_routes()` — that test only collects `APIRoute` instances, and
FastAPI represents a websocket endpoint as a distinct `APIWebSocketRoute`
type — so they are authenticated here, at the handshake, via the ticket
alone rather than via `Depends(get_current_user)`.
"""

import asyncio
import contextlib

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from redis.asyncio import Redis

from api.deps import CurrentUser, redis_dep, require_role
from models.enums import Role
from schemas.ws import TicketResponse
from ws import channels
from ws.tickets import consume_ticket
from ws.tickets import issue_ticket as _issue_ticket

router = APIRouter(tags=["ws"])

_any_role = require_role(Role.OWNER, Role.ACCOUNTANT, Role.BUYER)


@router.post("/ws/ticket", response_model=TicketResponse)
async def issue_ticket(current: CurrentUser = Depends(_any_role), redis: Redis = Depends(redis_dep)) -> TicketResponse:
    ticket = await _issue_ticket(redis, user_id=current.user_id, role=current.role, org_id=current.org_id)
    return TicketResponse(ticket=ticket)


async def _relay(websocket: WebSocket, redis: Redis, channel: str) -> None:
    await websocket.accept()
    pubsub = redis.pubsub()
    await pubsub.subscribe(channel)

    async def _forward() -> None:
        async for message in pubsub.listen():
            if message["type"] == "message":
                await websocket.send_text(message["data"])

    async def _watch_for_close() -> None:
        # The buyer/console client never needs to send anything over this
        # socket (delivery acks are a REST call, §10) — this loop exists
        # only to notice a client-initiated close promptly. A disconnect
        # without a close frame (tab close, refresh, HMR reload) raises
        # WebSocketDisconnect here — that's this task's normal exit, not
        # an error.
        with contextlib.suppress(WebSocketDisconnect):
            while True:
                await websocket.receive_text()

    forward_task = asyncio.create_task(_forward())
    watch_task = asyncio.create_task(_watch_for_close())
    try:
        await asyncio.wait({forward_task, watch_task}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        forward_task.cancel()
        watch_task.cancel()
        for task in (forward_task, watch_task):
            with contextlib.suppress(asyncio.CancelledError, WebSocketDisconnect):
                await task
        await pubsub.unsubscribe(channel)
        await pubsub.aclose()


@router.websocket("/ws/buyer")
async def ws_buyer(websocket: WebSocket, ticket: str, redis: Redis = Depends(redis_dep)) -> None:
    try:
        payload = await consume_ticket(redis, ticket)
    except Exception:
        await websocket.close(code=4401)
        return
    if payload.role is not Role.BUYER:
        await websocket.close(code=4403)
        return
    await _relay(websocket, redis, channels.buyer_channel(payload.org_id))


@router.websocket("/ws/console")
async def ws_console(websocket: WebSocket, ticket: str, redis: Redis = Depends(redis_dep)) -> None:
    try:
        payload = await consume_ticket(redis, ticket)
    except Exception:
        await websocket.close(code=4401)
        return
    if payload.role not in (Role.OWNER, Role.ACCOUNTANT):
        await websocket.close(code=4403)
        return
    await _relay(websocket, redis, channels.console_channel(payload.org_id))
