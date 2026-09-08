"""domain/engine/impact.py — the §6.5 impact-preview computation. Pure,
zero-IO: exercises compute_impact directly against hand-built configs and
line inputs, no DB, no service layer."""

from decimal import Decimal

from domain.engine.config import EverhealthConfig
from domain.engine.impact import ImpactLineInput, compute_impact


def _config(**overrides) -> EverhealthConfig:
    defaults = dict(
        cif_buffer_per_kg="0.30",
        dnbp_factor_by_species={"SHEEP": "0.83", "GOAT": "0.77"},
        standard_weight_by_species={"SHEEP": "22", "GOAT": "14"},
    )
    defaults.update(overrides)
    return EverhealthConfig.from_values(**defaults)


def _line(**overrides) -> ImpactLineInput:
    defaults = dict(
        order_line_id="line-1",
        contract_no="CED18650",
        species="SHEEP",
        avg_price_aud=Decimal("10.144927536231885"),
        qty_kg=Decimal("25000"),
    )
    defaults.update(overrides)
    return ImpactLineInput(**defaults)


def test_no_change_yields_zero_aggregate_and_zero_affected() -> None:
    config = _config()
    preview = compute_impact([_line()], old_config=config, new_config=config)

    assert preview.aggregate_exposure_delta_aud == 0
    assert preview.lines_affected == 0
    assert preview.lines[0].old_dnbp == preview.lines[0].new_dnbp
    assert preview.lines[0].delta_per_kg == 0


def test_factor_increase_raises_dnbp_and_exposure_matches_qty_times_delta() -> None:
    old_config = _config(dnbp_factor_by_species={"SHEEP": "0.83", "GOAT": "0.77"})
    new_config = _config(dnbp_factor_by_species={"SHEEP": "0.90", "GOAT": "0.77"})

    line = _line()
    preview = compute_impact([line], old_config=old_config, new_config=new_config)

    result = preview.lines[0]
    x = line.avg_price_aud - old_config.cif_buffer_per_kg
    expected_old = x * Decimal("0.83")
    expected_new = x * Decimal("0.90")
    expected_delta = expected_new - expected_old

    assert result.old_dnbp == expected_old
    assert result.new_dnbp == expected_new
    assert result.delta_per_kg == expected_delta
    assert result.exposure_delta_aud == expected_delta * line.qty_kg
    assert preview.aggregate_exposure_delta_aud == expected_delta * line.qty_kg
    assert preview.lines_affected == 1


def test_cif_buffer_change_affects_every_species_uniformly() -> None:
    old_config = _config(cif_buffer_per_kg="0.30")
    new_config = _config(cif_buffer_per_kg="0.50")

    lines = [_line(order_line_id="a", species="SHEEP"), _line(order_line_id="b", species="GOAT")]
    preview = compute_impact(lines, old_config=old_config, new_config=new_config)

    assert preview.lines_affected == 2
    for result in preview.lines:
        assert result.delta_per_kg is not None
        assert result.delta_per_kg < 0  # a bigger buffer deduction lowers AC


def test_line_with_no_factor_in_either_config_contributes_nothing() -> None:
    config = _config()  # no VEAL factor configured
    preview = compute_impact([_line(species="VEAL")], old_config=config, new_config=config)

    result = preview.lines[0]
    assert result.old_dnbp is None
    assert result.new_dnbp is None
    assert result.delta_per_kg is None
    assert result.exposure_delta_aud is None
    assert preview.aggregate_exposure_delta_aud == 0
    assert preview.lines_affected == 0


def test_newly_added_factor_prices_a_previously_unpriceable_species() -> None:
    old_config = _config()  # no VEAL factor
    new_config = _config(dnbp_factor_by_species={"SHEEP": "0.83", "GOAT": "0.77", "VEAL": "0.50"})

    preview = compute_impact([_line(species="VEAL")], old_config=old_config, new_config=new_config)

    result = preview.lines[0]
    assert result.old_dnbp is None
    assert result.new_dnbp is not None
    # Can't compute a per-kg delta when one side is unpriceable — never guess.
    assert result.delta_per_kg is None
    assert result.exposure_delta_aud is None


def test_null_qty_kg_omits_line_from_aggregate_but_still_reports_delta() -> None:
    old_config = _config(dnbp_factor_by_species={"SHEEP": "0.83"})
    new_config = _config(dnbp_factor_by_species={"SHEEP": "0.90"})

    preview = compute_impact([_line(qty_kg=None)], old_config=old_config, new_config=new_config)

    result = preview.lines[0]
    assert result.delta_per_kg is not None
    assert result.exposure_delta_aud is None
    assert preview.aggregate_exposure_delta_aud == 0


def test_aggregate_sums_across_multiple_lines() -> None:
    old_config = _config()
    new_config = _config(dnbp_factor_by_species={"SHEEP": "0.90", "GOAT": "0.80"})

    lines = [
        _line(order_line_id="a", species="SHEEP", qty_kg=Decimal("1000")),
        _line(order_line_id="b", species="GOAT", qty_kg=Decimal("2000")),
    ]
    preview = compute_impact(lines, old_config=old_config, new_config=new_config)

    expected = sum((r.exposure_delta_aud for r in preview.lines), Decimal(0))
    assert preview.aggregate_exposure_delta_aud == expected
    assert preview.lines_affected == 2
