"""
Backfill historical GDELT conflict events directly into Cassandra.

GDELT V2 publishes 15-minute event exports as .zip CSVs at
http://data.gdeltproject.org/gdeltv2/YYYYMMDDHHMMSS.export.CSV.zip. This
script walks a date range, downloads each 15-minute file, filters for the
same conflict criteria the live producer uses (CAMEO 18/19 or Goldstein
< -5), classifies and scores severity inline, and writes straight to
Cassandra — bypassing Kafka and the consumer's freshness filter.

Usage:
    python -m scripts.backfill_gdelt --start 2026-04-01 --end 2026-04-22
    python -m scripts.backfill_gdelt --days 30
    python -m scripts.backfill_gdelt --start 2020-01-01 --end 2020-12-31 --workers 8

Re-running is idempotent: event IDs are derived from GDELT's GLOBALEVENTID
via uuid5, so the same event always produces the same primary key.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import io
import logging
import sys
import time
import urllib.error
import urllib.request
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

from ingestion.gdelt_producer import (
    _COL_ACTION_GEO_COUNTRY_CODE,
    _COL_ACTION_GEO_LAT,
    _COL_ACTION_GEO_LONG,
    _COL_ACTOR1_NAME,
    _COL_ACTOR2_NAME,
    _COL_EVENT_CODE,
    _COL_GOLDSTEIN_SCALE,
    _COL_SOURCE_URL,
    _is_conflict_event,
    _safe_float,
)
from processing.nlp.classifier import classify_cameo
from processing.sink import CassandraSink, get_region, get_time_bucket

logger = logging.getLogger("backfill_gdelt")

# GDELT GLOBALEVENTID is column 0; DATEADDED is column 59 (YYYYMMDDHHMMSS).
_COL_GLOBAL_EVENT_ID = 0
_COL_DATEADDED = 59

GDELT_BASE = "http://data.gdeltproject.org/gdeltv2"
UUID_NAMESPACE = uuid.UUID("5e4d8b1a-6c9f-4e3a-9d2b-0f7a1c3e5b8d")


def _parse_dateadded(raw: str) -> Optional[datetime]:
    """Parse GDELT's DATEADDED field (YYYYMMDDHHMMSS) to a UTC datetime."""
    try:
        return datetime.strptime(raw.strip(), "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
    except (ValueError, AttributeError):
        return None


def _fifteen_min_stamps(start: datetime, end: datetime) -> Iterable[str]:
    """Yield GDELT filename stamps ('YYYYMMDDHHMMSS') at 15-min intervals."""
    t = start.replace(minute=(start.minute // 15) * 15, second=0, microsecond=0)
    while t <= end:
        yield t.strftime("%Y%m%d%H%M%S")
        t += timedelta(minutes=15)


def _download_csv(stamp: str, timeout: int = 60) -> Optional[str]:
    """Download a single GDELT 15-min export and return decoded CSV text."""
    url = f"{GDELT_BASE}/{stamp}.export.CSV.zip"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Sentinel-Backfill/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            # Pre-2015 data, maintenance gaps, or files that never existed.
            return None
        logger.warning("[%s] HTTP %s", stamp, e.code)
        return None
    except Exception as e:
        logger.warning("[%s] download failed: %s", stamp, e)
        return None

    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            names = zf.namelist()
            if not names:
                return None
            return zf.read(names[0]).decode("utf-8", errors="replace")
    except zipfile.BadZipFile:
        # Very early V2 exports were gzipped
        try:
            return gzip.decompress(raw).decode("utf-8", errors="replace")
        except Exception as e:
            logger.warning("[%s] decompress failed: %s", stamp, e)
            return None


def _compute_severity(event_type: str, goldstein: Optional[float]) -> int:
    """Mirrors consumer._compute_severity for GDELT events."""
    severity = 5
    if goldstein is not None:
        if goldstein < -8:
            severity = 9
        elif goldstein < -5:
            severity = 7
        elif goldstein < -2:
            severity = 6
        else:
            severity = 4
    if event_type == "terrorism":
        severity = min(severity + 2, 10)
    elif event_type == "conflict":
        severity = min(severity + 1, 10)
    return max(1, min(10, severity))


def _build_event(row: list, stamp: str) -> Optional[dict]:
    """Transform one GDELT row into a fully enriched event dict, or None to skip."""
    if len(row) <= _COL_SOURCE_URL:
        return None

    event_code = row[_COL_EVENT_CODE]
    goldstein = _safe_float(row[_COL_GOLDSTEIN_SCALE])
    if not _is_conflict_event(event_code, goldstein):
        return None

    lat = _safe_float(row[_COL_ACTION_GEO_LAT])
    lon = _safe_float(row[_COL_ACTION_GEO_LONG])
    if lat is None or lon is None:
        return None

    global_event_id = row[_COL_GLOBAL_EVENT_ID].strip()
    if not global_event_id:
        return None

    event_time = _parse_dateadded(row[_COL_DATEADDED]) or _parse_dateadded(stamp)
    if event_time is None:
        return None

    country_code = row[_COL_ACTION_GEO_COUNTRY_CODE].strip() or None
    source_url = row[_COL_SOURCE_URL].strip() or None
    actor1 = row[_COL_ACTOR1_NAME].strip() or None
    actor2 = row[_COL_ACTOR2_NAME].strip() or None

    actors = " vs ".join(filter(None, [actor1, actor2]))
    raw_text = f"CAMEO {event_code}"
    if actors:
        raw_text = f"{actors} — {raw_text}"
    if goldstein is not None:
        raw_text += f" (Goldstein {goldstein:+.1f})"

    event_type, confidence = classify_cameo(event_code)
    severity = _compute_severity(event_type, goldstein)
    event_id = uuid.uuid5(UUID_NAMESPACE, f"gdelt:{global_event_id}")

    return {
        "event_id": str(event_id),
        "source": "gdelt",
        "event_type": event_type,
        "confidence": confidence,
        "severity": severity,
        "title": None,
        "raw_text": raw_text,
        "timestamp": event_time.isoformat(),
        "source_url": source_url,
        "geo": {
            "lat": lat,
            "lon": lon,
            "country_code": country_code,
            "location_name": None,
        },
        "_region": get_region(country_code),
        "_time_bucket": get_time_bucket(event_time.isoformat()),
    }


def _process_stamp(stamp: str) -> list:
    """Download + parse one 15-min file, return list of enriched events."""
    text = _download_csv(stamp)
    if not text:
        return []

    events = []
    reader = csv.reader(io.StringIO(text), delimiter="\t")
    for row in reader:
        ev = _build_event(row, stamp)
        if ev:
            events.append(ev)
    return events


def run_backfill(start: datetime, end: datetime, workers: int = 4) -> dict:
    stamps = list(_fifteen_min_stamps(start, end))
    total_files = len(stamps)
    logger.info("Backfilling %d 15-min files from %s to %s (workers=%d)",
                total_files, start.isoformat(), end.isoformat(), workers)

    sink = CassandraSink()
    sink.connect()

    written = 0
    files_processed = 0
    files_empty = 0
    t0 = time.time()

    def _dispatch_writes(events: list) -> None:
        nonlocal written
        for ev in events:
            if sink.write(ev):
                written += 1

    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(_process_stamp, s): s for s in stamps}
            for fut in as_completed(futures):
                stamp = futures[fut]
                try:
                    events = fut.result()
                except Exception as e:
                    logger.warning("[%s] processing error: %s", stamp, e)
                    events = []

                files_processed += 1
                if not events:
                    files_empty += 1
                _dispatch_writes(events)

                if files_processed % 50 == 0 or files_processed == total_files:
                    elapsed = time.time() - t0
                    rate = files_processed / elapsed if elapsed > 0 else 0
                    eta_s = (total_files - files_processed) / rate if rate > 0 else 0
                    logger.info(
                        "Progress: %d/%d files (%.1f/s), written=%d events, empty=%d, ETA=%.0fm",
                        files_processed, total_files, rate, written, files_empty, eta_s / 60,
                    )
    finally:
        sink.close()

    elapsed = time.time() - t0
    logger.info("Backfill complete: %d events written from %d files in %.1fs",
                written, files_processed, elapsed)
    return {
        "files_processed": files_processed,
        "files_empty": files_empty,
        "events_written": written,
        "elapsed_seconds": elapsed,
    }


def _parse_date(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def main():
    parser = argparse.ArgumentParser(description="Backfill GDELT conflict events into Cassandra.")
    grp = parser.add_mutually_exclusive_group(required=True)
    grp.add_argument("--days", type=int, help="Backfill the last N days from now.")
    grp.add_argument("--start", type=_parse_date, help="Start date (YYYY-MM-DD, UTC).")
    parser.add_argument("--end", type=_parse_date, help="End date (YYYY-MM-DD, UTC). Default: now.")
    parser.add_argument("--workers", type=int, default=4, help="Parallel download workers (default 4).")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    end = args.end or datetime.now(timezone.utc)
    if args.days is not None:
        start = end - timedelta(days=args.days)
    else:
        start = args.start

    if start >= end:
        logger.error("start (%s) must be before end (%s)", start, end)
        sys.exit(1)

    run_backfill(start, end, workers=args.workers)


if __name__ == "__main__":
    main()
