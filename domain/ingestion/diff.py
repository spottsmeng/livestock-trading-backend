"""Structural diff between two parsed snapshots (§7.3). The submitted file
is cumulative, so the real question for the uploader is never "what's in
this file" — it's "what changed since yesterday". Lines are matched across
snapshots by `ParsedOrderLine.identity_key()` (contract_no + species +
product_type + incoterm) since the source data has no stable row id and
`contract_no` alone is not unique (§5.1).
"""

from dataclasses import dataclass, field
from decimal import Decimal

from domain.engine.workings import Lifecycle
from domain.ingestion.workbook import ParsedOrderLine

# Compared fields only — metadata like line_no/source_row/value_sources is
# parsing provenance, not a business change worth surfacing in a diff.
_COMPARED_FIELDS = (
    "customer_name",
    "loadout_date",
    "qty_kg",
    "avg_price_aud",
    "amount_aud",
    "incoterm",
    "nrv_per_kg",
    "expected_livestock_cost_per_kg",
    "pack_cost_ph",
    "offal_return_ph",
    "skin_return_ph",
    "avg_weight_kg",
    "mom_ph",
    "deposit_received",
    "dnbp_benchmark",
    "estimated_heads",
    "total_livestock_cost",
)


@dataclass(frozen=True, slots=True)
class FieldChange:
    field: str
    previous: object
    current: object


@dataclass(frozen=True, slots=True)
class LineChange:
    identity_key: tuple
    changes: list[FieldChange]


@dataclass(frozen=True, slots=True)
class SnapshotDiff:
    new_lines: list[ParsedOrderLine] = field(default_factory=list)
    changed_lines: list[LineChange] = field(default_factory=list)
    moved_to_loaded: list[ParsedOrderLine] = field(default_factory=list)
    removed_lines: list[tuple] = field(default_factory=list)  # identity keys present before, absent now

    def summary(self) -> dict:
        return {
            "new_count": len(self.new_lines),
            "changed_count": len(self.changed_lines),
            "moved_to_loaded_count": len(self.moved_to_loaded),
            "removed_count": len(self.removed_lines),
        }


def _values_differ(a: object, b: object) -> bool:
    if isinstance(a, Decimal) or isinstance(b, Decimal):
        try:
            return Decimal(a) != Decimal(b) if a is not None and b is not None else a != b
        except Exception:
            return a != b
    return a != b


def compare(previous: list[ParsedOrderLine] | None, current: list[ParsedOrderLine]) -> SnapshotDiff:
    if not previous:
        return SnapshotDiff(new_lines=list(current))

    previous_by_key = {line.identity_key(): line for line in previous}
    current_by_key = {line.identity_key(): line for line in current}

    new_lines: list[ParsedOrderLine] = []
    changed_lines: list[LineChange] = []
    moved_to_loaded: list[ParsedOrderLine] = []

    for key, current_line in current_by_key.items():
        previous_line = previous_by_key.get(key)
        if previous_line is None:
            new_lines.append(current_line)
            continue
        if previous_line.lifecycle is Lifecycle.ACTIVE and current_line.lifecycle is Lifecycle.LOADED:
            moved_to_loaded.append(current_line)
        changes = [
            FieldChange(field=name, previous=getattr(previous_line, name), current=getattr(current_line, name))
            for name in _COMPARED_FIELDS
            if _values_differ(getattr(previous_line, name), getattr(current_line, name))
        ]
        if changes:
            changed_lines.append(LineChange(identity_key=key, changes=changes))

    removed_lines = [key for key in previous_by_key if key not in current_by_key]

    return SnapshotDiff(
        new_lines=new_lines,
        changed_lines=changed_lines,
        moved_to_loaded=moved_to_loaded,
        removed_lines=removed_lines,
    )
