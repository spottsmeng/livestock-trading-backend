"""Validation issue types for the DNBP engine (PRD §5.7, §5.7.1).

Severity is a genuinely closed, small set of shapes the code itself branches
on (BLOCK gates publication, CORRECTION/WARN/INFO do not) — this is NOT the
same category as species/product_type (§6.9), which are open registries and
must never be enums. Do not add species or product_type here.
"""

import enum
from dataclasses import dataclass
from decimal import Decimal


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

# DNBP_OUTLIER threshold (§5.7): "> 15% off recent average". Not
# Everhealth-config-editable like the DNBP factor table — it's a fixed
# statistical tripwire on the analysis, not a money-moving lever, so it
# lives here as a plain constant rather than in EverhealthConfig.
OUTLIER_THRESHOLD_PCT = Decimal("15")


def check_dnbp_outlier(bing_dnbp: Decimal | None, recent_species_average: Decimal | None) -> ValidationIssue | None:
    """§5.7 `DNBP_OUTLIER` (WARN) — "DNBP deviates > 15% from 30-day
    species mean". Deliberately NOT part of compute_order_workings/
    _compute_active_line_workings: that function is pure and has no
    database access, and a 30-day trailing average can only ever come from
    a DB query over past dnbp_publication_lines rows (Phase 3). The caller
    (services/calculate_service.py) fetches that average and passes it in
    here; this function stays a pure comparison, same discipline as the
    rest of this module.

    Returns None (no issue) whenever there's nothing to compare against —
    e.g. no publication history yet for this species — never a guessed or
    zero-defaulted average."""
    if bing_dnbp is None or recent_species_average is None or recent_species_average == 0:
        return None

    deviation_pct = abs(bing_dnbp - recent_species_average) / recent_species_average * 100
    if deviation_pct <= OUTLIER_THRESHOLD_PCT:
        return None

    return ValidationIssue(
        DNBP_OUTLIER,
        Severity.WARN,
        f"DNBP is {deviation_pct.quantize(Decimal('1'))}% off recent average — please confirm",
    )
