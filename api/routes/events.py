"""
REST API routes for historical event queries.

GET /events — query events by region, time, type with pagination.
"""

from typing import List, Optional

from fastapi import APIRouter, Query

from api.db import query_events
from api.models import EventResponse

router = APIRouter()


@router.get("/events", response_model=List[EventResponse])
async def get_events(
    region: Optional[str] = Query(None, description="Region partition key (e.g. middle_east, europe)"),
    time_bucket: Optional[str] = Query(None, description="Hourly bucket (e.g. 2026-04-03T14)"),
    start: Optional[str] = Query(None, description="Start time (ISO8601) — reserved for future use"),
    end: Optional[str] = Query(None, description="End time (ISO8601) — reserved for future use"),
    event_type: Optional[str] = Query(None, description="Filter by event type"),
    source: Optional[str] = Query(None, description="Filter by source — reserved for future use"),
    limit: int = Query(100, ge=1, le=1000, description="Max results to return"),
):
    """Query historical events from Cassandra."""
    events = await query_events(
        region=region,
        time_bucket=time_bucket,
        event_type=event_type,
        limit=limit,
    )
    return events
