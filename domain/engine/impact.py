"""Reference-data change impact preview (§6.5, §9.8 `POST
/reference-data/versions/{id}/impact`).

Not one of §5.3's X-AF columns — there is no normative "exposure" formula in
the PRD. This exists solely because §6.5 requires "impact preview listing
every active line's before/after DNBP and the aggregate AUD exposure change"
before a source-of-truth-input change (dnbp_factor, cif_buffer) may activate.

Pure and zero-IO, same discipline as the rest of domain/engine/: takes
already-fetched line data and two configs, calls `compute_bing_dnbp` twice
per line (old config, new config) rather than reimplementing the formula,
and returns plain dataclasses. Fetching which lines are currently active is
the caller's job (services/reference_data_service.py), not this module's.

Exposure basis: for a line whose species prices under both configs,
`(new_dnbp - old_dnbp) * qty_kg` — the AUD swing in maximum permissible
spend for that order's total kg (`qty_kg`, column F). Chosen because it is
the same price-times-quantity move §13.1's `Expected Livestock Cost = dnbp *
weight_requirement * expected_heads` makes, just at the order's total-kg
grain rather than per-head — the PRD does not define "exposure" numerically
anywhere, so this is the most literal reading available. A line that cannot
price under one or both configs (no factor, no sell price) contributes zero
to the aggregate and is reported with a null delta, never guessed.
"""

from dataclasses import dataclass
from decimal import Decimal

from domain.engine.config import EverhealthConfig
from domain.engine.dnbp import NoDnbpFactorError, compute_bing_dnbp


@dataclass(frozen=True, slots=True)
class ImpactLineInput:
    """The minimal subset of a line needed to preview a config change."""

    order_line_id: str
    contract_no: str | None
    species: str
    avg_price_aud: Decimal | None
    qty_kg: Decimal | None


@dataclass(frozen=True, slots=True)
class ImpactLineResult:
    order_line_id: str
    contract_no: str | None
    species: str
    old_dnbp: Decimal | None
    new_dnbp: Decimal | None
    delta_per_kg: Decimal | None  # new - old; None if either side can't price
    exposure_delta_aud: Decimal | None  # delta_per_kg * qty_kg


@dataclass(frozen=True, slots=True)
class ImpactPreview:
    lines: list[ImpactLineResult]
    aggregate_exposure_delta_aud: Decimal
    lines_affected: int  # lines whose dnbp actually changes (old != new)


def _price_or_none(avg_price_aud: Decimal | None, species: str, config: EverhealthConfig) -> Decimal | None:
    if avg_price_aud is None:
        return None
    try:
        return compute_bing_dnbp(avg_price_aud, species, config)
    except NoDnbpFactorError:
        return None


def compute_impact(
    lines: list[ImpactLineInput],
    *,
    old_config: EverhealthConfig,
    new_config: EverhealthConfig,
) -> ImpactPreview:
    results: list[ImpactLineResult] = []
    aggregate = Decimal(0)
    affected = 0

    for line in lines:
        old_dnbp = _price_or_none(line.avg_price_aud, line.species, old_config)
        new_dnbp = _price_or_none(line.avg_price_aud, line.species, new_config)

        delta_per_kg: Decimal | None = None
        exposure_delta: Decimal | None = None
        if old_dnbp is not None and new_dnbp is not None:
            delta_per_kg = new_dnbp - old_dnbp
            if line.qty_kg is not None:
                exposure_delta = delta_per_kg * line.qty_kg
                aggregate += exposure_delta
            if delta_per_kg != 0:
                affected += 1

        results.append(
            ImpactLineResult(
                order_line_id=line.order_line_id,
                contract_no=line.contract_no,
                species=line.species,
                old_dnbp=old_dnbp,
                new_dnbp=new_dnbp,
                delta_per_kg=delta_per_kg,
                exposure_delta_aud=exposure_delta,
            )
        )

    return ImpactPreview(lines=results, aggregate_exposure_delta_aud=aggregate, lines_affected=affected)
