"""Non-negotiable #2: compute_bing_dnbp depends on exactly avg_price_aud,
species, cif_buffer and dnbp_factor[species] — nothing else. No dependency
on livestock cost, weight, pack cost, offal/skin return, incoterm, or
standard weight."""

from decimal import Decimal

from domain.engine.config import EverhealthConfig
from domain.engine.dnbp import compute_bing_dnbp
from domain.engine.workings import Lifecycle, OrderLineInput, compute_order_workings


def _config(**overrides) -> EverhealthConfig:
    defaults = dict(
        cif_buffer_per_kg="0.30",
        dnbp_factor_by_species={"SHEEP": "0.83"},
        standard_weight_by_species={"SHEEP": "22"},
    )
    defaults.update(overrides)
    return EverhealthConfig.from_values(**defaults)


def test_compute_bing_dnbp_ignores_standard_weight_changes() -> None:
    price = Decimal("10.144927536231885")
    result_a = compute_bing_dnbp(price, "SHEEP", _config(standard_weight_by_species={"SHEEP": "22"}))
    result_b = compute_bing_dnbp(price, "SHEEP", _config(standard_weight_by_species={"SHEEP": "999"}))
    result_c = compute_bing_dnbp(price, "SHEEP", _config(standard_weight_by_species={}))

    assert result_a == result_b == result_c


def test_compute_bing_dnbp_signature_takes_only_three_inputs() -> None:
    import inspect

    params = list(inspect.signature(compute_bing_dnbp).parameters)
    assert params == ["avg_price_aud", "species", "config"]


def _base_line(**overrides) -> OrderLineInput:
    defaults = dict(
        species="SHEEP",
        lifecycle=Lifecycle.ACTIVE,
        avg_price_aud=Decimal("10.144927536231885"),
        incoterm="CIF",
        expected_livestock_cost_per_kg=Decimal("8.4"),
        pack_cost_ph=Decimal("4"),
        offal_return_ph=Decimal("8"),
        skin_return_ph=Decimal("10"),
        avg_weight_kg=Decimal("22"),
        dnbp_benchmark=Decimal("8.663109354413702"),
    )
    defaults.update(overrides)
    return OrderLineInput(**defaults)


def test_bing_dnbp_unaffected_by_everything_except_price_and_species() -> None:
    config = _config()
    baseline, _ = compute_order_workings(_base_line(), config)

    variants = [
        _base_line(expected_livestock_cost_per_kg=Decimal("1")),
        _base_line(expected_livestock_cost_per_kg=None),
        _base_line(avg_weight_kg=Decimal("999")),
        _base_line(avg_weight_kg=None),
        _base_line(pack_cost_ph=Decimal("999")),
        _base_line(pack_cost_ph=None),
        _base_line(offal_return_ph=Decimal("999")),
        _base_line(offal_return_ph=None),
        _base_line(skin_return_ph=Decimal("999")),
        _base_line(skin_return_ph=None),
        _base_line(incoterm="FAS"),
        _base_line(incoterm=None),
        _base_line(dnbp_benchmark=Decimal("999")),
        _base_line(dnbp_benchmark=None),
    ]

    for variant in variants:
        workings, _ = compute_order_workings(variant, config)
        assert workings.bing_dnbp == baseline.bing_dnbp, f"AC changed for variant: {variant}"


def test_bing_dnbp_unaffected_by_standard_weight_removed_from_config() -> None:
    line = _base_line()
    with_weight, _ = compute_order_workings(line, _config(standard_weight_by_species={"SHEEP": "22"}))
    without_weight, _ = compute_order_workings(line, _config(standard_weight_by_species={}))

    assert with_weight.bing_dnbp == without_weight.bing_dnbp
    assert with_weight.bing_dnbp is not None
