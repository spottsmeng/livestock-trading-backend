"""fixtures/bidcheck-test-vectors.json — the same golden-vector discipline
`fixtures/engine-test-vectors.json` already established for the DNBP
engine, applied to domain/buyer/bidcheck.py. frontend/lib/buyer/bidcheck.ts
is a line-for-line TS mirror verified against the same file (no JS test
runner exists yet in this repo to automate that side — see this phase's
plan for why that's a deliberate, named gap rather than an oversight).

fixtures/ is vendored inside backend/ — see backend/fixtures/README.md."""

import json
from decimal import Decimal
from pathlib import Path

import pytest

from domain.buyer.bidcheck import score_bid

FIXTURE_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "bidcheck-test-vectors.json"


def _load_vectors() -> list[dict]:
    data = json.loads(FIXTURE_PATH.read_text())
    return data["vectors"], data["close_threshold_pct"]


_VECTORS, _CLOSE_THRESHOLD = _load_vectors()


@pytest.mark.parametrize("vector", _VECTORS, ids=[v["name"] for v in _VECTORS])
def test_bidcheck_golden_vector(vector: dict):
    result = score_bid(
        price_per_head=Decimal(vector["price_per_head"]),
        weight_kg=Decimal(vector["weight_kg"]),
        dnbp_per_kg=Decimal(vector["dnbp_per_kg"]),
        close_threshold_pct=Decimal(str(_CLOSE_THRESHOLD)),
    )
    assert abs(result.implied_price_per_kg - Decimal(vector["implied_price_per_kg"])) < Decimal("1E-9")
    assert result.status.value == vector["status"]
    assert result.is_breach == vector["is_breach"]
    assert result.max_price_per_head == Decimal(vector["max_price_per_head"])
