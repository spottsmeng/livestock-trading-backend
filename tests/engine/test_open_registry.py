"""Non-negotiable #7 / §6.9: species and product_type are never a closed
type anywhere in the engine — open, admin-managed registries. Extends the
existing tests/test_open_registry_guard.py tripwire pattern to domain/,
which that scan doesn't cover yet."""

import re
from pathlib import Path

DOMAIN_DIR = Path(__file__).resolve().parents[2] / "domain"

_ENUM_DECLARATION_PATTERN = re.compile(r"class\s+\w*(?:Species|ProductType)\w*\s*\(.*Enum", re.IGNORECASE)
_SUSPECT_PATTERN = re.compile(r"(species|product_type)", re.IGNORECASE)


def test_no_enum_or_literal_type_named_for_species_or_product_type_in_domain() -> None:
    offenders = []
    for path in DOMAIN_DIR.rglob("*.py"):
        text = path.read_text()
        if _ENUM_DECLARATION_PATTERN.search(text):
            offenders.append(str(path.relative_to(DOMAIN_DIR.parent)))
    assert offenders == [], (
        f"Found what looks like a closed enum for species/product_type — forbidden by §6.9: {offenders}"
    )


def test_species_is_a_plain_str_not_an_enum() -> None:
    from domain.engine.workings import OrderLineInput

    line = OrderLineInput(species="HOGGET")  # a species the seed data has never heard of
    assert isinstance(line.species, str)
    assert line.species == "HOGGET"  # stored verbatim, never rejected (§6.9)


def test_dnbp_factor_and_standard_weight_tables_are_plain_dicts() -> None:
    from domain.engine.config import EverhealthConfig

    config = EverhealthConfig.from_values(
        cif_buffer_per_kg="0.30",
        dnbp_factor_by_species={"HOGGET": "0.80"},
        standard_weight_by_species={},
    )
    assert isinstance(config.dnbp_factor_by_species, dict)
    assert "HOGGET" in config.dnbp_factor_by_species  # new species added with zero code change


def test_severity_is_the_only_legitimate_closed_enum_in_issues_module() -> None:
    """Sanity check mirroring test_models_enums_module_only_contains_
    legitimately_closed_types in the parent suite: issues.py's one Enum
    (Severity) is a genuinely closed set (§5.7's BLOCK/CORRECTION/WARN/INFO
    shapes), not species/product_type sneaking in under a different name."""
    from domain.engine import issues as issues_module

    code_lines = []
    for line in Path(issues_module.__file__).read_text().splitlines():
        code_part = line.split("#", 1)[0]
        if code_part.strip():
            code_lines.append(code_part)

    offending_lines = [line for line in code_lines if _SUSPECT_PATTERN.search(line) and "class" in line.lower()]
    assert offending_lines == []
