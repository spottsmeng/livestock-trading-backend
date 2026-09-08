"""§9.9 — WS ticket issuance and single-use consumption. The actual
`/ws/buyer`/`/ws/console` handshake isn't exercised over HTTP here (httpx
has no websocket transport); ws/tickets.py's issue/consume pair is unit-
tested directly, and `POST /ws/ticket` is exercised as the ordinary
authenticated REST route it is.
"""

import pytest
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import TicketInvalid
from models.enums import Role
from models.organisation import Organisation
from tests.pipeline_helpers import accountant_headers
from ws.tickets import consume_ticket, issue_ticket


async def test_ticket_route_requires_auth(client):
    resp = await client.post("/api/v1/ws/ticket")
    assert resp.status_code == 401


async def test_ticket_route_issues_a_ticket_for_any_authenticated_role(
    client, db: AsyncSession, everhealth_org: Organisation
):
    headers = await accountant_headers(client, db, everhealth_org, email="bing-ws1@test.com")
    resp = await client.post("/api/v1/ws/ticket", headers=headers)
    assert resp.status_code == 200
    assert len(resp.json()["ticket"]) > 20


async def test_ticket_is_single_use(redis_client: Redis, everhealth_org: Organisation):
    ticket = await issue_ticket(redis_client, user_id=everhealth_org.id, role=Role.BUYER, org_id=everhealth_org.id)

    payload = await consume_ticket(redis_client, ticket)
    assert payload.role is Role.BUYER
    assert payload.org_id == everhealth_org.id

    with pytest.raises(TicketInvalid):
        await consume_ticket(redis_client, ticket)


async def test_unknown_ticket_is_invalid(redis_client: Redis):
    with pytest.raises(TicketInvalid):
        await consume_ticket(redis_client, "not-a-real-ticket")
