from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.enums import OrgKind
from models.organisation import Organisation


async def get_by_kind(db: AsyncSession, kind: OrgKind) -> Organisation | None:
    result = await db.execute(select(Organisation).where(Organisation.kind == kind))
    return result.scalar_one_or_none()
