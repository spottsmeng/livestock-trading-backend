import dataclasses
import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import CurrentUser, require_role
from core.db import get_db
from models.enums import Role
from schemas.reference_data import (
    AbattoirTablesResponse,
    ActiveConfigResponse,
    CreateProductTypeRequest,
    CreateSpeciesRequest,
    CreateVersionRequest,
    DriftResponse,
    ImpactLineResponse,
    ImpactPreviewResponse,
    ProductTypeResponse,
    ReferenceDataEntryResponse,
    ReferenceDataVersionDetailResponse,
    ReferenceDataVersionResponse,
    SpeciesResponse,
)
from services import reference_data_drift_service, reference_data_service, registry_service

router = APIRouter(prefix="/reference-data", tags=["reference-data"])

# §9.8 — the DNBP model belongs to both Bobby and Bing (§2.1); neither is
# gated ahead of the other here, same as publications.
_trading_console = require_role(Role.OWNER, Role.ACCOUNTANT)


@router.get("/active", response_model=ActiveConfigResponse)
async def get_active(current: CurrentUser = Depends(_trading_console), db: AsyncSession = Depends(get_db)):
    config = await reference_data_service.get_active_config(db)
    return ActiveConfigResponse(
        ref_data_version=config.ref_data_version,
        cif_buffer_per_kg=config.cif_buffer_per_kg,
        dnbp_factor_by_species=config.dnbp_factor_by_species,
        standard_weight_by_species=config.standard_weight_by_species,
    )


@router.get("/versions", response_model=list[ReferenceDataVersionResponse])
async def list_versions(current: CurrentUser = Depends(_trading_console), db: AsyncSession = Depends(get_db)):
    return await reference_data_service.list_versions(db)


@router.get("/versions/{version_id}", response_model=ReferenceDataVersionDetailResponse)
async def get_version(
    version_id: uuid.UUID, current: CurrentUser = Depends(_trading_console), db: AsyncSession = Depends(get_db)
):
    version, entries = await reference_data_service.get_version_with_entries(db, version_id)
    return ReferenceDataVersionDetailResponse(
        **ReferenceDataVersionResponse.model_validate(version).model_dump(),
        entries=[ReferenceDataEntryResponse.model_validate(e) for e in entries],
    )


@router.post("/versions", response_model=ReferenceDataVersionResponse, status_code=201)
async def create_version(
    body: CreateVersionRequest,
    current: CurrentUser = Depends(_trading_console),
    db: AsyncSession = Depends(get_db),
):
    version = await reference_data_service.create_version(
        db,
        actor_id=current.user_id,
        effective_from=body.effective_from,
        note=body.note,
        raw_entries=[(e.table_key, e.key1, e.value) for e in body.entries],
    )
    await db.commit()
    return version


@router.post("/versions/{version_id}/impact", response_model=ImpactPreviewResponse)
async def preview_impact(
    version_id: uuid.UUID, current: CurrentUser = Depends(_trading_console), db: AsyncSession = Depends(get_db)
):
    preview = await reference_data_service.preview_impact(db, version_id, org_id=current.org_id)
    await db.commit()
    return ImpactPreviewResponse(
        lines=[ImpactLineResponse(**dataclasses.asdict(line)) for line in preview.lines],
        aggregate_exposure_delta_aud=preview.aggregate_exposure_delta_aud,
        lines_affected=preview.lines_affected,
    )


@router.post("/versions/{version_id}/activate", response_model=ReferenceDataVersionResponse)
async def activate_version(
    version_id: uuid.UUID, current: CurrentUser = Depends(_trading_console), db: AsyncSession = Depends(get_db)
):
    version = await reference_data_service.activate_version(db, version_id, actor_id=current.user_id)
    await db.commit()
    return version


@router.get("/abattoir", response_model=AbattoirTablesResponse)
async def get_abattoir_tables(current: CurrentUser = Depends(_trading_console), db: AsyncSession = Depends(get_db)):
    snapshot, tables = await reference_data_service.get_latest_abattoir_tables(db, org_id=current.org_id)
    return AbattoirTablesResponse(
        snapshot_id=snapshot.id,
        source_filename=snapshot.source_filename,
        pack_cost_by_product_type=tables.pack_cost_by_product_type,
        offal_return_ph_by_species=tables.offal_return_ph_by_species,
        skin_return_ph_by_species=tables.skin_return_ph_by_species,
    )


@router.get("/drift", response_model=list[DriftResponse])
async def list_drift(
    unacknowledged: bool = Query(default=False),
    current: CurrentUser = Depends(_trading_console),
    db: AsyncSession = Depends(get_db),
):
    return await reference_data_drift_service.list_drift(db, unacknowledged_only=unacknowledged)


@router.post("/drift/{drift_id}/acknowledge", response_model=DriftResponse)
async def acknowledge_drift(
    drift_id: uuid.UUID, current: CurrentUser = Depends(_trading_console), db: AsyncSession = Depends(get_db)
):
    drift = await reference_data_drift_service.acknowledge(db, drift_id, actor_id=current.user_id)
    await db.commit()
    return drift


@router.get("/species", response_model=list[SpeciesResponse])
async def list_species(current: CurrentUser = Depends(_trading_console), db: AsyncSession = Depends(get_db)):
    return await registry_service.list_species_with_pricing_status(db)


@router.post("/species", response_model=SpeciesResponse, status_code=201)
async def create_species(
    body: CreateSpeciesRequest, current: CurrentUser = Depends(_trading_console), db: AsyncSession = Depends(get_db)
):
    await registry_service.create_species(db, code=body.code, display_name=body.display_name, actor_id=current.user_id)
    await db.commit()
    rows = await registry_service.list_species_with_pricing_status(db)
    return next(row for row in rows if row["code"] == body.code.strip().upper())


@router.get("/product-types", response_model=list[ProductTypeResponse])
async def list_product_types(current: CurrentUser = Depends(_trading_console), db: AsyncSession = Depends(get_db)):
    return await registry_service.list_product_types(db)


@router.post("/product-types", response_model=ProductTypeResponse, status_code=201)
async def create_product_type(
    body: CreateProductTypeRequest,
    current: CurrentUser = Depends(_trading_console),
    db: AsyncSession = Depends(get_db),
):
    row = await registry_service.create_product_type(
        db, code=body.code, display_name=body.display_name, actor_id=current.user_id
    )
    await db.commit()
    return row
