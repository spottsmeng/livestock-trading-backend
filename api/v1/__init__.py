from fastapi import APIRouter

from api.v1 import auth, correction_requests, health, order_lines, snapshots, users

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(snapshots.router)
api_router.include_router(order_lines.router)
api_router.include_router(correction_requests.router)
