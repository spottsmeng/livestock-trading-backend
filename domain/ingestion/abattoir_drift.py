"""Abattoir lookup-table drift (§7.2 point 11, deferred by Phase 2,
picked up here). Pure comparison, no DB — the caller (services/
ingestion_service.py) fetches the previous snapshot's stored tables and
persists the result as ReferenceDataDrift rows.

Only the three tables that actually vary submission to submission are
compared (§6.1-6.3, per domain/ingestion/lookup_sheet.py's own docstring):
pack_cost_by_product_type, offal_return_ph_by_species,
skin_return_ph_by_species. cif_buffer_per_kg and the fixed_cost_per_head_*
constants come from the reference-data seed, not the workbook, so they
never drift between submissions by construction.

This is a notice, never an input: nothing here can write to or influence
§6.4/§6.5, and the caller must never treat a detected drift as license to
"correct" the received values it was computed from (§5.2's rule against
correcting the abattoir's own numbers applies here too).
"""

from dataclasses import dataclass
from decimal import Decimal

from domain.engine.crosscheck import AbattoirReferenceTables

_COMPARED_TABLES: tuple[str, ...] = (
    "pack_cost_by_product_type",
    "offal_return_ph_by_species",
    "skin_return_ph_by_species",
)


@dataclass(frozen=True, slots=True)
class AbattoirTableDrift:
    table_key: str
    key1: str
    old_value: Decimal | None
    new_value: Decimal | None


def compare_abattoir_tables(
    previous: AbattoirReferenceTables | None, current: AbattoirReferenceTables
) -> list[AbattoirTableDrift]:
    if previous is None:
        return []  # nothing to diff against on a first-ever submission

    drift: list[AbattoirTableDrift] = []
    for table_key in _COMPARED_TABLES:
        previous_table: dict[str, Decimal] = getattr(previous, table_key)
        current_table: dict[str, Decimal] = getattr(current, table_key)
        keys = set(previous_table) | set(current_table)
        for key1 in sorted(keys):
            old_value = previous_table.get(key1)
            new_value = current_table.get(key1)
            if old_value != new_value:
                drift.append(
                    AbattoirTableDrift(table_key=table_key, key1=key1, old_value=old_value, new_value=new_value)
                )

    return drift
