import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.reference_data import ProductTypeRegistry, SpeciesRegistry


async def list_species(db: AsyncSession) -> list[SpeciesRegistry]:
    result = await db.execute(select(SpeciesRegistry).order_by(SpeciesRegistry.code))
    return list(result.scalars().all())


async def get_species(db: AsyncSession, code: str) -> SpeciesRegistry | None:
    return await db.get(SpeciesRegistry, code)


async def create_species(db: AsyncSession, *, code: str, display_name: str, created_by: uuid.UUID) -> SpeciesRegistry:
    row = SpeciesRegistry(code=code, display_name=display_name, is_active=True, created_by=created_by)
    db.add(row)
    await db.flush()
    return row


async def list_product_types(db: AsyncSession) -> list[ProductTypeRegistry]:
    result = await db.execute(select(ProductTypeRegistry).order_by(ProductTypeRegistry.code))
    return list(result.scalars().all())


async def get_product_type(db: AsyncSession, code: str) -> ProductTypeRegistry | None:
    return await db.get(ProductTypeRegistry, code)


async def create_product_type(
    db: AsyncSession, *, code: str, display_name: str, created_by: uuid.UUID
) -> ProductTypeRegistry:
    row = ProductTypeRegistry(code=code, display_name=display_name, is_active=True, created_by=created_by)
    db.add(row)
    await db.flush()
    return row
