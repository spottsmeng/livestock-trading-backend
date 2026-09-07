from fastapi import APIRouter, Depends
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import redis_dep
from core.db import get_db

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(db: AsyncSession = Depends(get_db), redis: Redis = Depends(redis_dep)) -> dict:
    db_ok, redis_ok = True, True
    try:
        await db.execute(text("SELECT 1"))
    except Exception:
        db_ok = False
    try:
        await redis.ping()
    except Exception:
        redis_ok = False
    status = "ok" if db_ok and redis_ok else "degraded"
    return {"status": status, "db": db_ok, "redis": redis_ok}
