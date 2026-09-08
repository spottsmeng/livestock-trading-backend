"""§5.7 `DNBP_OUTLIER` — deferred by Phase 2 ("nothing has been published
yet"); buildable now. Publishing the same file twice in a row means every
species' second-calculation average is exactly its own first published
value, so a deliberately mutated factor is what actually creates the >15%
deviation to test against without waiting on 30 real days of history.
"""

from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from domain.engine.issues import DNBP_OUTLIER, check_dnbp_outlier
from models.organisation import Organisation
from tests.pipeline_helpers import accountant_headers, build_publishable_snapshot


def test_check_dnbp_outlier_pure_function_flags_large_deviation():
    issue = check_dnbp_outlier(Decimal("10.00"), Decimal("8.00"))  # 25% off
    assert issue is not None
    assert issue.code == DNBP_OUTLIER


def test_check_dnbp_outlier_pure_function_ignores_small_deviation():
    assert check_dnbp_outlier(Decimal("8.30"), Decimal("8.00")) is None  # 3.75% off


def test_check_dnbp_outlier_pure_function_needs_no_history():
    assert check_dnbp_outlier(Decimal("8.30"), None) is None
    assert check_dnbp_outlier(None, Decimal("8.00")) is None


async def test_outlier_does_not_fire_on_first_ever_publication(client, db: AsyncSession, everhealth_org: Organisation):
    """No publication history exists yet for this org — the rule must not
    invent a baseline to compare against (domain/engine/issues.py's own
    contract: None in, None out)."""
    headers = await accountant_headers(client, db, everhealth_org, email="bing-outlier1@test.com")
    snapshot = await build_publishable_snapshot(client, headers)

    issues_resp = await client.get(f"/api/v1/snapshots/{snapshot['id']}/issues", headers=headers)
    codes = {issue["code"] for issue in issues_resp.json()}
    assert DNBP_OUTLIER not in codes
