"""Validation issue types for the DNBP engine (PRD §5.7, §5.7.1).

Severity is a genuinely closed, small set of shapes the code itself branches
on (BLOCK gates publication, CORRECTION/WARN/INFO do not) — this is NOT the
same category as species/product_type (§6.9), which are open registries and
must never be enums. Do not add species or product_type here.
"""

import enum
from dataclasses import dataclass


class Severity(enum.StrEnum):
    BLOCK = "BLOCK"
    CORRECTION = "CORRECTION"
    WARN = "WARN"
    INFO = "INFO"


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    code: str
    severity: Severity
    message: str
    column_ref: str | None = None


# --- §5.7 ACTIVE-line rules -------------------------------------------------
# BLOCK — can corrupt AC; publication is refused.
NO_DNBP_FACTOR = "NO_DNBP_FACTOR"
MISSING_SELL_PRICE = "MISSING_SELL_PRICE"
UNKNOWN_SPECIES = "UNKNOWN_SPECIES"

# CORRECTION — defect in received A-V; does not block AC.
MISSING_LIVESTOCK_COST = "MISSING_LIVESTOCK_COST"
MISSING_AVG_WEIGHT = "MISSING_AVG_WEIGHT"
RECEIVED_VALUE_MISMATCH = "RECEIVED_VALUE_MISMATCH"
RECEIVED_BENCHMARK_ABSENT = "RECEIVED_BENCHMARK_ABSENT"

# WARN — supporting analysis degraded, or a commercial red flag.
NO_STANDARD_WEIGHT = "NO_STANDARD_WEIGHT"
DNBP_BELOW_COST = "DNBP_BELOW_COST"
NEGATIVE_MARGIN = "NEGATIVE_MARGIN"
DNBP_OUTLIER = "DNBP_OUTLIER"
LARGE_BENCHMARK_GAP = "LARGE_BENCHMARK_GAP"
HAND_SET_VALUE = "HAND_SET_VALUE"

# INFO
WEIGHT_OUTLIER = "WEIGHT_OUTLIER"

# --- §5.7.1 LOADED-line rules (P/L analysis only; never gate publication) --
LOADED_MISSING_LOADOUT_DATE = "LOADED_MISSING_LOADOUT_DATE"
LOADED_MISSING_ACTUAL_COST = "LOADED_MISSING_ACTUAL_COST"
LOADED_NEGATIVE_MARGIN = "LOADED_NEGATIVE_MARGIN"

# Codes that must never fire against a LOADED line — every rule whose sole
# purpose is protecting a price that will never be quoted (§5.3, §5.7).
ACTIVE_ONLY_CODES = frozenset(
    {
        NO_DNBP_FACTOR,
        MISSING_SELL_PRICE,
        UNKNOWN_SPECIES,
        MISSING_LIVESTOCK_COST,
        MISSING_AVG_WEIGHT,
        RECEIVED_VALUE_MISMATCH,
        RECEIVED_BENCHMARK_ABSENT,
        NO_STANDARD_WEIGHT,
        DNBP_BELOW_COST,
        NEGATIVE_MARGIN,
        DNBP_OUTLIER,
        LARGE_BENCHMARK_GAP,
        HAND_SET_VALUE,
        WEIGHT_OUTLIER,
    }
)
