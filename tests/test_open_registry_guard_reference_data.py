"""§6.9 non-negotiable #5 (Phase 3b): the new registry tables and their
write paths must not reintroduce a closed list for species/product_type —
extends tests/test_open_registry_guard.py's tripwire pattern to
models/reference_data.py and repositories/registries.py, which that scan's
_SCAN_DIRS already covers by directory but not by explicit assertion.
"""

from models.reference_data import ProductTypeRegistry, ReferenceDataEntry, SpeciesRegistry


def test_species_registry_code_is_a_plain_string_primary_key() -> None:
    column = SpeciesRegistry.__table__.columns["code"]
    assert column.primary_key is True
    assert str(column.type) == "VARCHAR"
    assert list(column.foreign_keys) == []


def test_product_type_registry_code_is_a_plain_string_primary_key() -> None:
    column = ProductTypeRegistry.__table__.columns["code"]
    assert column.primary_key is True
    assert str(column.type) == "VARCHAR"
    assert list(column.foreign_keys) == []


def test_reference_data_entry_key1_has_no_fk_to_either_registry() -> None:
    """key1 carries a species or product_type code for DNBP_FACTOR/
    STANDARD_WEIGHT entries (§8), but must stay a bare string — an FK here
    would silently reintroduce the closed-list behaviour §6.9 forbids for
    any species not yet in the registry at insert time."""
    column = ReferenceDataEntry.__table__.columns["key1"]
    assert list(column.foreign_keys) == []
    assert str(column.type) == "VARCHAR"


def test_order_lines_species_and_product_type_still_have_no_fk() -> None:
    """Phase 2 already established this; Phase 3b's registry tables must
    not change it — a new FK from order_lines to species_registry would
    reject an unrecognised value instead of storing it verbatim and
    flagging it (§6.9)."""
    from models.order_line import OrderLine

    for column_name in ("species", "product_type"):
        column = OrderLine.__table__.columns[column_name]
        assert list(column.foreign_keys) == [], f"order_lines.{column_name} must never gain a foreign key (§6.9)"
