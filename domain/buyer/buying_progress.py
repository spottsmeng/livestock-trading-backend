"""Beyond §8/§9.4's literal spec — same documented-deviation pattern as
`buy_instruction_line_fills`/`dnbp_publication_deliveries`. Confirmed with
Terence: nothing tells the buyer or the office how many head of a species
have actually been bought against `target_heads` while buying is happening
(the species home screen shows a static, never-decrementing target; the Buy
Instruction reconciliation is manual and hours-to-days after the fact).

This module is the pure core of the fix: given one species' publication
history, find the point in time "progress so far" should be measured from.

The naive choice — reset to zero on every publish — is wrong. Comparing the
real order book across two upload dates three days apart showed an
unfulfilled order's `estimated_heads` is byte-identical day to day; the
source data never partially decrements a still-active order. Since Bing
republishes roughly once per trading day, resetting on every publish would
zero out real multi-day progress on day 2+ of any buy that spans more than
one day — reintroducing the exact overbuying risk this feature exists to
prevent. Confirmed with Terence: only reset when the species' `target_heads`
actually changes between consecutive publications.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class PublicationSnapshot:
    """The minimal shape this module needs from a (DnbpPublication,
    DnbpPublicationLine | None) pair — kept independent of the ORM models so
    this stays pure and unit-testable with plain values, the same discipline
    bidcheck.py already follows."""

    effective_from: datetime
    target_heads: Decimal | None


def find_progress_anchor(
    history: list[PublicationSnapshot], current_target: Decimal | None, current_effective_from: datetime
) -> datetime:
    """`history` is every past publication for one species, ascending by
    `effective_from`, NOT including the current/live publication itself.

    Walks backward from the most recent entry in `history` and keeps going
    while that entry's `target_heads` still equals `current_target` — i.e.
    finds the start of the unbroken run of publications that all asked for
    the same number of head. The anchor is the earliest publication in that
    run. If there's no history at all, or the most recent entry's target
    already differs (the species is new, or its target just changed), the
    anchor is the current publication's own `effective_from` — progress
    starts counting from right now.
    """
    if not history:
        return current_effective_from

    anchor = current_effective_from
    for snapshot in reversed(history):
        if snapshot.target_heads != current_target:
            break
        anchor = snapshot.effective_from
    return anchor
