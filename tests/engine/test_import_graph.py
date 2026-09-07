"""Non-negotiable #5: crosscheck.py must have NO import path to dnbp.py —
verified by walking the actual AST import graph, not by inspection."""

import ast
from pathlib import Path

ENGINE_DIR = Path(__file__).resolve().parents[2] / "domain" / "engine"


def _module_imports(module_path: Path) -> set[str]:
    tree = ast.parse(module_path.read_text())
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    return imported


def _engine_module_names() -> dict[str, Path]:
    return {f"domain.engine.{p.stem}": p for p in ENGINE_DIR.glob("*.py") if p.stem != "__init__"}


def _reaches(module_path: Path, target_suffix: str, *, visited: set[Path] | None = None) -> bool:
    """True if `module_path` imports `target_suffix` (e.g. "dnbp"), directly
    or transitively, through any domain.engine.* module."""
    if visited is None:
        visited = set()
    if module_path in visited:
        return False
    visited.add(module_path)

    modules = _engine_module_names()
    for imported in _module_imports(module_path):
        if imported == f"domain.engine.{target_suffix}" or imported.endswith(f".{target_suffix}"):
            return True
        if imported in modules and _reaches(modules[imported], target_suffix, visited=visited):
            return True
    return False


def test_crosscheck_has_no_import_path_to_dnbp() -> None:
    crosscheck_path = ENGINE_DIR / "crosscheck.py"
    assert crosscheck_path.exists()
    assert not _reaches(crosscheck_path, "dnbp"), (
        "crosscheck.py must never import dnbp.py (§17.1) — validating the abattoir's arithmetic and "
        "computing Everhealth's price must stay separate concerns."
    )


def test_crosscheck_has_no_import_path_to_workings() -> None:
    crosscheck_path = ENGINE_DIR / "crosscheck.py"
    assert not _reaches(crosscheck_path, "workings")


def test_dnbp_module_imports_nothing_from_workings_or_crosscheck() -> None:
    """The dependency direction must run workings -> dnbp, never the reverse."""
    dnbp_path = ENGINE_DIR / "dnbp.py"
    imports = _module_imports(dnbp_path)
    assert not any("workings" in name or "crosscheck" in name for name in imports)
