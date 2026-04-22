"""
Geocoder — converts location entity names to lat/lon coordinates.

Uses a pre-seeded LRU cache from geo_cache_seed.json (~500 conflict locations).
Falls back to geopy Nominatim for cache misses.

Only called for unstructured sources (RSS, Bluesky, Wikipedia).
GDELT/ACLED already have coordinates — pass through directly.
"""

import atexit
import json
import logging
import os
import time
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

# In-memory cache seeded from JSON file
_geo_cache: dict = {}
_nominatim_hits = 0
_cache_hits = 0

# Learned entries accumulated during this session (to persist on shutdown)
_learned_entries: dict = {}
_DATA_DIR = os.path.join(Path(__file__).parent.parent.parent, "data")
_LEARNED_CACHE_PATH = os.path.join(_DATA_DIR, "geo_cache_learned.json")


def _flush_learned_cache():
    """Persist learned geocoding entries to disk."""
    if not _learned_entries:
        return
    try:
        # Merge with existing file if present
        existing = {}
        if os.path.exists(_LEARNED_CACHE_PATH):
            try:
                with open(_LEARNED_CACHE_PATH, "r", encoding="utf-8") as f:
                    existing = json.load(f)
            except (json.JSONDecodeError, OSError):
                pass
        existing.update(_learned_entries)
        os.makedirs(_DATA_DIR, exist_ok=True)
        with open(_LEARNED_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(existing, f, ensure_ascii=False, indent=2)
        logger.info("Flushed %d learned geocoding entries to disk", len(_learned_entries))
    except OSError as e:
        logger.warning("Failed to flush learned geocoding cache: %s", e)


atexit.register(_flush_learned_cache)


def load_cache(cache_path: Optional[str] = None):
    """Load the pre-seeded geocoding cache and learned cache from JSON."""
    global _geo_cache

    if cache_path is None:
        cache_path = os.path.join(
            Path(__file__).parent.parent.parent, "data", "geo_cache_seed.json"
        )

    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        # Normalize keys to lowercase for case-insensitive lookup
        _geo_cache = {k.lower(): v for k, v in raw.items()}
        logger.info("Geocoding cache loaded: %d entries from seed", len(_geo_cache))
    except FileNotFoundError:
        logger.warning("Geocoding cache file not found: %s", cache_path)
    except json.JSONDecodeError as e:
        logger.error("Invalid geocoding cache JSON: %s", e)

    # Also load previously learned entries
    try:
        with open(_LEARNED_CACHE_PATH, "r", encoding="utf-8") as f:
            learned = json.load(f)
        for k, v in learned.items():
            _geo_cache[k.lower()] = v
        logger.info("Geocoding cache loaded: %d entries from learned cache", len(learned))
    except FileNotFoundError:
        pass
    except json.JSONDecodeError as e:
        logger.warning("Invalid learned geocoding cache JSON: %s", e)


def _nominatim_lookup(location: str) -> Optional[dict]:
    """
    Fallback geocoding via Nominatim (OpenStreetMap).
    Rate-limited to 1 request per second per Nominatim policy.
    """
    global _nominatim_hits
    try:
        from geopy.geocoders import Nominatim
        from geopy.exc import GeocoderTimedOut, GeocoderServiceError

        geolocator = Nominatim(user_agent="sentinel-osint-dashboard", timeout=5)
        time.sleep(1.1)  # Respect Nominatim rate limit

        result = geolocator.geocode(location, exactly_one=True, language="en")
        if result:
            _nominatim_hits += 1
            entry = {
                "lat": result.latitude,
                "lon": result.longitude,
                "country_code": None,  # Nominatim doesn't always give this simply
            }
            # Cache the result for future lookups
            _geo_cache[location.lower()] = entry
            # Record for persistence
            _learned_entries[location.lower()] = entry
            logger.debug("Nominatim resolved '%s' → (%s, %s)", location, result.latitude, result.longitude)
            return entry
        else:
            logger.debug("Nominatim could not resolve: '%s'", location)
            # Cache the miss to avoid repeated lookups
            _geo_cache[location.lower()] = None
            return None

    except (GeocoderTimedOut, GeocoderServiceError) as e:
        logger.warning("Nominatim error for '%s': %s", location, e)
        return None
    except Exception as e:
        logger.warning("Unexpected geocoding error for '%s': %s", location, e)
        return None


def geocode(location: str) -> Optional[Tuple[float, float, Optional[str]]]:
    """
    Resolve a location name to (lat, lon, country_code).

    Checks pre-seeded cache first, falls back to Nominatim.
    Returns None if the location cannot be resolved.
    """
    global _cache_hits

    if not location or not location.strip():
        return None

    key = location.strip().lower()

    # Check cache first
    if key in _geo_cache:
        entry = _geo_cache[key]
        if entry is None:
            return None  # Previously failed lookup
        _cache_hits += 1
        return (entry["lat"], entry["lon"], entry.get("country_code"))

    # Fallback to Nominatim
    entry = _nominatim_lookup(location.strip())
    if entry:
        return (entry["lat"], entry["lon"], entry.get("country_code"))

    return None


def geocode_entities(entities: list) -> Optional[Tuple[float, float, Optional[str]]]:
    """
    Try to geocode a list of entity names, returning the first successful result.

    Prioritizes entities that are likely to be more specific (longer names first).
    """
    if not entities:
        return None

    # Sort by length descending — more specific names tend to be longer
    sorted_entities = sorted(entities, key=len, reverse=True)

    for entity in sorted_entities:
        result = geocode(entity)
        if result:
            return result

    return None


def get_stats() -> dict:
    """Return cache statistics."""
    return {
        "cache_size": len(_geo_cache),
        "cache_hits": _cache_hits,
        "nominatim_hits": _nominatim_hits,
    }


# Load cache on module import
load_cache()
