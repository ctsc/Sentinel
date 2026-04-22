"""
REST API routes for historical event queries.

GET /events — query events by region, time, type, source with pagination.
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
    event_type: Optional[str] = Query(None, description="Filter by event type"),
    source: Optional[str] = Query(None, description="Filter by source (gdelt, acled, rss, bluesky, wikipedia)"),
    hours: int = Query(168, ge=1, le=8760, description="Sweep window in hours going back from now (default 168 = 7 days, max 8760 = 1 year)"),
    limit: int = Query(1000, ge=1, le=5000, description="Max results to return"),
):
    """Query historical events from Cassandra.

    Default sweeps the last 7 days across all regions, newest-first.
    """
    events = await query_events(
        region=region,
        time_bucket=time_bucket,
        event_type=event_type,
        source=source,
        hours=hours,
        limit=limit,
    )
    return events
