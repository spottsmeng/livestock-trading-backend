import re
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
_SCAN_DIRS = ["core", "models", "schemas", "api", "repositories", "services", "scripts"]

# §6.9 / non-negotiable #10: species and product_type must never become a
# closed type anywhere in this codebase, even before any phase actually
# defines an order_lines table. This regex is deliberately loose — it's a
# tripwire for whoever adds species/product_type later, not a precise
# parser. A false positive here is cheap to fix; a real violation slipping
# through is a §6.9 spec violation.
_SUSPECT_PATTERN = re.compile(r"(species|product_type)", re.IGNORECASE)
_ENUM_DECLARATION_PATTERN = re.compile(r"class\s+\w*(?:Species|ProductType)\w*\s*\(.*Enum", re.IGNORECASE)


def test_no_enum_or_literal_type_named_for_species_or_product_type():
    offenders = []
    for dir_name in _SCAN_DIRS:
        for path in (BACKEND_ROOT / dir_name).rglob("*.py"):
            text = path.read_text()
            if _ENUM_DECLARATION_PATTERN.search(text):
                offenders.append(str(path.relative_to(BACKEND_ROOT)))
    assert offenders == [], (
        f"Found what looks like a closed enum for species/product_type — forbidden by §6.9, "
        f"these must be open, admin-managed registries: {offenders}"
    )


def test_models_enums_module_only_contains_legitimately_closed_types():
    """models/enums.py is where closed enums are allowed to live (role,
    invite_status, org_kind). Make sure species/product_type never sneak
    in there specifically — the single most likely place a future
    contributor would add them out of habit.

    Checks CODE only, not comments — the module's own explanatory comment
    legitimately says "species" to explain why it isn't there, which would
    otherwise make this test trip on itself."""
    from models import enums as enums_module

    code_lines = []
    for line in Path(enums_module.__file__).read_text().splitlines():
        code_part = line.split("#", 1)[0]
        if code_part.strip():
            code_lines.append(code_part)

    offending_lines = [line for line in code_lines if _SUSPECT_PATTERN.search(line)]
    assert offending_lines == [], (
        f"models/enums.py must never define species or product_type — they are open registries (§6.9), "
        f"not enums, even when it would be convenient: {offending_lines}"
    )
