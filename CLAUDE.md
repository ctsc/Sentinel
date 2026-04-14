# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## Quick Reference — Development Commands

### Infrastructure (Docker)
```bash
docker-compose up -d                  # Start Kafka + Zookeeper + Cassandra
docker-compose ps                     # Check container health
docker exec -it sentinel-cassandra cqlsh -f /docker-entrypoint-initdb.d/init.cql  # Init Cassandra schema
docker-compose down                   # Stop all containers
```

### Backend (Python 3.11 or 3.12 (NOT 3.13+ — spaCy 3.7 has no wheels for newer versions))
```bash
pip install -r requirements.txt       # Install dependencies
python -m spacy download en_core_web_lg  # Download spaCy model (required for NER)

# Run individual producers
python -m ingestion.gdelt_producer
python -m ingestion.acled_producer    # Requires ACLED_EMAIL + ACLED_PASSWORD in .env (OAuth)
python -m ingestion.rss_producer
python -m ingestion.bluesky_producer
python -m ingestion.wikipedia_producer

# Run NLP consumer (processes all Kafka topics)
python -m processing.consumer

# Run API server
uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
```

### Frontend (Node/TypeScript)
```bash
cd frontend
npm install                           # Install dependencies
npm run dev                           # Vite dev server with HMR
npm run build                         # TypeScript check + production build
npm run lint                          # ESLint
npm run preview                       # Preview production build
```

### Tests
```bash
# All tests require Docker containers running (Kafka + Cassandra)
pytest tests/test_phase1_infra.py -v        # Infrastructure connectivity
pytest tests/test_producers.py -v           # Producer schema validation
pytest tests/test_schema_consistency.py -v  # Cross-source schema consistency
pytest tests/test_nlp.py -v                 # NER, geocoder, classifier units
pytest tests/test_dedup.py -v               # Deduplication logic
pytest tests/test_pipeline_e2e.py -v        # Full pipeline integration
pytest tests/test_api.py -v                 # REST + WebSocket endpoints
pytest tests/ -v                            # Run all tests
```

### Environment Variables
Copy `.env.example` to `.env` and fill in:
- `ACLED_EMAIL` + `ACLED_PASSWORD` — required for ACLED producer (OAuth against myACLED account; register at acleddata.com/user/register)
- `MAPBOX_TOKEN` — required for frontend map tiles (get from mapbox.com)
- Kafka/Cassandra defaults work with docker-compose (localhost:9092 / localhost:9042)

---

# SENTINEL — Real-Time Global Conflict & News Intelligence Dashboard

> GSU CSC 6311 | Solo Project | Carter Loftus | Spring 2026

## Project Overview

Sentinel is an open-source OSINT intelligence dashboard that ingests 5+ live public data sources, classifies and geolocates every event using local NLP in-stream, and renders them on a live interactive map — no editorial filtering, no hallucinated data, everything sourced from real feeds.

**Core priorities (in order):**
1. Clean, working end-to-end pipeline with minimal errors
2. Beautiful low-latency flat map frontend (dark theme, Deck.gl on Mapbox)
3. All data sourced from real live feeds — nothing fabricated
4. Benchmarkable architecture for the research paper

---

## Architecture (Lambda Pattern)

```
INGEST (Kafka) → PROCESS (NLP service) → STORE (Cassandra + S3) → VISUALIZE (Deck.gl + React)
```

### Key Tech Decisions

| Layer | Tech | Why |
|-------|------|-----|
| Message broker | Apache Kafka (single broker local, 3-broker prod) | Decouples 5+ producers, offset replay for fault recovery |
| Stream processing | Python Kafka consumer (dev) → PyFlink (prod/benchmark) | See "Two-stage processing strategy" below |
| NLP - NER | spaCy `en_core_web_lg` (unstructured sources ONLY) | Only for RSS, Bluesky, Wikipedia. GDELT/ACLED already have lat/lon — skip NER for them |
| NLP - Classification | Keyword/rule-based classifier | GDELT has CAMEO codes, ACLED has event_type. Only RSS/Bluesky/Wikipedia need classification — keyword matcher does it in <1ms, zero torch dependency |
| Geocoding | geopy + Nominatim + pre-seeded LRU cache | Only for unstructured sources. GDELT/ACLED coords pass through directly. Cache pre-seeded with ~500 conflict locations |
| Speed layer | Cassandra on EC2 (NOT Keyspaces — see below) | Tunable consistency for CAP research |
| Batch layer | S3 JSON → Parquet via Glue | Raw JSON archive, nightly conversion |
| Frontend | Deck.gl v9 + React + Mapbox (flat MapView) | GPU-accelerated, 100K+ points at 60fps. Flat map, NOT globe |
| API | FastAPI (REST + WebSocket) | Historical queries + live stream |
| CDN | CloudFront | Static frontend delivery |

### Two-Stage Processing Strategy (KEY DE-RISK)

**Problem:** PyFlink on Windows is painful. PyFlink's JVM↔Python bridge adds complexity. If Flink breaks, the whole pipeline is dead.

**Solution:** Build NLP processing as a plain Python Kafka consumer service FIRST. It does the same thing — reads from Kafka, runs spaCy + distilBERT, writes to Cassandra + S3 — but without any Flink dependency. This works on Windows, is easy to debug, and gets the pipeline running immediately.

Then in Phase 5 (production), wrap the same NLP logic inside a Flink job for the benchmark. The NLP code is identical — only the orchestration changes.

**Why this works:**
- Dev/testing uses simple Python consumer → works everywhere, easy to debug
- Production/benchmark uses Flink → satisfies the proposal, enables proper stream processing metrics
- If Flink causes problems, the Python consumer is the fallback and the system still works
- The NLP code (`ner.py`, `classifier.py`, `geocoder.py`) is shared between both paths

### CRITICAL: Cassandra vs Keyspaces

**AWS Keyspaces does NOT support tunable consistency.** Only LOCAL_QUORUM. The CAP theorem research (ONE vs QUORUM under write pressure) is impossible on Keyspaces.

**Decision: Run real Cassandra on EC2** (single-node dev, 3-node benchmark). Docker Compose locally for dev.

### Flat Map, NOT Globe

Deck.gl's `HeatmapLayer` does NOT work on `GlobeView` — only on flat `MapView`. Since heatmap is a core visual, we use flat MapView with Mapbox dark style. This is also faster, simpler, and looks cleaner for a dashboard.

---

## Data Sources — Integration Details

### Tier 1 — Must Have (5 sources)

#### 1. GDELT Project (Structured)
- **Endpoint:** `http://data.gdeltproject.org/gdeltv2/lastupdate.txt` → links to 15-min CSV exports
- **API:** `https://api.gdeltproject.org/api/v2/doc/doc?query=...&format=json`
- **Update frequency:** Every 15 minutes
- **Key fields:** `ActionGeo_Lat`, `ActionGeo_Long`, `ActionGeo_CountryCode`, `EventCode` (CAMEO — 18x/19x = conflict), `GoldsteinScale` (negative = conflict)
- **Auth:** None. Soft rate limit ~1 req/sec
- **Kafka topic:** `sentinel.raw.gdelt`

#### 2. ACLED (Structured)
- **Endpoint:** `https://acleddata.com/acled/read`
- **Auth:** OAuth bearer token. POST email + password to `https://acleddata.com/oauth/token` → access token (24h) + refresh token (14d). Register a myACLED account at acleddata.com/user/register.
- **Key fields:** `latitude`, `longitude`, `country`, `event_type`, `fatalities`, `event_date`, `actor1`, `actor2`, `source`
- **Rate limit:** ~500 requests/day, paginate with `page=N` (5000 rows/page)
- **Kafka topic:** `sentinel.raw.acled`

#### 3. RSS Feeds (Unstructured text)
- **BBC World:** `https://feeds.bbci.co.uk/news/world/rss.xml` (stable)
- **Al Jazeera:** `https://www.aljazeera.com/xml/rss/all.xml` (stable)
- **Reuters/AP:** Both deprecated direct RSS. Use Google News RSS as fallback: `https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGx1YlY4U0FtVnVHZ0pWVXigAQ`
- **Poll interval:** Every 60 seconds
- **Kafka topic:** `sentinel.raw.rss`

#### 4. Bluesky Firehose (Unstructured text)
- **Endpoint:** `wss://bsky.network/xrpc/com.atproto.sync.subscribeRepos`
- **Library:** `atproto` Python package
- **Auth:** None required
- **IMPORTANT:** Firehose is VERY high volume. Must keyword-filter aggressively (conflict/war/protest/attack/etc) and rate-limit to max ~100 events/min to avoid flooding Kafka
- **Kafka topic:** `sentinel.raw.bluesky`

#### 5. Wikipedia Recent Changes (Signal)
- **Endpoint:** `https://stream.wikimedia.org/v2/stream/recentchange` (SSE stream)
- **Library:** `sseclient-py` or `aiohttp`
- **Auth:** None
- **Filter:** `wiki == "enwiki"`, match `title` against conflict keyword list
- **Kafka topic:** `sentinel.raw.wikipedia`

### Tier 2 — Optional (add if time permits)

#### 6. Telegram Channels (Unstructured text)
- **Requires:** Personal Telegram account with phone number + API credentials from my.telegram.org
- **Library:** `telethon`
- **Channels:** Public OSINT/conflict monitors
- **Kafka topic:** `sentinel.raw.telegram`
- **Skip if:** You don't want to use a personal phone number or don't have Telegram

---

## Kafka Topic Schema (Unified)

All producers normalize to this before publishing:

```json
{
  "event_id": "uuid",
  "source": "gdelt|acled|rss|bluesky|wikipedia|telegram",
  "raw_text": "string",
  "title": "string|null",
  "timestamp": "ISO8601",
  "source_url": "string|null",
  "geo": {
    "lat": "float|null",
    "lon": "float|null",
    "country_code": "string|null",
    "location_name": "string|null"
  },
  "metadata": {}
}
```

After NLP processing, events gain:

```json
{
  "event_type": "conflict|protest|disaster|political|terrorism|other",
  "confidence": 0.0-1.0,
  "entities": ["string"],
  "severity": 1-10,
  "dedupe_hash": "string"
}
```

---

## Cassandra Schema

```sql
CREATE KEYSPACE sentinel WITH replication = {
  'class': 'SimpleStrategy', 'replication_factor': 1
};
-- SimpleStrategy for single-node dev. Switch to NetworkTopologyStrategy for 3-node benchmark.

CREATE TABLE sentinel.events (
    region text,
    time_bucket text,         -- hourly: '2026-04-03T14'
    event_time timestamp,
    event_id uuid,
    source text,
    event_type text,
    title text,
    raw_text text,
    lat double,
    lon double,
    country_code text,
    location_name text,
    confidence double,
    severity int,
    source_url text,
    PRIMARY KEY ((region, time_bucket), event_time, event_id)
) WITH CLUSTERING ORDER BY (event_time DESC);
```

---

## Project Structure

```
sentinel/
├── CLAUDE.md
├── docker-compose.yml          # Local dev: Kafka + Zookeeper + Cassandra
├── infrastructure/
│   ├── docker/
│   │   ├── Dockerfile.processor  # Python NLP processor
│   │   ├── Dockerfile.flink      # PyFlink wrapper (Phase 5)
│   │   ├── Dockerfile.api        # FastAPI
│   │   └── Dockerfile.frontend   # React build
│   ├── cassandra/
│   │   └── init.cql              # Keyspace + table creation
│   └── aws/
│       └── cloudformation.yml    # EC2 + ECS + S3 + CloudFront (Phase 5)
├── ingestion/
│   ├── __init__.py
│   ├── base_producer.py          # Abstract Kafka producer with schema normalization
│   ├── gdelt_producer.py
│   ├── acled_producer.py
│   ├── rss_producer.py
│   ├── bluesky_producer.py
│   ├── wikipedia_producer.py
│   ├── telegram_producer.py      # Optional (Tier 2)
│   └── config.py                 # Endpoints, poll intervals, keyword lists
├── processing/
│   ├── __init__.py
│   ├── consumer.py               # Plain Python Kafka consumer (dev path)
│   ├── flink_job.py              # PyFlink wrapper (prod path, Phase 5)
│   ├── nlp/
│   │   ├── __init__.py
│   │   ├── ner.py                # spaCy NER → GPE/LOC extraction
│   │   ├── classifier.py         # distilBERT event classification
│   │   └── geocoder.py           # Entity → lat/lon with pre-seeded LRU cache
│   ├── dedup.py                  # Hash-based deduplication
│   └── sink.py                   # Write to Cassandra + S3
├── api/
│   ├── __init__.py
│   ├── main.py                   # FastAPI app
│   ├── routes/
│   │   ├── events.py             # GET /events — historical queries
│   │   └── ws.py                 # WebSocket /ws/live — live feed
│   ├── db.py                     # Cassandra connection
│   └── models.py                 # Pydantic schemas
├── frontend/
│   ├── package.json
│   ├── src/
│   │   ├── App.tsx
│   │   ├── components/
│   │   │   ├── MapView.tsx       # Deck.gl flat map + Mapbox dark style
│   │   │   ├── EventPanel.tsx    # Side panel — event details + source link
│   │   │   ├── FilterBar.tsx     # Country/type/time filters
│   │   │   └── StatsBar.tsx      # Live event count, sources active, latency
│   │   ├── hooks/
│   │   │   ├── useWebSocket.ts   # Live event stream (batched at ~1/sec)
│   │   │   └── useEvents.ts      # REST query hook
│   │   ├── layers/
│   │   │   ├── heatmap.ts        # HeatmapLayer config
│   │   │   ├── scatter.ts        # ScatterplotLayer config
│   │   │   └── arcs.ts           # ArcLayer config (optional)
│   │   └── utils/
│   │       └── types.ts          # TypeScript event types
│   └── public/
├── benchmark/
│   ├── load_generator.py         # Synthetic events at N× throughput
│   ├── latency_tracker.py        # End-to-end latency measurement
│   ├── cap_test.py               # ONE vs QUORUM consistency tests
│   └── results/
├── data/
│   └── geo_cache_seed.json       # Pre-seeded geocoding cache (~500 common conflict locations)
├── tests/
│   ├── test_phase1_infra.py      # Phase 1: Kafka + Cassandra connectivity
│   ├── test_producers.py         # Phase 2: each producer schema + output
│   ├── test_schema_consistency.py # Phase 2: all sources produce same schema
│   ├── test_nlp.py               # Phase 3: NER, geocoder, classifier unit tests
│   ├── test_dedup.py             # Phase 3: deduplication logic
│   ├── test_pipeline_e2e.py      # Phase 3: full pipeline integration test
│   └── test_api.py               # Phase 4: REST + WebSocket endpoints
├── requirements.txt
└── .env.example                  # Template for API keys (ACLED, Mapbox, etc.)
```

---

## Build Phases (6 total)

**RULE: No phase is complete until ALL its tests pass.** Each phase has a test gate — a set of automated and manual tests that must succeed before moving to the next phase. If tests fail, fix the issue in that phase. Never build on a broken foundation.

---

### PHASE 1 — Local Infrastructure + Project Scaffold
**Goal: Docker Compose stack running. Python + React projects scaffolded. Can produce/consume Kafka and read/write Cassandra.**

- [ ] `docker-compose.yml` — Kafka (single broker) + Zookeeper + Cassandra (single node)
- [ ] `infrastructure/cassandra/init.cql` — keyspace + events table
- [ ] Python project: `requirements.txt`, package structure, `config.py`
- [ ] React project: Vite + TypeScript scaffold with Deck.gl + react-map-gl installed
- [ ] `.env.example` with placeholder keys

**TEST GATE — Phase 1 (all must pass):**
- [ ] `docker-compose up` → all containers reach healthy status within 60 seconds
- [ ] `tests/test_phase1_infra.py` — automated:
  - Kafka broker accepts connections on localhost:9092
  - Can create a topic, produce a message, consume it back, verify content matches
  - Cassandra accepts connections on localhost:9042
  - Can create keyspace + table via init.cql
  - Can INSERT a sample event row, SELECT it back, verify all fields match
  - Can DELETE the sample row (cleanup)
- [ ] Frontend: `npm run dev` starts without errors, page loads in browser
- [ ] Frontend: `npm run build` completes with zero errors and zero warnings

**Exit criteria:** All test gate checks pass. No manual verification needed — tests prove it works.

**No MinIO in Phase 1.** S3 writes are Phase 5 — local dev doesn't need object storage yet.

---

### PHASE 2 — Data Ingestion (5 producers)
**Goal: All 5 core sources producing normalized events to Kafka.**

- [ ] `base_producer.py` — abstract class: Kafka connection, schema normalization, retry logic, structured logging
- [ ] `gdelt_producer.py` — poll GDELT every 15 min, parse CSV, extract lat/lon/country/event code
- [ ] `acled_producer.py` — poll ACLED API with pagination, map fields to unified schema
- [ ] `rss_producer.py` — poll BBC + Al Jazeera + Google News fallback every 60s via `feedparser`
- [ ] `bluesky_producer.py` — WebSocket firehose → keyword filter → rate limit (max 100/min) → Kafka
- [ ] `wikipedia_producer.py` — SSE stream → filter English conflict edits → Kafka
- [ ] Keyword list in `config.py` — shared conflict/geopolitical terms for Bluesky + Wikipedia filtering
- [ ] Test each producer individually with Docker Kafka running

**TEST GATE — Phase 2 (all must pass):**
- [ ] `tests/test_producers.py` — automated, per producer:
  - Each producer connects to Kafka without error
  - Each producer outputs messages matching the unified schema (all required fields present, correct types)
  - `event_id` is a valid UUID
  - `timestamp` is valid ISO8601
  - `source` field matches expected source name
  - GDELT/ACLED: `geo.lat` and `geo.lon` are populated (not null)
  - Bluesky/Wikipedia: keyword filter is working (only conflict-relevant events pass through)
  - RSS: `source_url` is populated for every event
- [ ] `tests/test_schema_consistency.py` — automated:
  - Produce one event from each of the 5 sources
  - Consume all 5 from Kafka
  - Verify all 5 deserialize to the same schema without errors
- [ ] Stability test (manual): run all 5 producers for 10 minutes continuously — no crashes, no memory leaks, Kafka lag stays near zero

**Exit criteria:** All automated tests pass. 10-minute stability test passes.

**Order to build:** GDELT first (simplest, structured), then ACLED, then RSS, then Wikipedia, then Bluesky (hardest, highest volume).

---

### PHASE 3 — NLP Pipeline (Python consumer path)
**Goal: Events flow from Kafka → NLP → Cassandra. End-to-end pipeline works.**

- [ ] `nlp/ner.py` — spaCy `en_core_web_lg` extracts GPE/LOC entities. **Only runs on unstructured sources** (RSS, Bluesky, Wikipedia). GDELT/ACLED already have coordinates — pass them through directly.
- [ ] `nlp/geocoder.py` — entity name → lat/lon. Pre-seeded LRU cache from `geo_cache_seed.json` (~500 locations). Falls back to Nominatim for cache misses. **Only called for unstructured sources.**
- [ ] `nlp/classifier.py` — **keyword/rule-based classifier**, NOT distilBERT. Maps text to: conflict, protest, disaster, political, terrorism, other. GDELT uses CAMEO codes (already classified). ACLED uses `event_type` (already classified). Only RSS/Bluesky/Wikipedia need keyword matching. <1ms per event, zero ML dependencies.
- [ ] `dedup.py` — hash(title + source + 1-hour time window) deduplication
- [ ] `sink.py` — write enriched events to Cassandra
- [ ] `consumer.py` — plain Python Kafka consumer that ties it all together: read from all topics → route structured sources (GDELT/ACLED) through passthrough path, unstructured sources (RSS/Bluesky/Wikipedia) through NER → geocode → classify → all through dedup → sink
- [ ] `data/geo_cache_seed.json` — pre-built with common locations (Kyiv, Gaza, Khartoum, Taipei, etc.)
- [ ] Test NLP components individually with sample texts
- [ ] Test full pipeline: producer → Kafka → consumer → Cassandra → query back

**TEST GATE — Phase 3 (all must pass):**
- [ ] `tests/test_nlp.py` — automated, unit tests:
  - NER extracts known locations from sample texts (e.g., "explosion in Kyiv" → entity "Kyiv")
  - NER returns empty list for texts with no locations
  - Geocoder resolves "Kyiv" → lat/lon within expected range (50.4, 30.5 ± 1°)
  - Geocoder cache hit: second call for same entity does NOT hit Nominatim
  - Classifier maps "soldiers attacked a village" → "conflict"
  - Classifier maps "thousands marched in protest" → "protest"
  - Classifier maps "earthquake struck the coast" → "disaster"
  - Classifier returns "other" for unrelated text
- [ ] `tests/test_dedup.py` — automated:
  - Duplicate event (same title + source + within 1hr) is rejected
  - Similar event with different source is NOT rejected
  - Event outside time window is NOT rejected
- [ ] `tests/test_pipeline_e2e.py` — automated, integration:
  - Produce a sample GDELT event → consumer picks it up → lands in Cassandra with correct fields (passthrough path)
  - Produce a sample RSS event → consumer picks it up → NER + geocode + classify → lands in Cassandra with enriched fields
  - Query Cassandra by region + time_bucket → returns the inserted events
  - Dedup works end-to-end: produce same event twice → only one row in Cassandra
- [ ] Stability test (manual): run full pipeline (all 5 producers + consumer) for 30 minutes — no crashes, events accumulating in Cassandra, geocoding cache hit rate > 50%

**Exit criteria:** All automated tests pass. 30-minute stability test passes.

**Two processing paths in consumer.py:**
- **Structured sources (GDELT, ACLED):** Already have lat/lon + event type. Skip NER and classification. Just normalize fields, dedup, and sink. Near-zero processing cost.
- **Unstructured sources (RSS, Bluesky, Wikipedia):** Run spaCy NER → geocoder → keyword classifier → dedup → sink.

---

### PHASE 4 — Frontend + API
**Goal: Beautiful dark-theme map showing live events. Filter by country/type. Click for details.**

**API (FastAPI):**
- [ ] `db.py` — Cassandra connection pool (sync driver wrapped with `asyncio.to_thread`)
- [ ] `models.py` — Pydantic models for event schema
- [ ] `routes/events.py` — `GET /events?region=X&start=X&end=X&type=X` with pagination
- [ ] `routes/ws.py` — WebSocket `/ws/live` — Kafka consumer fans out to connected clients via asyncio.Queue per client
- [ ] `main.py` — CORS, health check, mount routes
- [ ] Test API with curl / Postman against live Cassandra data

**Frontend (React + Deck.gl):**
- [ ] `MapView.tsx` — Deck.gl flat map with Mapbox `dark-v11` style
- [ ] `layers/heatmap.ts` — HeatmapLayer weighted by severity (red = hot zones)
- [ ] `layers/scatter.ts` — ScatterplotLayer color-coded by event type (conflict=red, protest=yellow, disaster=orange, political=blue, terrorism=purple)
- [ ] `hooks/useWebSocket.ts` — connect to `/ws/live`, batch incoming events into 1-second windows before state update (critical for performance)
- [ ] `hooks/useEvents.ts` — REST hook for loading historical data on map pan/zoom
- [ ] `FilterBar.tsx` — dropdown for country, toggles for event types, time range
- [ ] `EventPanel.tsx` — click a scatter point → slide-in panel with title, source, text, confidence, source link
- [ ] `StatsBar.tsx` — bottom bar showing: events/min, sources active, avg latency
- [ ] Dark theme styling — dark background (#0a0a1a), cyan/green/orange accents matching proposal

**TEST GATE — Phase 4 (all must pass):**
- [ ] `tests/test_api.py` — automated:
  - `GET /health` returns 200
  - `GET /events?region=middle_east&time_bucket=2026-04-03T14` returns valid JSON array
  - Response matches Pydantic event schema (all fields, correct types)
  - Empty query returns empty array (not error)
  - WebSocket `/ws/live` connects successfully and receives events within 5 seconds (with producers + consumer running)
  - CORS headers present in response
- [ ] Frontend build: `npm run build` — zero errors, zero warnings
- [ ] Frontend lint: `npx tsc --noEmit` — zero type errors
- [ ] Manual visual tests (with full pipeline running):
  - Map loads with dark Mapbox style, no tile errors
  - Heatmap layer renders — visible red/orange zones where events cluster
  - Scatter points appear and are color-coded by event type
  - Click a scatter point → EventPanel slides in with title, source, type, confidence, source URL link
  - FilterBar: select a country → map filters to only that country's events
  - FilterBar: toggle event type off → those points disappear from map
  - StatsBar: shows events/min updating in real-time
  - No visible lag or jank with 1K+ points on screen

**Exit criteria:** All automated tests pass. All manual visual tests pass. System looks professional.

**Deck.gl rules:**
- Always create NEW array reference on data update (`[...prev, ...newBatch]`)
- Batch WebSocket messages — never setState per individual message
- Limit visible points to latest ~10K to keep GPU happy. Older points fade or are removed.

---

### PHASE 5 — Production Hardening + AWS Deploy
**Goal: System running on AWS. Flink wrapper working. S3 archive flowing.**

- [ ] Wrap NLP pipeline in PyFlink job (`flink_job.py`) — same NLP code, Flink orchestration
- [ ] `Dockerfile.flink` with PyFlink + models pre-baked
- [ ] `Dockerfile.processor` (fallback Python consumer)
- [ ] `Dockerfile.api` for FastAPI
- [ ] Build frontend → static files for S3
- [ ] Deploy: Kafka on EC2 (3× t3.medium), Cassandra on EC2 (1 node), Flink on ECS Fargate, API on ECS Fargate
- [ ] S3 bucket for raw JSON archive + Glue job for nightly Parquet conversion
- [ ] CloudFront for frontend + API
- [ ] End-to-end smoke test with all live sources on AWS
- [ ] Fix any data quality issues found in production

**TEST GATE — Phase 5 (all must pass):**
- [ ] All Dockerfiles build without errors
- [ ] Smoke test on AWS — each service health check returns 200:
  - Kafka brokers accepting connections
  - Cassandra accepting connections
  - FastAPI `/health` returns 200 via CloudFront URL
  - Frontend loads in browser via CloudFront URL
- [ ] End-to-end AWS test:
  - Produce an event on AWS Kafka → verify it reaches Cassandra → verify it appears on the frontend map via WebSocket
  - All 5 producers running on AWS without crashes for 10 minutes
  - S3 bucket accumulating raw JSON files
- [ ] Regression: re-run all Phase 2-4 automated tests against AWS endpoints (swap localhost for AWS URLs in test config)

**Exit criteria:** All smoke tests pass. End-to-end event flow verified on AWS. Phase 2-4 tests pass against cloud deployment.

**If Flink causes problems on ECS:** Fall back to the Python consumer in a Docker container on ECS. The system works identically — only the orchestration layer differs. Don't let Flink block the project.

---

### PHASE 6 — Benchmarking + Paper
**Goal: 5-tier load test, CAP analysis, research paper, demo-ready.**

- [ ] `load_generator.py` — synthetic event generator at 1×, 5×, 10×, 25×, 50× baseline throughput
- [ ] Scale Cassandra to 3 nodes for benchmark
- [ ] Measure per tier: end-to-end latency, NLP processing time, Cassandra write latency
- [ ] CAP experiment: switch Cassandra between ONE and QUORUM consistency — measure latency + staleness under write pressure
- [ ] Lambda divergence: compare Cassandra (live) vs S3/Parquet (batch) query results
- [ ] NLP saturation: find events/sec where spaCy+distilBERT bottleneck
- [ ] Generate graphs (matplotlib)
- [ ] Write research paper
- [ ] Prepare demo
- [ ] Tear down benchmark cluster immediately after

**TEST GATE — Phase 6 (all must pass):**
- [ ] Load generator produces events at each of the 5 tiers without crashing
- [ ] Latency data collected for all 5 tiers — no gaps or missing measurements
- [ ] CAP experiment: measurable latency difference between ONE and QUORUM consistency levels
- [ ] Graphs generated and visually correct (axes labeled, data points present, trends visible)
- [ ] Full system demo: start-to-finish walkthrough works without errors — map loads, events flow, filters work, event details show source links
- [ ] All prior phase tests still pass (full regression)

**Exit criteria:** Paper done. All 3 research questions answered with data. Demo works. Full regression passes.

---

## Environment & Dependencies

### Python (backend)
```
kafka-python
spacy
geopy
feedparser
atproto
sseclient-py
fastapi
uvicorn[standard]
websockets
cassandra-driver
boto3
pydantic
python-dotenv
```

**NOT installed:** `torch`, `transformers` — not needed. Keyword classifier replaces distilBERT.
`pyflink` added in Phase 5 only — NOT needed for dev.
`telethon` added only if Telegram source is pursued.

### Node (frontend)
```
react, react-dom
@deck.gl/core, @deck.gl/layers, @deck.gl/react
react-map-gl, mapbox-gl
typescript, vite
```

### Infrastructure (local dev)
```
Docker + Docker Compose
Kafka 3.7+ (via Docker)
Cassandra 4.x (via Docker)
```

No MinIO locally — S3 writes are production only (Phase 5).

---

## Cost Budget

| Component | Dev/Month | Benchmark (2hr) |
|-----------|-----------|-----------------|
| EC2 3× t3.medium (Kafka) | $30 | $2-3 |
| EC2 Cassandra (1→3 node) | $10-15 | $5-8 |
| ECS Fargate (Flink + API) | $15 | $8-10 |
| S3 + Glue + Athena | ~$2 | ~$1 |
| CloudFront | ~$5 | — |
| **TOTAL** | **$62-67** | **~$40** |

---

## Rules & Conventions

- **No hallucinated data.** Every event on the map traces to a real source URL.
- **No external AI APIs in the hot path.** All NLP runs locally.
- **Schema-first.** All Kafka messages follow the unified schema.
- **Cache geocoding aggressively.** Pre-seed cache. Never hit Nominatim for the same entity twice.
- **Dark theme.** #0a0a1a backgrounds, cyan/green/orange accents.
- **Fail gracefully.** One source down ≠ pipeline down.
- **Python 3.11 or 3.12 (NOT 3.13+ — spaCy 3.7 has no wheels for newer versions)** backend. **TypeScript strict** frontend.
- **Flat map only.** MapView, not GlobeView.
- **Test each phase before moving on.** Don't build on broken foundations.
- **Flink is optional for dev.** Python consumer is the reliable path. Flink wraps it for production.

---

## Known Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| PyFlink on Windows | Never run Flink natively. Docker only. Python consumer as fallback. |
| Bluesky firehose floods Kafka | Aggressive keyword filter + rate limit (100 events/min cap) |
| Geocoding cold start (empty cache) | Pre-seed `geo_cache_seed.json` with ~500 common locations |
| Reuters/AP RSS deprecated | Google News RSS as fallback. BBC + Al Jazeera are stable. |
| Telegram needs personal account | Telegram is Tier 2 / optional. Skip if no account. |
| Deck.gl HeatmapLayer + GlobeView | Not using GlobeView. Flat MapView — HeatmapLayer works natively. |

### Eliminated Risks (via plan simplification)
- **torch/transformers 2GB install** — eliminated. Keyword classifier has zero ML dependencies.
- **distilBERT latency bottleneck** — eliminated. Keyword classifier runs in <1ms.
- **spaCy NER on all events** — eliminated for structured sources. GDELT/ACLED already have coords, skip NER entirely for them.
