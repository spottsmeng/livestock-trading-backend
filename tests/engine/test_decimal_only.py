"""Non-negotiable #8: all money and rate values use Decimal — never float —
anywhere in the calculation path (§5.5)."""

import ast
from dataclasses import fields
from decimal import Decimal
from pathlib import Path

from domain.engine.config import EverhealthConfig
from domain.engine.workings import Lifecycle, OrderLineInput, compute_order_workings

ENGINE_DIR = Path(__file__).resolve().parents[2] / "domain" / "engine"
_CALCULATION_FILES = ["config.py", "dnbp.py", "workings.py", "crosscheck.py"]


def test_no_float_literals_in_the_calculation_path() -> None:
    offenders: list[str] = []
    for filename in _CALCULATION_FILES:
        path = ENGINE_DIR / filename
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, float):
                offenders.append(f"{filename}:{node.lineno}: float literal {node.value!r}")
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "float":
                offenders.append(f"{filename}:{node.lineno}: float(...) call")
    assert offenders == [], f"float found in the calculation path (§5.5 requires Decimal only): {offenders}"


def test_config_values_are_decimal_instances() -> None:
    config = EverhealthConfig.from_values(
        cif_buffer_per_kg="0.30",
        dnbp_factor_by_species={"SHEEP": "0.83"},
        standard_weight_by_species={"SHEEP": "22"},
    )
    assert isinstance(config.cif_buffer_per_kg, Decimal)
    assert all(isinstance(v, Decimal) for v in config.dnbp_factor_by_species.values())
    assert all(isinstance(v, Decimal) for v in config.standard_weight_by_species.values())


def test_every_computed_workings_field_is_decimal_or_none() -> None:
    config = EverhealthConfig.from_values(
        cif_buffer_per_kg="0.30",
        dnbp_factor_by_species={"SHEEP": "0.83"},
        standard_weight_by_species={"SHEEP": "22"},
    )
    line = OrderLineInput(
        species="SHEEP",
        lifecycle=Lifecycle.ACTIVE,
        avg_price_aud=Decimal("10.144927536231885"),
        expected_livestock_cost_per_kg=Decimal("8.4"),
        pack_cost_ph=Decimal("4"),
        offal_return_ph=Decimal("8"),
        skin_return_ph=Decimal("10"),
        avg_weight_kg=Decimal("22"),
        dnbp_benchmark=Decimal("8.663109354413702"),
    )

    workings, _ = compute_order_workings(line, config)
    assert workings is not None

    for f in fields(workings):
        value = getattr(workings, f.name)
        if value is None or f.name == "supporting_analysis_complete":
            continue
        assert isinstance(value, Decimal), f"{f.name} is {type(value)!r}, expected Decimal"
