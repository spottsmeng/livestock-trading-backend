from decimal import Decimal

from domain.engine.crosscheck import AbattoirReferenceTables
from domain.ingestion.abattoir_drift import compare_abattoir_tables


def _tables(**overrides) -> AbattoirReferenceTables:
    defaults = dict(
        cif_buffer_per_kg=Decimal("0.30"),
        pack_cost_by_product_type={"CCS": Decimal("2"), "6 WAY": Decimal("4")},
        offal_return_ph_by_species={"SHEEP": Decimal("8"), "GOAT": Decimal("6")},
        skin_return_ph_by_species={"SHEEP": Decimal("10"), "GOAT": Decimal("0")},
    )
    defaults.update(overrides)
    return AbattoirReferenceTables(**defaults)


def test_no_previous_snapshot_yields_no_drift() -> None:
    assert compare_abattoir_tables(None, _tables()) == []


def test_identical_tables_yield_no_drift() -> None:
    assert compare_abattoir_tables(_tables(), _tables()) == []


def test_changed_value_is_reported() -> None:
    previous = _tables(skin_return_ph_by_species={"SHEEP": Decimal("10"), "GOAT": Decimal("0")})
    current = _tables(skin_return_ph_by_species={"SHEEP": Decimal("10"), "GOAT": Decimal("0.5")})

    drift = compare_abattoir_tables(previous, current)

    assert len(drift) == 1
    assert drift[0].table_key == "skin_return_ph_by_species"
    assert drift[0].key1 == "GOAT"
    assert drift[0].old_value == Decimal("0")
    assert drift[0].new_value == Decimal("0.5")


def test_new_key_reported_with_null_old_value() -> None:
    previous = _tables(offal_return_ph_by_species={"SHEEP": Decimal("8")})
    current = _tables(offal_return_ph_by_species={"SHEEP": Decimal("8"), "VEAL": Decimal("11")})

    drift = compare_abattoir_tables(previous, current)

    assert len(drift) == 1
    assert drift[0].key1 == "VEAL"
    assert drift[0].old_value is None
    assert drift[0].new_value == Decimal("11")


def test_cif_buffer_and_fixed_costs_never_compared() -> None:
    previous = _tables(cif_buffer_per_kg=Decimal("0.30"), fixed_cost_per_head_active=Decimal("40"))
    current = _tables(cif_buffer_per_kg=Decimal("999"), fixed_cost_per_head_active=Decimal("999"))

    assert compare_abattoir_tables(previous, current) == []
