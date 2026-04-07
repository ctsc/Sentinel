"""Pydantic schemas for the Sentinel API."""

from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field


class GeoLocation(BaseModel):
    lat: Optional[float] = None
    lon: Optional[float] = None
    country_code: Optional[str] = None
    location_name: Optional[str] = None


class EventResponse(BaseModel):
    event_id: str
    source: str
    event_type: Optional[str] = "other"
    title: Optional[str] = None
    raw_text: str = ""
    timestamp: str
    source_url: Optional[str] = None
    geo: GeoLocation = Field(default_factory=GeoLocation)
    confidence: Optional[float] = 0.0
    severity: Optional[int] = 1
    entities: List[str] = Field(default_factory=list)


class EventsQueryParams(BaseModel):
    region: Optional[str] = None
    time_bucket: Optional[str] = None
    start: Optional[str] = None
    end: Optional[str] = None
    event_type: Optional[str] = None
    source: Optional[str] = None
    limit: int = Field(default=100, ge=1, le=1000)


class StatsResponse(BaseModel):
    total_events: int = 0
    sources_active: List[str] = Field(default_factory=list)
    events_per_minute: float = 0.0
