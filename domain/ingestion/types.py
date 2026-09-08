"""Closed enums intrinsic to parsing itself (PRD §6.9's `closed_enums`
list: `benchmark_method`, `value_source`). Defined here, in the domain
layer, and reused by the persistence layer (models/order_line.py) — the
same direction as domain/engine/workings.py's `Lifecycle`, so the
vocabulary has exactly one definition regardless of which layer needs a
SQLAlchemy column type for it.
"""

import enum


class BenchmarkMethod(enum.StrEnum):
    GAYAN_FIXED_COST = "GAYAN_FIXED_COST"
    FINANCIER_MARGIN = "FINANCIER_MARGIN"
    UNKNOWN = "UNKNOWN"


class ValueSource(enum.StrEnum):
    FORMULA = "FORMULA"
    HAND_SET = "HAND_SET"
