"""§5.2 — recomputation of the abattoir's own A-V formulas, for validation
only. A mismatch raises a warning/correction; this module NEVER overwrites
the received value (Constraint 1) and NEVER computes anything the engine
depends on.

This module must have NO import path to dnbp.py (verified by
tests/engine/test_import_graph.py) and, more broadly, does not import
workings.py or config.py either. Validating the abattoir's arithmetic and
computing Everhealth's price are separate concerns that must never share
code (§17.1) — even though both formulas happen to reference a $0.30
figure, they are independent numbers (K's buffer is CIF-only; X's is
universal, §5.3) that could diverge if either changed, and a shared helper
is exactly how a change to a validation rule could silently move the
published price. The only thing this module shares with the rest of the
engine package is `issues.py`, which carries no calculation logic — plain
data types only.
"""

from dataclasses import dataclass, field
from decimal import Decimal

from domain.engine import issues as codes
from domain.engine.issues import Severity, ValidationIssue

RELATIVE_TOLERANCE = Decimal("0.000001")  # 1e-6, per §5.2


@dataclass(frozen=True, slots=True)
class AbattoirReferenceTables:
    """Abattoir-owned lookup tables (§6.1-6.3, §6.7), ingested verbatim from
    each submission's own lookup sheet. Cross-check only — never used to
    compute anything the engine or a publication depends on (§5.1)."""

    cif_buffer_per_kg: Decimal
    pack_cost_by_product_type: dict[str, Decimal] = field(default_factory=dict)
    offal_return_ph_by_species: dict[str, Decimal] = field(default_factory=dict)
    skin_return_ph_by_species: dict[str, Decimal] = field(default_factory=dict)
    fixed_cost_per_head_active: Decimal = Decimal(40)
    fixed_cost_per_head_loaded: Decimal = Decimal(34)


def expected_nrv_per_kg(avg_price_aud: Decimal, incoterm: str, tables: AbattoirReferenceTables) -> Decimal:
    """K ≈ (J == "CIF") ? G - 0.30 : G"""
    if incoterm == "CIF":
        return avg_price_aud - tables.cif_buffer_per_kg
    return avg_price_aud


def expected_pack_cost_ph(product_type: str, tables: AbattoirReferenceTables) -> Decimal | None:
    """M ≈ abattoir_pack_cost_table[I]"""
    return tables.pack_cost_by_product_type.get(product_type)


def expected_offal_return_ph(species: str, tables: AbattoirReferenceTables) -> Decimal | None:
    """N ≈ abattoir_offal_table[D]"""
    return tables.offal_return_ph_by_species.get(species)


def expected_skin_return_ph(species: str, tables: AbattoirReferenceTables) -> Decimal | None:
    """O ≈ abattoir_skin_table[D]. Deliberate divergences (e.g. GOAT's
    hand-set 0.5) are expected and reported via HAND_SET_VALUE elsewhere —
    this function only ever returns the table's own value, never "corrects"
    anything."""
    return tables.skin_return_ph_by_species.get(species)


def expected_mom_ph(
    *,
    nrv_per_kg: Decimal,
    livestock_cost_per_kg: Decimal,
    avg_weight_kg: Decimal,
    offal_return_ph: Decimal,
    skin_return_ph: Decimal,
    pack_cost_ph: Decimal,
) -> Decimal:
    """Q ≈ (P > 0) ? (K - L) * P + N + O - M : 0"""
    if avg_weight_kg <= 0:
        return Decimal(0)
    return (nrv_per_kg - livestock_cost_per_kg) * avg_weight_kg + offal_return_ph + skin_return_ph - pack_cost_ph


def expected_estimated_heads(qty_kg: Decimal, avg_weight_kg: Decimal) -> Decimal:
    """U ≈ (P > 0) ? F / P : 0"""
    if avg_weight_kg <= 0:
        return Decimal(0)
    return qty_kg / avg_weight_kg


def expected_total_livestock_cost(livestock_cost_per_kg: Decimal, qty_kg: Decimal) -> Decimal:
    """V ≈ L * F"""
    return livestock_cost_per_kg * qty_kg


def expected_dnbp_gayan(
    *,
    nrv_per_kg: Decimal,
    avg_weight_kg: Decimal,
    pack_cost_ph: Decimal,
    offal_return_ph: Decimal,
    skin_return_ph: Decimal,
    lifecycle: str,
    tables: AbattoirReferenceTables,
) -> Decimal:
    """T ≈ (P > 0) ? K - ((fixed_cost + M - O - N) / P) : 0
    where fixed_cost = 40 (ACTIVE) or 34 (LOADED)."""
    if avg_weight_kg <= 0:
        return Decimal(0)
    fixed_cost = tables.fixed_cost_per_head_active if lifecycle == "ACTIVE" else tables.fixed_cost_per_head_loaded
    return nrv_per_kg - ((fixed_cost + pack_cost_ph - skin_return_ph - offal_return_ph) / avg_weight_kg)


def check(column: str, received: Decimal | None, expected: Decimal | None) -> ValidationIssue | None:
    """Relative-tolerance comparison (§5.2, tolerance 1e-6). None on either
    side means "nothing to cross-check" — not a mismatch. Never overwrites
    `received`; only ever reports."""
    if received is None or expected is None:
        return None

    if expected == 0:
        mismatched = received != 0
    else:
        mismatched = abs((received - expected) / expected) > RELATIVE_TOLERANCE

    if not mismatched:
        return None

    return ValidationIssue(
        codes.RECEIVED_VALUE_MISMATCH,
        Severity.CORRECTION,
        f"Received {column} = {received}, expected {expected}",
        column_ref=column,
    )
