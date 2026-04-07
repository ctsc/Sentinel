"""
FastAPI application — Sentinel API.

REST endpoints for historical queries + WebSocket for live streaming.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes.events import router as events_router
from api.routes.ws import router as ws_router
from api import db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    db.close()


app = FastAPI(
    title="Sentinel API",
    description="Real-Time Global Conflict & News Intelligence Dashboard",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS — allow frontend dev server and production origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount routes
app.include_router(events_router, tags=["events"])
app.include_router(ws_router, tags=["websocket"])


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok", "service": "sentinel-api"}
