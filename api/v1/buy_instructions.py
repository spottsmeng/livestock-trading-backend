"""§9.6, §13.1 — Buy Instruction generation, approval, issue, reconciliation
fills, and export. Trading-console surface, OWNER/ACCOUNTANT only, except
`approve` (OWNER only, §9.6 explicit) and `reconcile-close` (OWNER or
ACCOUNTANT — not in §9.6's literal list, see
services/buy_instruction_service.py's module docstring)."""

import uuid

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import CurrentUser, require_role
from core.db import get_db
from core.errors import NotFound
from core.reference_data import get_saleyard_calendar
from core.trading_calendar import trading_week_bounds
from models.buy_instruction import BuyInstruction, BuyInstructionLine
from models.enums import Role
from repositories import buy_instructions as buy_instructions_repo
from repositories import order_snapshots as order_snapshots_repo
from repositories import publications as publications_repo
from repositories import users as users_repo
from schemas.buy_instructions import (
    AddFillRequest,
    BuyInstructionLineResponse,
    BuyInstructionResponse,
    FillResponse,
    GenerateBuyInstructionRequest,
    PatchBuyInstructionRequest,
    ReconciliationResponse,
    ReconciliationSummaryResponse,
    SaleyardReconciliationResponse,
)
from services import buy_instruction_export as export_service
from services import buy_instruction_service

router = APIRouter(prefix="/buy-instructions", tags=["buy-instructions"])

_trading_console = require_role(Role.OWNER, Role.ACCOUNTANT)
_owner_only = require_role(Role.OWNER)


async def _to_response(db: AsyncSession, instruction: BuyInstruction) -> BuyInstructionResponse:
    lines = await buy_instructions_repo.list_lines(db, instruction.id)
    fills = await buy_instructions_repo.list_fills_for_lines(db, [line.id for line in lines])
    fills_by_line: dict[uuid.UUID, list] = {}
    for fill in fills:
        fills_by_line.setdefault(fill.line_id, []).append(fill)

    line_responses = [
        BuyInstructionLineResponse(
            id=line.id,
            seq=line.seq,
            order_line_id=line.order_line_id,
            contract_no=line.contract_no,
            species=line.species,
            schw_kg=line.schw_kg,
            expected_heads=line.expected_heads,
            weight_requirement_kg=line.weight_requirement_kg,
            dnbp_per_kg=line.dnbp_per_kg,
            peters_expectation=line.peters_expectation,
            expected_livestock_cost=line.expected_livestock_cost,
            fills=[FillResponse.model_validate(f) for f in fills_by_line.get(line.id, [])],
            balance_kg=buy_instruction_service.line_balance(line, fills_by_line.get(line.id, [])),
        )
        for line in lines
    ]
    return BuyInstructionResponse(
        id=instruction.id,
        org_id=instruction.org_id,
        instruction_no=instruction.instruction_no,
        version=instruction.version,
        trade_date=instruction.trade_date,
        snapshot_id=instruction.snapshot_id,
        publication_id=instruction.publication_id,
        prepared_by=instruction.prepared_by,
        approved_by=instruction.approved_by,
        approved_at=instruction.approved_at,
        note=instruction.note,
        status=instruction.status.value,
        lines=line_responses,
    )


async def _get_owned(db: AsyncSession, instruction_id: uuid.UUID, org_id: uuid.UUID) -> BuyInstruction:
    instruction = await buy_instructions_repo.get_by_id(db, instruction_id)
    if instruction is None or instruction.org_id != org_id:
        raise NotFound("Buy instruction")
    return instruction


async def _get_owned_line(db: AsyncSession, instruction: BuyInstruction, line_id: uuid.UUID) -> BuyInstructionLine:
    line = await buy_instructions_repo.get_line(db, line_id)
    if line is None or line.instruction_id != instruction.id:
        raise NotFound("Buy instruction line")
    return line


@router.post("", response_model=BuyInstructionResponse, status_code=201)
async def generate(
    body: GenerateBuyInstructionRequest,
    current: CurrentUser = Depends(_trading_console),
    db: AsyncSession = Depends(get_db),
) -> BuyInstructionResponse:
    snapshot = await order_snapshots_repo.get_by_id(db, body.snapshot_id)
    if snapshot is None or snapshot.org_id != current.org_id:
        raise NotFound("Snapshot")
    publication = await publications_repo.get_by_id(db, body.publication_id)
    if publication is None or publication.org_id != current.org_id:
        raise NotFound("Publication")

    instruction, _lines = await buy_instruction_service.generate(
        db,
        snapshot=snapshot,
        publication=publication,
        actor_id=current.user_id,
        trade_date=body.trade_date,
        note=body.note,
    )
    await db.commit()
    return await _to_response(db, instruction)


@router.get("", response_model=list[BuyInstructionResponse])
async def list_instructions(
    trade_date: str | None = Query(default=None),
    status: str | None = Query(default=None),
    current: CurrentUser = Depends(_trading_console),
    db: AsyncSession = Depends(get_db),
) -> list[BuyInstructionResponse]:
    from datetime import date as date_cls

    parsed_date = date_cls.fromisoformat(trade_date) if trade_date else None
    instructions = await buy_instructions_repo.list_for_org(db, current.org_id, trade_date=parsed_date, status=status)
    return [await _to_response(db, instruction) for instruction in instructions]


@router.get("/{instruction_id}", response_model=BuyInstructionResponse)
async def get_instruction(
    instruction_id: uuid.UUID, current: CurrentUser = Depends(_trading_console), db: AsyncSession = Depends(get_db)
) -> BuyInstructionResponse:
    instruction = await _get_owned(db, instruction_id, current.org_id)
    return await _to_response(db, instruction)


@router.patch("/{instruction_id}", response_model=BuyInstructionResponse)
async def patch_instruction(
    instruction_id: uuid.UUID,
    body: PatchBuyInstructionRequest,
    current: CurrentUser = Depends(_trading_console),
    db: AsyncSession = Depends(get_db),
) -> BuyInstructionResponse:
    instruction = await _get_owned(db, instruction_id, current.org_id)
    await buy_instruction_service.update_note(db, instruction, note=body.note, actor_id=current.user_id)
    await db.commit()
    return await _to_response(db, instruction)


@router.post("/{instruction_id}/approve", response_model=BuyInstructionResponse)
async def approve(
    instruction_id: uuid.UUID, current: CurrentUser = Depends(_owner_only), db: AsyncSession = Depends(get_db)
) -> BuyInstructionResponse:
    instruction = await _get_owned(db, instruction_id, current.org_id)
    await buy_instruction_service.approve(db, instruction, actor_id=current.user_id)
    await db.commit()
    return await _to_response(db, instruction)


@router.post("/{instruction_id}/issue", response_model=BuyInstructionResponse)
async def issue(
    instruction_id: uuid.UUID, current: CurrentUser = Depends(_trading_console), db: AsyncSession = Depends(get_db)
) -> BuyInstructionResponse:
    instruction = await _get_owned(db, instruction_id, current.org_id)
    await buy_instruction_service.issue(db, instruction, actor_id=current.user_id)
    await db.commit()
    return await _to_response(db, instruction)


@router.post("/{instruction_id}/reconcile-close", response_model=BuyInstructionResponse)
async def reconcile_close(
    instruction_id: uuid.UUID, current: CurrentUser = Depends(_trading_console), db: AsyncSession = Depends(get_db)
) -> BuyInstructionResponse:
    instruction = await _get_owned(db, instruction_id, current.org_id)
    await buy_instruction_service.reconcile_close(db, instruction, actor_id=current.user_id)
    await db.commit()
    return await _to_response(db, instruction)


@router.post("/{instruction_id}/lines/{line_id}/fills", response_model=BuyInstructionResponse, status_code=201)
async def add_fill(
    instruction_id: uuid.UUID,
    line_id: uuid.UUID,
    body: AddFillRequest,
    current: CurrentUser = Depends(_trading_console),
    db: AsyncSession = Depends(get_db),
) -> BuyInstructionResponse:
    instruction = await _get_owned(db, instruction_id, current.org_id)
    line = await _get_owned_line(db, instruction, line_id)
    await buy_instruction_service.add_fill(
        db, instruction, line, label=body.label, kg_amount=body.kg_amount, actor_id=current.user_id
    )
    await db.commit()
    return await _to_response(db, instruction)


@router.delete("/{instruction_id}/lines/{line_id}/fills/{fill_id}", response_model=BuyInstructionResponse)
async def remove_fill(
    instruction_id: uuid.UUID,
    line_id: uuid.UUID,
    fill_id: uuid.UUID,
    current: CurrentUser = Depends(_trading_console),
    db: AsyncSession = Depends(get_db),
) -> BuyInstructionResponse:
    instruction = await _get_owned(db, instruction_id, current.org_id)
    line = await _get_owned_line(db, instruction, line_id)
    fill = await buy_instructions_repo.get_fill(db, fill_id)
    if fill is None or fill.line_id != line.id:
        raise NotFound("Fill")
    await buy_instruction_service.remove_fill(db, instruction, fill, actor_id=current.user_id)
    await db.commit()
    return await _to_response(db, instruction)


@router.get("/{instruction_id}/reconciliation", response_model=ReconciliationResponse)
async def get_reconciliation(
    instruction_id: uuid.UUID, current: CurrentUser = Depends(_trading_console), db: AsyncSession = Depends(get_db)
) -> ReconciliationResponse:
    instruction = await _get_owned(db, instruction_id, current.org_id)
    rows, summary = await buy_instruction_service.compute_reconciliation(db, instruction)
    week_start, week_end = trading_week_bounds(instruction.trade_date)
    return ReconciliationResponse(
        week_start=week_start,
        week_end=week_end,
        by_saleyard=[
            SaleyardReconciliationResponse(
                saleyard=r.saleyard, schw_kg=r.schw_kg, heads=r.heads, actual_cost=r.actual_cost
            )
            for r in rows
        ],
        summary=ReconciliationSummaryResponse(
            actual_heads=summary.actual_heads,
            expected_heads=summary.expected_heads,
            ordered_schw=summary.ordered_schw,
            bought_schw=summary.bought_schw,
            surplus_shortfall_schw=summary.surplus_shortfall_schw,
            expected_cost=summary.expected_cost,
            actual_cost=summary.actual_cost,
            cost_variance=summary.cost_variance,
        ),
    )


@router.get("/{instruction_id}/export")
async def export_instruction(
    instruction_id: uuid.UUID,
    format: str = Query(..., pattern="^(pdf|xlsx)$"),
    current: CurrentUser = Depends(_trading_console),
    db: AsyncSession = Depends(get_db),
) -> Response:
    instruction = await _get_owned(db, instruction_id, current.org_id)
    lines = await buy_instructions_repo.list_lines(db, instruction.id)
    fills = await buy_instructions_repo.list_fills_for_lines(db, [line.id for line in lines])
    fills_by_line: dict[uuid.UUID, list] = {}
    for fill in fills:
        fills_by_line.setdefault(fill.line_id, []).append(fill)

    rows, summary = await buy_instruction_service.compute_reconciliation(db, instruction)
    week_start, week_end = trading_week_bounds(instruction.trade_date)

    prepared_by = await users_repo.get_by_id(db, instruction.prepared_by)
    approved_by = await users_repo.get_by_id(db, instruction.approved_by) if instruction.approved_by else None

    data = export_service.build_export_data(
        instruction=instruction,
        lines=lines,
        fills_by_line=fills_by_line,
        saleyard_calendar=get_saleyard_calendar(),
        week_start=week_start,
        week_end=week_end,
        reconciliation=rows,
        summary=summary,
        prepared_by_name=prepared_by.email if prepared_by else "(unknown)",
        approved_by_name=approved_by.email if approved_by else None,
    )

    filename = f"{instruction.instruction_no}-v{instruction.version}.{format}"
    if format == "xlsx":
        content = export_service.render_xlsx(data)
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    else:
        content = export_service.render_pdf(data)
        media_type = "application/pdf"

    return Response(
        content=content, media_type=media_type, headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )
