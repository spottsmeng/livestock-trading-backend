"""§6.9/§9.8/§11.7 — the species/product-type open registries as admin-
managed data, plus each species' pricing-prerequisite status (§6.9's
onboarding checklist): does it have a dnbp_factor (mandatory before pricing)
and a standard_weight (optional, supporting-analysis only)?
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import RegistryCodeExists
from core.reference_data import get_active_everhealth_config
from models.reference_data import ProductTypeRegistry, SpeciesRegistry
from repositories import registries as registries_repo
from services import audit_service


async def list_species_with_pricing_status(db: AsyncSession) -> list[dict]:
    rows = await registries_repo.list_species(db)
    config = await get_active_everhealth_config(db)
    return [
        {
            "code": row.code,
            "display_name": row.display_name,
            "is_active": row.is_active,
            "has_dnbp_factor": row.code in config.dnbp_factor_by_species,
            "has_standard_weight": row.code in config.standard_weight_by_species,
        }
        for row in rows
    ]


async def create_species(db: AsyncSession, *, code: str, display_name: str, actor_id: uuid.UUID) -> SpeciesRegistry:
    normalised = code.strip().upper()
    if await registries_repo.get_species(db, normalised) is not None:
        raise RegistryCodeExists(normalised)

    row = await registries_repo.create_species(db, code=normalised, display_name=display_name, created_by=actor_id)
    await audit_service.write(
        db,
        actor_id=actor_id,
        action="species_registry.created",
        entity="species_registry",
        entity_id=None,
        after={"code": normalised, "display_name": display_name},
    )
    return row


async def list_product_types(db: AsyncSession) -> list[ProductTypeRegistry]:
    return await registries_repo.list_product_types(db)


async def create_product_type(
    db: AsyncSession, *, code: str, display_name: str, actor_id: uuid.UUID
) -> ProductTypeRegistry:
    normalised = code.strip().upper()
    if await registries_repo.get_product_type(db, normalised) is not None:
        raise RegistryCodeExists(normalised)

    row = await registries_repo.create_product_type(
        db, code=normalised, display_name=display_name, created_by=actor_id
    )
    await audit_service.write(
        db,
        actor_id=actor_id,
        action="product_type_registry.created",
        entity="product_type_registry",
        entity_id=None,
        after={"code": normalised, "display_name": display_name},
    )
    return row
