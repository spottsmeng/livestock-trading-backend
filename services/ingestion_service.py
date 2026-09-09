"""Upload -> parse preview -> diff -> commit (§7.3, §9.2).

A parsed-but-uncommitted upload lives only in Redis, keyed by a preview_id,
for `settings.upload_preview_ttl_seconds` — nothing touches Postgres until
POST /snapshots confirms it. This is what makes "drop a file, see a
preview, confirm" cheap to get wrong and retry: an abandoned upload leaves
no trace.
"""

import base64
import hashlib
import json
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.errors import PreviewExpired
from core.object_storage import ObjectStorage
from core.reference_data import get_abattoir_fixed_costs, get_active_everhealth_config
from domain.engine.crosscheck import AbattoirReferenceTables
from domain.engine.workings import Lifecycle
from domain.ingestion import diff as diff_module
from domain.ingestion.abattoir_drift import compare_abattoir_tables
from domain.ingestion.layout import DetectedLayout, SectionLocation
from domain.ingestion.types import BenchmarkMethod, ValueSource
from domain.ingestion.workbook import ParsedOrderLine, ParsedSnapshot, parse
from models.enums import Incoterm, SnapshotStatus
from models.order_line import OrderLine
from models.order_snapshot import OrderSnapshot
from models.reference_data import ReferenceDataDrift
from repositories import order_lines as order_lines_repo
from repositories import order_snapshots as order_snapshots_repo
from repositories import reference_data_drift as reference_data_drift_repo
from repositories import users as users_repo
from services import audit_service

_PREVIEW_KEY_PREFIX = "snapshot-preview:"


# --- Decimal-safe (de)serialisation for the Redis preview cache ------------


def _decimal_to_str(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


def _str_to_decimal(value: str | None) -> Decimal | None:
    return Decimal(value) if value is not None else None


def _serialize_abattoir_tables(tables: AbattoirReferenceTables) -> dict:
    """Shape persisted verbatim into order_snapshots.abattoir_reference_tables."""
    return {
        "cif_buffer_per_kg": str(tables.cif_buffer_per_kg),
        "pack_cost_by_product_type": {k: str(v) for k, v in tables.pack_cost_by_product_type.items()},
        "offal_return_ph_by_species": {k: str(v) for k, v in tables.offal_return_ph_by_species.items()},
        "skin_return_ph_by_species": {k: str(v) for k, v in tables.skin_return_ph_by_species.items()},
        "fixed_cost_per_head_active": str(tables.fixed_cost_per_head_active),
        "fixed_cost_per_head_loaded": str(tables.fixed_cost_per_head_loaded),
    }


def deserialize_abattoir_tables(data: dict) -> AbattoirReferenceTables:
    return AbattoirReferenceTables(
        cif_buffer_per_kg=Decimal(data["cif_buffer_per_kg"]),
        pack_cost_by_product_type={k: Decimal(v) for k, v in data["pack_cost_by_product_type"].items()},
        offal_return_ph_by_species={k: Decimal(v) for k, v in data["offal_return_ph_by_species"].items()},
        skin_return_ph_by_species={k: Decimal(v) for k, v in data["skin_return_ph_by_species"].items()},
        fixed_cost_per_head_active=Decimal(data["fixed_cost_per_head_active"]),
        fixed_cost_per_head_loaded=Decimal(data["fixed_cost_per_head_loaded"]),
    )


def _serialize_line(line: ParsedOrderLine) -> dict:
    return {
        "line_no": line.line_no,
        "lifecycle": line.lifecycle.value,
        "source_sheet": line.source_sheet,
        "source_row": line.source_row,
        "contract_no": line.contract_no,
        "customer_name": line.customer_name,
        "species": line.species,
        "loadout_date": line.loadout_date.isoformat() if line.loadout_date else None,
        "qty_kg": _decimal_to_str(line.qty_kg),
        "avg_price_aud": _decimal_to_str(line.avg_price_aud),
        "amount_aud": _decimal_to_str(line.amount_aud),
        "product_type": line.product_type,
        "incoterm": line.incoterm,
        "nrv_per_kg": _decimal_to_str(line.nrv_per_kg),
        "expected_livestock_cost_per_kg": _decimal_to_str(line.expected_livestock_cost_per_kg),
        "pack_cost_ph": _decimal_to_str(line.pack_cost_ph),
        "offal_return_ph": _decimal_to_str(line.offal_return_ph),
        "skin_return_ph": _decimal_to_str(line.skin_return_ph),
        "avg_weight_kg": _decimal_to_str(line.avg_weight_kg),
        "mom_ph": _decimal_to_str(line.mom_ph),
        "deposit_received": _decimal_to_str(line.deposit_received),
        "comments": line.comments,
        "dnbp_benchmark": _decimal_to_str(line.dnbp_benchmark),
        "benchmark_method": line.benchmark_method.value if line.benchmark_method else None,
        "estimated_heads": _decimal_to_str(line.estimated_heads),
        "total_livestock_cost": _decimal_to_str(line.total_livestock_cost),
        "value_sources": {k: v.value for k, v in line.value_sources.items()},
    }


def _deserialize_line(data: dict) -> ParsedOrderLine:
    return ParsedOrderLine(
        line_no=data["line_no"],
        lifecycle=Lifecycle(data["lifecycle"]),
        source_sheet=data["source_sheet"],
        source_row=data["source_row"],
        contract_no=data["contract_no"],
        customer_name=data["customer_name"],
        species=data["species"],
        loadout_date=date.fromisoformat(data["loadout_date"]) if data["loadout_date"] else None,
        qty_kg=_str_to_decimal(data["qty_kg"]),
        avg_price_aud=_str_to_decimal(data["avg_price_aud"]),
        amount_aud=_str_to_decimal(data["amount_aud"]),
        product_type=data["product_type"],
        incoterm=data["incoterm"],
        nrv_per_kg=_str_to_decimal(data["nrv_per_kg"]),
        expected_livestock_cost_per_kg=_str_to_decimal(data["expected_livestock_cost_per_kg"]),
        pack_cost_ph=_str_to_decimal(data["pack_cost_ph"]),
        offal_return_ph=_str_to_decimal(data["offal_return_ph"]),
        skin_return_ph=_str_to_decimal(data["skin_return_ph"]),
        avg_weight_kg=_str_to_decimal(data["avg_weight_kg"]),
        mom_ph=_str_to_decimal(data["mom_ph"]),
        deposit_received=_str_to_decimal(data["deposit_received"]),
        comments=data["comments"],
        dnbp_benchmark=_str_to_decimal(data["dnbp_benchmark"]),
        benchmark_method=BenchmarkMethod(data["benchmark_method"]) if data["benchmark_method"] else None,
        estimated_heads=_str_to_decimal(data["estimated_heads"]),
        total_livestock_cost=_str_to_decimal(data["total_livestock_cost"]),
        value_sources={k: ValueSource(v) for k, v in data["value_sources"].items()},
    )


def _serialize_layout(layout: DetectedLayout) -> dict:
    def _section(section: SectionLocation | None) -> dict | None:
        if section is None:
            return None
        return {
            "sheet_name": section.sheet_name,
            "header_row": section.header_row,
            "data_row_start": section.data_row_start,
            "data_row_end": section.data_row_end,
        }

    return {
        "strategy": layout.strategy,
        "loaded_strategy": layout.loaded_strategy,
        "active": _section(layout.active),
        "loaded": _section(layout.loaded),
        "candidates_considered": layout.candidates_considered,
    }


def _deserialize_layout(data: dict) -> DetectedLayout:
    def _section(section: dict | None) -> SectionLocation | None:
        if section is None:
            return None
        return SectionLocation(**section)

    return DetectedLayout(
        strategy=data["strategy"],
        loaded_strategy=data["loaded_strategy"],
        active=_section(data["active"]),
        loaded=_section(data["loaded"]),
        candidates_considered=data["candidates_considered"],
    )


def _serialize_parsed_snapshot(parsed: ParsedSnapshot) -> dict:
    return {
        "source_filename": parsed.source_filename,
        "parser_version": parsed.parser_version,
        "detected_layout": _serialize_layout(parsed.detected_layout),
        "abattoir_tables": _serialize_abattoir_tables(parsed.abattoir_tables),
        "lines": [_serialize_line(line) for line in parsed.lines],
    }


def _deserialize_parsed_snapshot(data: dict) -> ParsedSnapshot:
    return ParsedSnapshot(
        source_filename=data["source_filename"],
        parser_version=data["parser_version"],
        detected_layout=_deserialize_layout(data["detected_layout"]),
        abattoir_tables=deserialize_abattoir_tables(data["abattoir_tables"]),
        lines=[_deserialize_line(line) for line in data["lines"]],
    )


def parsed_line_from_db(order_line: OrderLine) -> ParsedOrderLine:
    """Reconstructs a diff-comparable ParsedOrderLine from a committed DB
    row — used only to diff a new upload against the previous snapshot
    (§7.3); parsing metadata (source_sheet/source_row/value_sources) is
    irrelevant to that comparison."""
    return ParsedOrderLine(
        line_no=order_line.line_no,
        lifecycle=order_line.lifecycle,
        source_sheet="",
        source_row=0,
        contract_no=order_line.contract_no,
        customer_name=order_line.customer_name,
        species=order_line.species,
        loadout_date=order_line.loadout_date,
        qty_kg=order_line.qty_kg,
        avg_price_aud=order_line.avg_price_aud,
        amount_aud=order_line.amount_aud,
        product_type=order_line.product_type,
        incoterm=order_line.incoterm.value if order_line.incoterm else None,
        nrv_per_kg=order_line.nrv_per_kg,
        expected_livestock_cost_per_kg=order_line.expected_livestock_cost_per_kg,
        pack_cost_ph=order_line.pack_cost_ph,
        offal_return_ph=order_line.offal_return_ph,
        skin_return_ph=order_line.skin_return_ph,
        avg_weight_kg=order_line.avg_weight_kg,
        mom_ph=order_line.mom_ph,
        deposit_received=order_line.deposit_received,
        comments=order_line.comments,
        dnbp_benchmark=order_line.dnbp_benchmark,
        benchmark_method=order_line.benchmark_method,
        estimated_heads=order_line.estimated_heads,
        total_livestock_cost=order_line.total_livestock_cost,
    )


def _order_line_model(snapshot_id: uuid.UUID, line: ParsedOrderLine) -> OrderLine:
    incoterm = None
    if line.incoterm:
        try:
            incoterm = Incoterm(line.incoterm)
        except ValueError:
            incoterm = None  # genuinely closed per PRD; an unrecognised value is dropped, not stored as garbage
    return OrderLine(
        snapshot_id=snapshot_id,
        line_no=line.line_no,
        lifecycle=line.lifecycle,
        contract_no=line.contract_no,
        customer_name=line.customer_name,
        species=line.species,
        loadout_date=line.loadout_date,
        qty_kg=line.qty_kg,
        avg_price_aud=line.avg_price_aud,
        amount_aud=line.amount_aud,
        product_type=line.product_type,
        incoterm=incoterm,
        nrv_per_kg=line.nrv_per_kg,
        expected_livestock_cost_per_kg=line.expected_livestock_cost_per_kg,
        pack_cost_ph=line.pack_cost_ph,
        offal_return_ph=line.offal_return_ph,
        skin_return_ph=line.skin_return_ph,
        avg_weight_kg=line.avg_weight_kg,
        mom_ph=line.mom_ph,
        deposit_received=line.deposit_received,
        comments=line.comments,
        dnbp_benchmark=line.dnbp_benchmark,
        benchmark_method=line.benchmark_method,
        estimated_heads=line.estimated_heads,
        total_livestock_cost=line.total_livestock_cost,
        value_sources={k: v.value for k, v in line.value_sources.items()},
    )


def diff_to_jsonable(snapshot_diff: diff_module.SnapshotDiff) -> dict:
    def _line(line: ParsedOrderLine) -> dict:
        return {"contract_no": line.contract_no, "species": line.species, "lifecycle": line.lifecycle.value}

    def _field_change(change: diff_module.FieldChange) -> dict:
        def _value(v: object) -> object:
            if isinstance(v, Decimal):
                return str(v)
            if isinstance(v, (date, datetime)):
                return v.isoformat()
            return v

        return {"field": change.field, "previous": _value(change.previous), "current": _value(change.current)}

    return {
        "new_lines": [_line(line) for line in snapshot_diff.new_lines],
        "changed_lines": [
            {"identity_key": list(c.identity_key), "changes": [_field_change(fc) for fc in c.changes]}
            for c in snapshot_diff.changed_lines
        ],
        "moved_to_loaded": [_line(line) for line in snapshot_diff.moved_to_loaded],
        "removed_lines": [list(key) for key in snapshot_diff.removed_lines],
        "summary": snapshot_diff.summary(),
    }


async def diff_snapshots(db: AsyncSession, snapshot_a_id: uuid.UUID, snapshot_b_id: uuid.UUID) -> dict:
    """GET /snapshots/{id}/diff/{other_id} (§9.2) — structural diff between
    two already-committed snapshots, reusing the same comparison the
    upload preview runs against the previous snapshot."""
    lines_a = [parsed_line_from_db(line) for line in await order_lines_repo.list_by_snapshot(db, snapshot_a_id)]
    lines_b = [parsed_line_from_db(line) for line in await order_lines_repo.list_by_snapshot(db, snapshot_b_id)]
    return diff_to_jsonable(diff_module.compare(lines_a, lines_b))


async def create_upload_preview(
    db: AsyncSession, redis: Redis, *, org_id: uuid.UUID, file_bytes: bytes, filename: str
) -> dict:
    previous_snapshot = await order_snapshots_repo.get_latest_for_org(db, org_id)

    config = await get_active_everhealth_config(db)
    fixed_active, fixed_loaded = get_abattoir_fixed_costs()
    parsed = parse(
        file_bytes,
        filename=filename,
        cif_buffer_per_kg=config.cif_buffer_per_kg,
        fixed_cost_per_head_active=fixed_active,
        fixed_cost_per_head_loaded=fixed_loaded,
    )

    previous_lines: list[ParsedOrderLine] | None = None
    if previous_snapshot is not None:
        db_lines = await order_lines_repo.list_by_snapshot(db, previous_snapshot.id)
        previous_lines = [parsed_line_from_db(line) for line in db_lines]
    snapshot_diff = diff_module.compare(previous_lines, parsed.lines)

    # Never blocks the upload (§7.3: identical resubmission is a valid,
    # expected case, e.g. a quiet day) — just tells the human this looks
    # like something already sitting in the current snapshot, since §11.2
    # lets both Owner and Accountant upload and either could've beaten the
    # other to it.
    duplicate_of_current = None
    if previous_snapshot is not None and hashlib.sha256(file_bytes).hexdigest() == previous_snapshot.source_sha256:
        uploader = await users_repo.get_by_id(db, previous_snapshot.uploaded_by)
        duplicate_of_current = {
            "snapshot_id": previous_snapshot.id,
            "uploaded_by_email": uploader.email if uploader is not None else "unknown",
            "uploaded_at": previous_snapshot.created_at,
        }

    preview_id = str(uuid.uuid4())
    cache_payload = {
        "org_id": str(org_id),
        "filename": filename,
        "file_bytes_b64": base64.b64encode(file_bytes).decode("ascii"),
        "parsed": _serialize_parsed_snapshot(parsed),
    }
    await redis.set(
        f"{_PREVIEW_KEY_PREFIX}{preview_id}",
        json.dumps(cache_payload),
        ex=settings.upload_preview_ttl_seconds,
    )

    return {
        "preview_id": preview_id,
        "detected_layout": parsed.detected_layout.as_jsonable(),
        "active_count": len(parsed.active_lines),
        "loaded_count": len(parsed.loaded_lines),
        "diff": diff_to_jsonable(snapshot_diff),
        "duplicate_of_current": duplicate_of_current,
    }


async def commit_snapshot(
    db: AsyncSession,
    redis: Redis,
    storage: ObjectStorage,
    *,
    org_id: uuid.UUID,
    uploaded_by: uuid.UUID,
    preview_id: str,
) -> OrderSnapshot:
    raw = await redis.get(f"{_PREVIEW_KEY_PREFIX}{preview_id}")
    if raw is None:
        raise PreviewExpired()
    cache_payload = json.loads(raw)
    if cache_payload["org_id"] != str(org_id):
        raise PreviewExpired()

    file_bytes = base64.b64decode(cache_payload["file_bytes_b64"])
    parsed = _deserialize_parsed_snapshot(cache_payload["parsed"])

    # §7.2 point 11 — fetched before the new snapshot is created, so this is
    # genuinely "the previous submission's tables", never the one about to
    # be written.
    previous_snapshot = await order_snapshots_repo.get_latest_for_org(db, org_id)
    previous_tables = (
        deserialize_abattoir_tables(previous_snapshot.abattoir_reference_tables)
        if previous_snapshot is not None
        else None
    )

    source_sha256 = hashlib.sha256(file_bytes).hexdigest()
    snapshot_id = uuid.uuid4()
    storage_key = f"snapshots/{snapshot_id}/{cache_payload['filename']}"
    storage.put(storage_key, file_bytes)

    snapshot = OrderSnapshot(
        id=snapshot_id,
        org_id=org_id,
        uploaded_by=uploaded_by,
        source_filename=cache_payload["filename"],
        source_sha256=source_sha256,
        object_storage_key=storage_key,
        detected_layout=_serialize_layout(parsed.detected_layout),
        abattoir_reference_tables=_serialize_abattoir_tables(parsed.abattoir_tables),
        parser_version=parsed.parser_version,
        status=SnapshotStatus.PARSED,
    )
    await order_snapshots_repo.create(db, snapshot)
    await order_lines_repo.create_many(db, [_order_line_model(snapshot_id, line) for line in parsed.lines])

    drift_rows = compare_abattoir_tables(previous_tables, parsed.abattoir_tables)
    if drift_rows:
        now = datetime.now(UTC)
        await reference_data_drift_repo.create_many(
            db,
            [
                ReferenceDataDrift(
                    snapshot_id=snapshot_id,
                    table_key=row.table_key,
                    key1=row.key1,
                    old_value=row.old_value,
                    new_value=row.new_value,
                    detected_at=now,
                )
                for row in drift_rows
            ],
        )

    await audit_service.write(
        db,
        actor_id=uploaded_by,
        action="snapshot.committed",
        entity="order_snapshot",
        entity_id=snapshot_id,
        after={
            "source_filename": snapshot.source_filename,
            "source_sha256": source_sha256,
            "active_count": len(parsed.active_lines),
            "loaded_count": len(parsed.loaded_lines),
        },
    )

    await redis.delete(f"{_PREVIEW_KEY_PREFIX}{preview_id}")
    return snapshot
