"""POST /snapshots/{id}/calculate (§9.2) — runs Phase 1's engine over every
line in a snapshot for the first time in this system's life:
`domain.engine.workings.compute_order_workings` per line, plus
`domain.engine.crosscheck`'s §5.2 comparisons against the submission's own
lookup sheet for ACTIVE lines. Also where a correction request auto-resolves
once a later snapshot supplies a previously-missing value (§9.3).

Calculation is idempotent — re-running it replaces each line's workings row
and issue set rather than accumulating duplicates (repositories/
order_workings.py's `upsert`, repositories/validation_issues.py's
`replace_for_line`).
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from core.reference_data import get_everhealth_config
from domain.engine import crosscheck
from domain.engine import issues as codes
from domain.engine.crosscheck import AbattoirReferenceTables
from domain.engine.issues import Severity, ValidationIssue, check_dnbp_outlier
from domain.engine.workings import Lifecycle, OrderLineInput, compute_order_workings
from domain.ingestion.types import BenchmarkMethod
from models.enums import CorrectionStatus
from models.order_line import OrderLine
from models.order_snapshot import OrderSnapshot
from models.order_workings import OrderWorkings
from models.validation_issue import ValidationIssueRecord
from repositories import correction_requests as correction_requests_repo
from repositories import order_lines as order_lines_repo
from repositories import order_workings as order_workings_repo
from repositories import publications as publications_repo
from repositories import validation_issues as validation_issues_repo
from services import audit_service
from services.ingestion_service import deserialize_abattoir_tables

DNBP_OUTLIER_LOOKBACK_DAYS = 30  # §5.7 — "> 15% off recent average" is a trailing 30-day species mean

ENGINE_VERSION = "BingMultiplierV1"  # §5.6 — the one shipped, publishable engine method


def _line_input(order_line: OrderLine) -> OrderLineInput:
    return OrderLineInput(
        species=order_line.species,
        lifecycle=order_line.lifecycle,
        contract_no=order_line.contract_no,
        avg_price_aud=order_line.avg_price_aud,
        incoterm=order_line.incoterm.value if order_line.incoterm else None,
        expected_livestock_cost_per_kg=order_line.expected_livestock_cost_per_kg,
        pack_cost_ph=order_line.pack_cost_ph,
        offal_return_ph=order_line.offal_return_ph,
        skin_return_ph=order_line.skin_return_ph,
        avg_weight_kg=order_line.avg_weight_kg,
        mom_ph=order_line.mom_ph,
        dnbp_benchmark=order_line.dnbp_benchmark,
        loadout_date=order_line.loadout_date.isoformat() if order_line.loadout_date else None,
    )


def _run_crosscheck(order_line: OrderLine, tables: AbattoirReferenceTables) -> list[ValidationIssue]:
    """§5.2 — only ever runs for ACTIVE lines (the caller enforces this);
    RECEIVED_VALUE_MISMATCH is an ACTIVE-only code (domain/engine/issues.py
    ACTIVE_ONLY_CODES) since it protects nothing on a line whose livestock
    was already bought."""
    issues: list[ValidationIssue] = []

    if order_line.avg_price_aud is not None and order_line.incoterm is not None:
        expected_k = crosscheck.expected_nrv_per_kg(order_line.avg_price_aud, order_line.incoterm.value, tables)
        issues.append(crosscheck.check("K", order_line.nrv_per_kg, expected_k))

    if order_line.product_type is not None:
        expected_m = crosscheck.expected_pack_cost_ph(order_line.product_type, tables)
        issues.append(crosscheck.check("M", order_line.pack_cost_ph, expected_m))

    if order_line.species is not None:
        expected_n = crosscheck.expected_offal_return_ph(order_line.species, tables)
        issues.append(crosscheck.check("N", order_line.offal_return_ph, expected_n))

        # §5.2: a hand-set skin return is a deliberate abattoir divergence,
        # not an error — already surfaced via HAND_SET_VALUE. Cross-checking
        # it here too would raise a confusing second, contradictory issue
        # on the very cell §5.2 says explicitly not to "correct".
        if order_line.value_sources.get("skin_return_ph") != "HAND_SET":
            expected_o = crosscheck.expected_skin_return_ph(order_line.species, tables)
            issues.append(crosscheck.check("O", order_line.skin_return_ph, expected_o))

    if None not in (
        order_line.nrv_per_kg,
        order_line.expected_livestock_cost_per_kg,
        order_line.avg_weight_kg,
        order_line.offal_return_ph,
        order_line.skin_return_ph,
        order_line.pack_cost_ph,
    ):
        expected_q = crosscheck.expected_mom_ph(
            nrv_per_kg=order_line.nrv_per_kg,
            livestock_cost_per_kg=order_line.expected_livestock_cost_per_kg,
            avg_weight_kg=order_line.avg_weight_kg,
            offal_return_ph=order_line.offal_return_ph,
            skin_return_ph=order_line.skin_return_ph,
            pack_cost_ph=order_line.pack_cost_ph,
        )
        issues.append(crosscheck.check("Q", order_line.mom_ph, expected_q))

    if order_line.qty_kg is not None and order_line.avg_weight_kg is not None:
        expected_u = crosscheck.expected_estimated_heads(order_line.qty_kg, order_line.avg_weight_kg)
        issues.append(crosscheck.check("U", order_line.estimated_heads, expected_u))

    if order_line.expected_livestock_cost_per_kg is not None and order_line.qty_kg is not None:
        expected_v = crosscheck.expected_total_livestock_cost(
            order_line.expected_livestock_cost_per_kg, order_line.qty_kg
        )
        issues.append(crosscheck.check("V", order_line.total_livestock_cost, expected_v))

    if order_line.dnbp_benchmark is None:
        issues.append(
            ValidationIssue(
                codes.RECEIVED_BENCHMARK_ABSENT,
                Severity.CORRECTION,
                "No abattoir DNBP benchmark in file — AE unavailable",
            )
        )
    elif (
        order_line.benchmark_method == BenchmarkMethod.GAYAN_FIXED_COST
        and None
        not in (
            order_line.nrv_per_kg,
            order_line.avg_weight_kg,
            order_line.pack_cost_ph,
            order_line.offal_return_ph,
            order_line.skin_return_ph,
        )
    ):
        # The financier-% method (§5.6a) is a different abattoir formula
        # crosscheck.py does not reproduce — §5.2's normative pseudocode
        # only specifies the Gayan fixed-cost formula. A benchmark present
        # via the other method is stored and used for AE regardless; it is
        # simply not cross-checkable here.
        expected_t = crosscheck.expected_dnbp_gayan(
            nrv_per_kg=order_line.nrv_per_kg,
            avg_weight_kg=order_line.avg_weight_kg,
            pack_cost_ph=order_line.pack_cost_ph,
            offal_return_ph=order_line.offal_return_ph,
            skin_return_ph=order_line.skin_return_ph,
            lifecycle=order_line.lifecycle.value,
            tables=tables,
        )
        issues.append(crosscheck.check("T", order_line.dnbp_benchmark, expected_t))

    return [issue for issue in issues if issue is not None]


def _hand_set_issues(order_line: OrderLine) -> list[ValidationIssue]:
    """§5.7's `HAND_SET_VALUE` (WARN) — a formula-driven column holding a
    literal, per the provenance domain/ingestion/workbook.py already
    recorded on `value_sources` at parse time (§7.2 pt 4). This is exactly
    how the GOAT skin-return `0.5` override gets surfaced to Bing: used as
    submitted, never "corrected" (§5.2), but visibly flagged."""
    return [
        ValidationIssue(
            codes.HAND_SET_VALUE,
            Severity.WARN,
            f"{column} was hand-set in the submission to {getattr(order_line, column)}",
            column_ref=column,
        )
        for column, source in order_line.value_sources.items()
        if source == "HAND_SET"
    ]


async def _check_dnbp_outlier(
    db: AsyncSession, snapshot: OrderSnapshot, workings, species: str | None
) -> list[ValidationIssue]:
    """§5.7 `DNBP_OUTLIER` — deferred by Phase 2's own instructions
    ("nothing has been published yet"); buildable now that
    dnbp_publications/dnbp_publication_lines exist (Phase 3). The 30-day
    average is scoped to this org only — a species average from before
    this org's own publication history began is simply None (no history),
    never a cross-org or synthetic baseline."""
    if workings is None or workings.bing_dnbp is None or species is None:
        return []
    since = datetime.now(UTC) - timedelta(days=DNBP_OUTLIER_LOOKBACK_DAYS)
    average = await publications_repo.recent_species_average(db, snapshot.org_id, species, since=since)
    issue = check_dnbp_outlier(workings.bing_dnbp, average)
    return [issue] if issue else []


async def calculate_snapshot(db: AsyncSession, snapshot: OrderSnapshot, *, actor_id: uuid.UUID) -> dict:
    config = get_everhealth_config()
    abattoir_tables = deserialize_abattoir_tables(snapshot.abattoir_reference_tables)

    lines = await order_lines_repo.list_by_snapshot(db, snapshot.id)

    active_computed = blocked = correction_flags = warnings = 0

    for order_line in lines:
        workings, engine_issues = compute_order_workings(_line_input(order_line), config)

        crosscheck_issues: list[ValidationIssue] = []
        hand_set_issues: list[ValidationIssue] = []
        outlier_issues: list[ValidationIssue] = []
        if order_line.lifecycle is Lifecycle.ACTIVE:
            crosscheck_issues = _run_crosscheck(order_line, abattoir_tables)
            hand_set_issues = _hand_set_issues(order_line)
            outlier_issues = await _check_dnbp_outlier(db, snapshot, workings, order_line.species)

        all_issues = [*engine_issues, *crosscheck_issues, *hand_set_issues, *outlier_issues]

        if workings is not None:
            model = OrderWorkings(
                order_line_id=order_line.id,
                engine_version=ENGINE_VERSION,
                ref_data_version=config.ref_data_version,
                adjusted_price_per_kg=workings.adjusted_price_per_kg,
                pack_cost_per_kg=workings.pack_cost_per_kg,
                offal_return_per_kg=workings.offal_return_per_kg,
                skin_return_per_kg=workings.skin_return_per_kg,
                profit_on_peter_costs=workings.profit_on_peter_costs,
                bing_dnbp=workings.bing_dnbp,
                bing_dnbp_factor_used=workings.bing_dnbp_factor_used,
                bing_dnbp_inputs={
                    "avg_price_aud": str(order_line.avg_price_aud) if order_line.avg_price_aud is not None else None,
                    "species": order_line.species,
                    "cif_buffer_per_kg": str(config.cif_buffer_per_kg),
                    "dnbp_factor": (
                        str(workings.bing_dnbp_factor_used) if workings.bing_dnbp_factor_used is not None else None
                    ),
                },
                profit_on_bing_dnbp=workings.profit_on_bing_dnbp,
                diff_vs_benchmark=workings.diff_vs_benchmark,
                diff_vs_peter=workings.diff_vs_peter,
                supporting_analysis_complete=workings.supporting_analysis_complete,
            )
            await order_workings_repo.upsert(db, model)
            active_computed += 1

        issue_models = [
            ValidationIssueRecord(
                order_line_id=order_line.id,
                code=issue.code,
                severity=issue.severity,
                message=issue.message,
                column_ref=issue.column_ref,
            )
            for issue in all_issues
        ]
        await validation_issues_repo.replace_for_line(db, order_line.id, issue_models)

        for issue in all_issues:
            if issue.severity is Severity.BLOCK:
                blocked += 1
            elif issue.severity is Severity.CORRECTION:
                correction_flags += 1
            elif issue.severity is Severity.WARN:
                warnings += 1

    resolved_count = await _auto_resolve_correction_requests(db, snapshot)

    await audit_service.write(
        db,
        actor_id=actor_id,
        action="snapshot.calculated",
        entity="order_snapshot",
        entity_id=snapshot.id,
        after={
            "active_lines_computed": active_computed,
            "blocked_issues": blocked,
            "correction_issues": correction_flags,
            "warnings": warnings,
            "correction_requests_auto_resolved": resolved_count,
        },
    )

    return {
        "active_lines_computed": active_computed,
        "blocked_issues": blocked,
        "correction_issues": correction_flags,
        "warnings": warnings,
        "correction_requests_auto_resolved": resolved_count,
    }


async def _auto_resolve_correction_requests(db: AsyncSession, snapshot: OrderSnapshot) -> int:
    """§9.3: a correction request auto-resolves when a later snapshot
    supplies a valid (non-null) value for the same flagged line — matched
    by identity, since order_line rows are immutable and a new snapshot
    creates entirely new rows — and column."""
    open_requests = await correction_requests_repo.list_open_for_org(db, snapshot.org_id)
    resolved_count = 0

    for request in open_requests:
        if request.snapshot_id == snapshot.id:
            continue  # a request can never resolve against the very snapshot it was raised on

        flagged_line = await correction_requests_repo.order_line_for(db, request)
        if flagged_line is None:
            continue

        candidate_line = await order_lines_repo.find_by_identity(
            db,
            snapshot.id,
            contract_no=flagged_line.contract_no,
            species=flagged_line.species,
            product_type=flagged_line.product_type,
            incoterm=flagged_line.incoterm.value if flagged_line.incoterm else None,
        )
        if candidate_line is None:
            continue

        new_value = getattr(candidate_line, request.column_ref, None)
        if new_value is None:
            continue

        request.status = CorrectionStatus.RESOLVED
        request.resolved_by_snapshot_id = snapshot.id
        request.resolved_at = datetime.now(UTC)
        resolved_count += 1

        await audit_service.write(
            db,
            actor_id=None,  # system-detected resolution, not a user action
            action="correction_request.auto_resolved",
            entity="correction_request",
            entity_id=request.id,
            before={"status": CorrectionStatus.OPEN.value},
            after={"status": CorrectionStatus.RESOLVED.value, "resolved_by_snapshot_id": str(snapshot.id)},
        )

    return resolved_count
