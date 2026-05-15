from __future__ import annotations

from fastapi import APIRouter

from app.api import auth, candidates, cv, esco, health, interviews, jobs, matching, rag, reports, voice, ws

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(auth.router, tags=["auth"])
api_router.include_router(cv.router, tags=["cv"])
api_router.include_router(candidates.router, tags=["candidates"])
api_router.include_router(jobs.router, tags=["jobs"])
api_router.include_router(matching.router, tags=["matching"])
api_router.include_router(interviews.router, tags=["interviews"])
api_router.include_router(reports.router, tags=["reports"])
api_router.include_router(rag.router, tags=["rag"])
api_router.include_router(esco.router, tags=["esco"])
api_router.include_router(voice.router, tags=["voice"])
api_router.include_router(ws.router)
