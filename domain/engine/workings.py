"""Supporting X-AF workings (PRD §5.3) built around the isolated `AC`.

`Y`, `Z`, `AA`, `AB`, `AD`, `AE`, `AF` are supporting analysis: computed in
independent expressions from `compute_bing_dnbp`'s result, never by reaching
into its internals, so a fault in one cannot corrupt the other (§5.3).

Only ACTIVE lines get a workings row and the §5.7 rule set (§5.3, §5.7). A
LOADED line runs the separate, much smaller §5.7.1 rule set and gets no
workings row at all — these are two separate functions below, not one path
branching on severity, so a LOADED line structurally cannot trip a
DNBP-protecting rule.

Every division here is guarded per §5.5: a missing/zero divisor yields None
for that derived field plus a validation issue — never a raised exception,
never NaN/Inf.
"""

import enum
from dataclasses import dataclass
from decimal import Decimal

from domain.engine import issues as codes
from domain.engine.config import EverhealthConfig
from domain.engine.dnbp import compute_bing_dnbp
from domain.engine.issues import Severity, ValidationIssue


class Lifecycle(enum.StrEnum):
    """Genuinely closed (PRD §6.9's closed_enums list) — unlike species and
    product_type, which must never be enums."""

    ACTIVE = "ACTIVE"
    LOADED = "LOADED"


@dataclass(frozen=True, slots=True)
class OrderLineInput:
    """The subset of received columns A-V (§5.1) the engine and its
    validation rules need. `species` is a plain str — an open registry
    (§6.9), never a closed type."""

    species: str
    lifecycle: Lifecycle = Lifecycle.ACTIVE
    contract_no: str | None = None
    avg_price_aud: Decimal | None = None
    incoterm: str | None = None
    expected_livestock_cost_per_kg: Decimal | None = None
    pack_cost_ph: Decimal | None = None
    offal_return_ph: Decimal | None = None
    skin_return_ph: Decimal | None = None
    avg_weight_kg: Decimal | None = None
    mom_ph: Decimal | None = None
    dnbp_benchmark: Decimal | None = None
    loadout_date: str | None = None


@dataclass(frozen=True, slots=True)
class OrderWorkings:
    """Columns X-AF (§5.3). Every numeric field is `Decimal | None` — None
    means "not computable from what was received", never a guessed 0."""

    adjusted_price_per_kg: Decimal | None  # X
    pack_cost_per_kg: Decimal | None  # Y
    offal_return_per_kg: Decimal | None  # Z
    skin_return_per_kg: Decimal | None  # AA
    profit_on_peter_costs: Decimal | None  # AB
    bing_dnbp: Decimal | None  # AC — SOURCE OF TRUTH
    bing_dnbp_factor_used: Decimal | None
    profit_on_bing_dnbp: Decimal | None  # AD
    diff_vs_benchmark: Decimal | None  # AE
    diff_vs_peter: Decimal | None  # AF
    supporting_analysis_complete: bool


def compute_order_workings(
    line: OrderLineInput, config: EverhealthConfig
) -> tuple[OrderWorkings | None, list[ValidationIssue]]:
    """Entry point. LOADED lines never reach the ACTIVE rule set or produce
    a workings row (§5.3) — the buyer already bought them."""
    if line.lifecycle is Lifecycle.LOADED:
        return None, _compute_loaded_line_issues(line)
    return _compute_active_line_workings(line, config)


def _compute_active_line_workings(
    line: OrderLineInput, config: EverhealthConfig
) -> tuple[OrderWorkings, list[ValidationIssue]]:
    found_issues: list[ValidationIssue] = []

    has_factor = line.species in config.dnbp_factor_by_species
    if not has_factor:
        found_issues.append(
            ValidationIssue(
                codes.NO_DNBP_FACTOR,
                Severity.BLOCK,
                f"No DNBP factor configured for {line.species} — cannot compute Do Not Buy Price",
            )
        )

    has_sell_price = line.avg_price_aud is not None and line.avg_price_aud > 0
    if not has_sell_price:
        found_issues.append(
            ValidationIssue(
                codes.MISSING_SELL_PRICE, Severity.BLOCK, "Average Price AUD missing — request correction from abattoir"
            )
        )

    if line.expected_livestock_cost_per_kg is None:
        found_issues.append(
            ValidationIssue(
                codes.MISSING_LIVESTOCK_COST,
                Severity.CORRECTION,
                "Livestock Cost/kg missing from submission — request correction",
            )
        )

    if line.avg_weight_kg is None or line.avg_weight_kg <= 0:
        found_issues.append(
            ValidationIssue(
                codes.MISSING_AVG_WEIGHT, Severity.CORRECTION, "Avg Weight missing from submission — request correction"
            )
        )

    standard_weight = config.standard_weight_by_species.get(line.species)
    if not standard_weight:
        found_issues.append(
            ValidationIssue(
                codes.NO_STANDARD_WEIGHT,
                Severity.WARN,
                f"No standard weight for {line.species} — Y/Z/AA unavailable; DNBP unaffected",
            )
        )

    # X — ALWAYS deducted, for CIF and FAS alike (§5.3 non-negotiable #3).
    # incoterm is deliberately never consulted here.
    adjusted_price_per_kg: Decimal | None = None
    if line.avg_price_aud is not None:
        adjusted_price_per_kg = line.avg_price_aud - config.cif_buffer_per_kg

    # Y / Z / AA — divide by the species standard weight, never avg_weight_kg
    # (§5.3 non-negotiable #4).
    pack_cost_per_kg = offal_return_per_kg = skin_return_per_kg = None
    if standard_weight:
        if line.pack_cost_ph is not None:
            pack_cost_per_kg = line.pack_cost_ph / standard_weight
        if line.offal_return_ph is not None:
            offal_return_per_kg = line.offal_return_ph / standard_weight
        if line.skin_return_ph is not None:
            skin_return_per_kg = line.skin_return_ph / standard_weight

    # AB — independent expression, not derived from AC.
    profit_on_peter_costs: Decimal | None = None
    if (
        adjusted_price_per_kg is not None
        and line.expected_livestock_cost_per_kg is not None
        and pack_cost_per_kg is not None
        and offal_return_per_kg is not None
        and skin_return_per_kg is not None
    ):
        profit_on_peter_costs = (
            adjusted_price_per_kg - line.expected_livestock_cost_per_kg - pack_cost_per_kg + offal_return_per_kg
        ) + skin_return_per_kg

    # AC — the isolated source of truth. Computed via compute_bing_dnbp only;
    # never inlined here, so there is exactly one place this formula lives.
    bing_dnbp: Decimal | None = None
    bing_dnbp_factor_used = config.dnbp_factor_by_species.get(line.species)
    if has_factor and has_sell_price:
        bing_dnbp = compute_bing_dnbp(line.avg_price_aud, line.species, config)  # type: ignore[arg-type]

    # AD — independent expression, not derived from AB.
    profit_on_bing_dnbp: Decimal | None = None
    if (
        adjusted_price_per_kg is not None
        and bing_dnbp is not None
        and pack_cost_per_kg is not None
        and offal_return_per_kg is not None
        and skin_return_per_kg is not None
    ):
        profit_on_bing_dnbp = (
            adjusted_price_per_kg - bing_dnbp - pack_cost_per_kg + offal_return_per_kg
        ) + skin_return_per_kg

    # AE
    diff_vs_benchmark: Decimal | None = None
    if bing_dnbp is not None and line.dnbp_benchmark is not None:
        diff_vs_benchmark = bing_dnbp - line.dnbp_benchmark

    # AF
    diff_vs_peter: Decimal | None = None
    if bing_dnbp is not None and line.expected_livestock_cost_per_kg is not None:
        diff_vs_peter = bing_dnbp - line.expected_livestock_cost_per_kg

    if profit_on_peter_costs is not None and profit_on_peter_costs < 0:
        found_issues.append(
            ValidationIssue(codes.NEGATIVE_MARGIN, Severity.WARN, "Negative margin at expected livestock cost")
        )

    if diff_vs_peter is not None and diff_vs_peter < 0:
        found_issues.append(
            ValidationIssue(
                codes.DNBP_BELOW_COST, Severity.WARN, "DNBP is below expected livestock cost — order likely loss-making"
            )
        )

    supporting_analysis_complete = profit_on_bing_dnbp is not None and diff_vs_peter is not None

    workings = OrderWorkings(
        adjusted_price_per_kg=adjusted_price_per_kg,
        pack_cost_per_kg=pack_cost_per_kg,
        offal_return_per_kg=offal_return_per_kg,
        skin_return_per_kg=skin_return_per_kg,
        profit_on_peter_costs=profit_on_peter_costs,
        bing_dnbp=bing_dnbp,
        bing_dnbp_factor_used=bing_dnbp_factor_used,
        profit_on_bing_dnbp=profit_on_bing_dnbp,
        diff_vs_benchmark=diff_vs_benchmark,
        diff_vs_peter=diff_vs_peter,
        supporting_analysis_complete=supporting_analysis_complete,
    )
    return workings, found_issues


def _compute_loaded_line_issues(line: OrderLineInput) -> list[ValidationIssue]:
    """§5.7.1 — P/L analysis only. Nothing here concerns pricing and nothing
    here blocks. None of the ACTIVE rule checks above are reachable from
    this function."""
    found_issues: list[ValidationIssue] = []

    if line.loadout_date is None:
        found_issues.append(
            ValidationIssue(
                codes.LOADED_MISSING_LOADOUT_DATE,
                Severity.WARN,
                "Loaded order has no loadout date — excluded from period P/L",
            )
        )

    if line.expected_livestock_cost_per_kg is None:
        found_issues.append(
            ValidationIssue(
                codes.LOADED_MISSING_ACTUAL_COST, Severity.WARN, "No livestock cost — excluded from realised margin"
            )
        )

    if line.mom_ph is not None and line.mom_ph < 0:
        found_issues.append(
            ValidationIssue(
                codes.LOADED_NEGATIVE_MARGIN, Severity.INFO, "Loaded order shows a negative margin over materials"
            )
        )

    return found_issues


def is_publishable(found_issues: list[ValidationIssue]) -> bool:
    """§5.7 publication gate: refused only while a BLOCK issue is present."""
    return not any(issue.severity is Severity.BLOCK for issue in found_issues)
