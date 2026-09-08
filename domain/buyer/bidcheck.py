"""Bid Check scoring (PRD §12.3) — pure, no I/O, mirrored line-for-line in
TypeScript at frontend/lib/buyer/bidcheck.ts so the buyer's PWA can score a
bid fully offline (§12.7) against its cached DNBP. Both implementations are
verified against the same fixture, fixtures/bidcheck-test-vectors.json —
the same golden-vector discipline domain/engine/dnbp.py already uses for
`AC` itself.

This module is deliberately separate from domain/engine/ — it never touches
`compute_bing_dnbp` or any order-line input. It only ever sees an already-
published `dnbp_per_kg` and a candidate bid; it has no way to influence what
that DNBP is and cannot corrupt it.
"""

import enum
from dataclasses import dataclass
from decimal import ROUND_FLOOR, Decimal


class BidStatus(enum.StrEnum):
    """§12.3, §15.4 — the only three states, each with a fixed colour
    meaning used identically everywhere (never repurposed for anything
    else, per §15.4)."""

    PASS = "PASS"
    CLOSE = "CLOSE"
    BREACH = "BREACH"


@dataclass(frozen=True, slots=True)
class BidCheckResult:
    implied_price_per_kg: Decimal
    status: BidStatus
    variance_per_kg: Decimal  # dnbp_per_kg - implied_price_per_kg; negative = over DNBP
    max_price_per_head: Decimal  # §12.3 "reverse mode" — the figure a buyer actually bids with
    is_breach: bool


def score_bid(
    *,
    price_per_head: Decimal,
    weight_kg: Decimal,
    dnbp_per_kg: Decimal,
    close_threshold_pct: Decimal,
) -> BidCheckResult:
    """§12.3's calculator. `close_threshold_pct` is
    EverhealthConfig-sourced (seed: `bid_check_close_threshold_pct` = 5) —
    never hard-coded here, since it is business-tunable.

    Guarded per §5.5's division discipline even though a zero weight should
    never reach this function from a real form: returns a BREACH-safe
    result (max_price_per_head = 0) rather than raising or emitting Inf.
    """
    if weight_kg <= 0:
        return BidCheckResult(
            implied_price_per_kg=Decimal("0"),
            status=BidStatus.BREACH,
            variance_per_kg=dnbp_per_kg,
            max_price_per_head=Decimal("0"),
            is_breach=True,
        )

    implied_price_per_kg = price_per_head / weight_kg
    variance_per_kg = dnbp_per_kg - implied_price_per_kg
    max_price_per_head = (dnbp_per_kg * weight_kg).quantize(Decimal("0.01"), rounding=ROUND_FLOOR)

    is_breach = implied_price_per_kg > dnbp_per_kg
    if is_breach:
        status = BidStatus.BREACH
    else:
        # CLOSE = within close_threshold_pct of the ceiling, i.e. headroom
        # (dnbp - implied) is less than that percentage of dnbp itself.
        headroom_pct = (variance_per_kg / dnbp_per_kg * 100) if dnbp_per_kg > 0 else Decimal("0")
        status = BidStatus.CLOSE if headroom_pct < close_threshold_pct else BidStatus.PASS

    return BidCheckResult(
        implied_price_per_kg=implied_price_per_kg,
        status=status,
        variance_per_kg=variance_per_kg,
        max_price_per_head=max_price_per_head,
        is_breach=is_breach,
    )
