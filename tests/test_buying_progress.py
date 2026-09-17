"""domain/buyer/buying_progress.py — the anchor-finding logic behind the
live bought-vs-target counter. See that module's docstring for why "reset
on every publish" is wrong and "reset only when target_heads changes" is
the confirmed behaviour."""

from datetime import UTC, datetime
from decimal import Decimal

from domain.buyer.buying_progress import PublicationSnapshot, find_progress_anchor

T0 = datetime(2026, 9, 1, tzinfo=UTC)
T1 = datetime(2026, 9, 2, tzinfo=UTC)
T2 = datetime(2026, 9, 3, tzinfo=UTC)
T3 = datetime(2026, 9, 4, tzinfo=UTC)
NOW = datetime(2026, 9, 5, tzinfo=UTC)


def test_no_history_anchors_to_now():
    assert find_progress_anchor([], Decimal("100"), NOW) == NOW


def test_species_absent_from_history_anchors_to_now():
    # A species with no prior publication line at all reads the same as
    # "no history" once the caller has already filtered to snapshots with
    # target_heads=None for that gap — treated as differing from any real
    # target, so it never extends the streak.
    history = [PublicationSnapshot(effective_from=T0, target_heads=None)]
    assert find_progress_anchor(history, Decimal("100"), NOW) == NOW


def test_one_identical_prior_extends_anchor_back():
    history = [PublicationSnapshot(effective_from=T0, target_heads=Decimal("100"))]
    assert find_progress_anchor(history, Decimal("100"), NOW) == T0


def test_immediately_different_prior_anchors_to_now():
    history = [PublicationSnapshot(effective_from=T0, target_heads=Decimal("50"))]
    assert find_progress_anchor(history, Decimal("100"), NOW) == NOW


def test_several_identical_priors_then_an_older_change():
    history = [
        PublicationSnapshot(effective_from=T0, target_heads=Decimal("50")),
        PublicationSnapshot(effective_from=T1, target_heads=Decimal("100")),
        PublicationSnapshot(effective_from=T2, target_heads=Decimal("100")),
        PublicationSnapshot(effective_from=T3, target_heads=Decimal("100")),
    ]
    # T1/T2/T3 all asked for 100 head; T0 asked for 50. The unbroken run of
    # "100" starts at T1, so that's the anchor — T0 must not extend it
    # further even though it's older.
    assert find_progress_anchor(history, Decimal("100"), NOW) == T1


def test_target_change_partway_resets_anchor_to_the_change_point():
    history = [
        PublicationSnapshot(effective_from=T0, target_heads=Decimal("100")),
        PublicationSnapshot(effective_from=T1, target_heads=Decimal("100")),
        PublicationSnapshot(effective_from=T2, target_heads=Decimal("200")),
    ]
    # Current target is 200, same as T2 only — T0/T1 were a different
    # (now-irrelevant) target, so the anchor is T2, not further back.
    assert find_progress_anchor(history, Decimal("200"), NOW) == T2
