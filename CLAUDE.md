# CLAUDE.md

> GSU CSC 6311 | Solo Project | Carter Loftus | Spring 2026

## Quick Reference — Dev Commands

```bash
# Infrastructure
docker-compose up -d                  # Kafka + Zookeeper + Cassandra
docker exec -it sentinel-cassandra cqlsh -f /docker-entrypoint-initdb.d/init.cql

# Backend (Python 3.11 or 3.12 ONLY — spaCy 3.7 has no 3.13+ wheels)
pip install -r requirements.txt
python -m spacy download en_core_web_lg

# Run everything (after unified runner is built — see FINISH PLAN Step 1)
python run_all.py                     # Starts all producers + consumer + API in one process

# Or run individually (current approach — each needs its own terminal)
python -m ingestion.gdelt_producer
python -m ingestion.acled_producer    # Needs ACLED_EMAIL + ACLED_PASSWORD in .env
python -m ingestion.rss_producer
python -m ingestion.bluesky_producer
python -m ingestion.wikipedia_producer
python -m processing.consumer
uvicorn api.main:app --reload --host 0.0.0.0 --port 8000

# Frontend
cd frontend && npm install && npm run dev
npm run build                         # Production build

# Tests (need Docker running)
pytest tests/ -v
```

### Environment Variables (.env)
- `ACLED_EMAIL` + `ACLED_PASSWORD` — ACLED OAuth (register at acleddata.com)
- `MAPBOX_TOKEN` / `VITE_MAPBOX_TOKEN` — Mapbox map tiles
- `KAFKA_BOOTSTRAP_SERVERS` — default localhost:9092
- `CASSANDRA_HOSTS` — default localhost

---

## What Sentinel Is

Real-time OSINT dashboard: 5 live public data sources -> Kafka -> NLP processing -> Cassandra -> Deck.gl map. No fabricated data, no external AI APIs, everything sourced from real feeds.

```
PRODUCERS (5 sources) -> KAFKA -> CONSUMER (spaCy NER + geocoder + classifier) -> CASSANDRA -> API (FastAPI) -> FRONTEND (Deck.gl + React)
```

## Current State (as of 2026-04-19)

**Phases 1-4: COMPLETE** — Infrastructure, ingestion, NLP pipeline, API, and frontend all work locally.

**What works:**
- All 5 producers (GDELT, ACLED, RSS, Bluesky, Wikipedia) produce to Kafka
- Consumer processes events through NER/geocoding/classification and sinks to Cassandra
- Consumer republishes enriched events to `sentinel.enriched` topic for WebSocket
- FastAPI serves REST (`GET /events`) + WebSocket (`/ws/live`)
- Frontend renders scatter + heatmap layers on dark Mapbox map
- Filter by event type, source, location search, sort order

**What's broken/annoying:**
- Each producer + consumer + API needs its own terminal (7 terminals to run everything)
- Bluesky producer has a thread leak on error (daemon thread not cleaned up)
- WebSocket Kafka consumer thread has no restart-on-crash logic
- Geocoding cache is in-memory only — cache misses not persisted across restarts
- Consumer drops events too aggressively (year-based freshness filter, `_OLD_YEAR_RE`)
- Consumer `_is_fresh()` rejects any RSS/Wikipedia text mentioning a past year — drops legitimate current news about historical topics
- API `start`/`end`/`source` query params are accepted but ignored
- Frontend looks functional but not polished — needs UX pass for real-user readability

---

## Architecture Decisions (DO NOT CHANGE)

- **Flat MapView, NOT GlobeView** — HeatmapLayer doesn't work on GlobeView
- **Keyword classifier, NOT distilBERT** — <1ms, zero torch dependency
- **spaCy NER only on unstructured sources** — GDELT/ACLED already have coords
- **Real Cassandra on EC2, NOT AWS Keyspaces** — Keyspaces doesn't support tunable consistency (needed for CAP research)
- **Python Kafka consumer, NOT PyFlink** for dev — Flink is optional Phase 5 wrapper
- **Dark theme** — #0a0a1a background, cyan (#00ffc8) / green / orange accents

## Kafka Schema (Unified)

All producers normalize to:
```json
{
  "event_id": "uuid", "source": "gdelt|acled|rss|bluesky|wikipedia",
  "raw_text": "string", "title": "string|null", "timestamp": "ISO8601",
  "source_url": "string|null",
  "geo": { "lat": "float|null", "lon": "float|null", "country_code": "string|null", "location_name": "string|null" },
  "metadata": {}
}
```
After NLP: `+ event_type, confidence, entities[], severity, dedupe_hash`

## Cassandra Schema
```sql
PRIMARY KEY ((region, time_bucket), event_time, event_id)
CLUSTERING ORDER BY (event_time DESC)
-- region = continent-level bucket, time_bucket = hourly like '2026-04-03T14'
```

---

# ============================================================
# FINISH PLAN — Deploy to AWS (Cheap)
# ============================================================
#
# Goal: Ship a deployed version that a professor can visit in a browser,
# see real live news events on a map, filter/click/explore them.
# Budget: <$25/month running cost.
#
# Status: NOT STARTED
# ============================================================

## Step 1: Unified Runner (fixes "7 terminals" problem)
**File:** `run_all.py` (new, project root)
**Why:** Running 7 separate terminals is awful for demos and for deployment. One process to rule them all.
**What:**
- Python script that spawns all 5 producers + consumer + API as managed threads/subprocesses
- Graceful shutdown on Ctrl+C (SIGINT) — kills all children
- Structured logging with `[source]` prefixes so output is readable
- Health monitoring: if a producer crashes, log it but don't kill everything (fail gracefully)
- Each producer runs on its own poll interval (GDELT=15min, RSS=60s, etc.) — already built into `base_producer.run(interval=...)`
- Consumer and API run continuously
- **This same script is what runs on EC2 in production**

**Implementation notes:**
- Use `threading` for producers (they're I/O-bound, GIL is fine)
- Use `subprocess` for uvicorn API server (needs its own event loop)
- Or just run uvicorn programmatically via `uvicorn.run()` in a thread
- Signal handler to set a shutdown flag, each thread checks it

## Step 2: Backend Bug Fixes (before deployment)
**Priority fixes — do these before deploying:**

### 2a. Relax freshness filter (`processing/consumer.py`)
- `_is_fresh()` drops too many events. The `_OLD_YEAR_RE` regex rejects any text mentioning 2024 or earlier — this drops real current news like "2024 conflict continues into 2026"
- **Fix:** Remove the `_OLD_YEAR_RE` check entirely for RSS. Keep the timestamp-based age check (MAX_EVENT_AGE_DAYS) which is sufficient.
- For Wikipedia, keep `_OLD_YEAR_RE` but only match titles, not body text

### 2b. Persist geocoding cache (`processing/nlp/geocoder.py`)
- Currently in-memory LRU only — every restart re-fetches from Nominatim
- **Fix:** On cache miss after Nominatim lookup, append result to `data/geo_cache_seed.json` (or a separate `geo_cache_learned.json`). Load both on startup.
- Use a file lock or just write-on-shutdown to avoid corruption

### 2c. WebSocket consumer thread recovery (`api/routes/ws.py`)
- If the Kafka consumer thread crashes, WebSocket goes permanently silent
- **Fix:** Wrap the thread body in a retry loop with exponential backoff. If it crashes, log and restart after 5s/10s/30s.

### 2d. Bluesky thread cleanup (`ingestion/bluesky_producer.py`)
- Thread leak on error — daemon thread spins but firehose is dead
- **Fix:** Add proper exception handling in the firehose thread. On error, wait and reconnect.

## Step 3: Frontend Polish (major UX improvements)
**Goal:** Make it look like a real intelligence dashboard a user would actually want to use.

### 3a. Layout improvements
- **Collapsible sidebar** — the EventsSidebar takes 360px always. Add a toggle button (chevron) to collapse it. Default to collapsed on mobile-width screens.
- **Responsive filter bar** — currently all chips on one line, wraps messily. Group into labeled sections: "SOURCES" and "EVENT TYPES" with subtle dividers.
- **Better empty state** — when no events loaded yet, show a centered message like "Connecting to live feeds..." with a subtle pulse animation instead of blank map.

### 3b. Map interaction improvements
- **Hover tooltips on scatter points** — show event title + type on hover (Deck.gl `getTooltip` prop). Currently you have to click to see anything.
- **Cluster dense points** — when zoomed out, many points overlap. Use Deck.gl `IconLayer` with aggregation or implement a simple grid-based clustering.
- **Pulse animation on new events** — when a new event arrives via WebSocket, briefly pulse/flash its scatter point so the user can see activity.

### 3c. Event panel improvements
- **Better typography** — increase line-height, add subtle section dividers
- **Timestamp formatting** — show relative time ("3 min ago") with absolute on hover
- **Source branding** — small colored dot or icon next to source name (GDELT=blue, ACLED=red, RSS=green, etc.)
- **Severity indicator** — visual bar or color-coded badge (1-10 scale)

### 3d. Stats bar improvements
- **Events/min sparkline** — tiny inline chart showing rate over last 10 minutes
- **Per-source event counts** — not just "sources active" but "GDELT: 142, RSS: 38, ..."
- **Last event timestamp** — "Last event: 3s ago" so user knows feed is live

### 3e. Loading and error states
- **WebSocket reconnection indicator** — when disconnected, show a yellow banner "Reconnecting..." at top of screen (not just the dot in stats bar)
- **Map loading skeleton** — show a dark placeholder while Mapbox tiles load

### 3f. Color and theme refinements
- Ensure all text is readable (some #6a6a7a text on #0a0a1a is too low contrast)
- Add subtle glow effects on the SENTINEL title and key stats
- Refine event type colors for better visual distinction at small scatter sizes

## Step 4: Dockerize Everything
**Files:** `Dockerfile` (project root — single multi-stage), `docker-compose.prod.yml`

### Single Dockerfile (multi-target)
```dockerfile
# Stage: backend
FROM python:3.12-slim AS backend
COPY requirements.txt .
RUN pip install -r requirements.txt && python -m spacy download en_core_web_lg
COPY ingestion/ processing/ api/ run_all.py ./
CMD ["python", "run_all.py"]

# Stage: frontend-build
FROM node:20-alpine AS frontend-build
COPY frontend/ .
RUN npm ci && npm run build

# Stage: nginx (serves frontend + reverse proxies API)
FROM nginx:alpine AS frontend
COPY --from=frontend-build /dist /usr/share/nginx/html
COPY infrastructure/nginx/nginx.conf /etc/nginx/conf.d/default.conf
```

### docker-compose.prod.yml
- **zookeeper** — same as dev
- **kafka** — single broker (3 brokers is $90/mo overkill for a class project)
- **cassandra** — single node, 512MB heap
- **backend** — runs `run_all.py` (all producers + consumer + API on port 8000)
- **nginx** — serves frontend static files, reverse proxies `/api/*` and `/ws/*` to backend:8000
- Expose only port 80 (nginx) to the world

## Step 5: Deploy to AWS (Single EC2 — Cheapest)
**Target cost: ~$15-25/month**

### Why single EC2, not ECS/Fargate/CloudFormation
- The existing CloudFormation template provisions 3x Kafka brokers ($90/mo EC2 alone) — massively overprovisioned for a class project demo
- ECS Fargate adds complexity and cost for no benefit at this scale
- Single t3.small ($15/mo) or t3.medium ($30/mo) running docker-compose is the cheapest path that works
- **If the professor asks about scaling:** "The architecture supports horizontal scaling — Kafka partitions, Cassandra replication, ECS Fargate tasks — but for the demo we run on a single node to minimize cost"

### Deployment steps
1. Launch t3.medium EC2 (Amazon Linux 2023) in us-east-1
   - Security group: port 22 (SSH), port 80 (HTTP), port 443 (HTTPS optional)
   - 30GB EBS gp3 root volume (free tier)
   - Elastic IP (free while attached)
2. SSH in, install Docker + Docker Compose
3. Clone repo, copy `.env` with secrets
4. `docker-compose -f docker-compose.prod.yml up -d`
5. Wait for Cassandra to be healthy, init schema
6. Verify: `curl http://<public-ip>/health` returns 200
7. Verify: open `http://<public-ip>` in browser, map loads, events flow

### Frontend env config
- `VITE_MAPBOX_TOKEN` baked into frontend build
- `VITE_API_URL` set to empty string (same-origin — nginx proxies to backend)
- `VITE_WS_URL` set to `ws://<public-ip>/ws/live` (or empty for same-origin WebSocket)

### nginx.conf
```nginx
server {
    listen 80;
    root /usr/share/nginx/html;
    index index.html;

    location /api/ {
        proxy_pass http://backend:8000/;
    }
    location /ws/ {
        proxy_pass http://backend:8000/ws/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
    location / {
        try_files $uri $uri/ /index.html;
    }
}
```

### Cost breakdown (actual)
| Component | Monthly |
|-----------|---------|
| EC2 t3.medium (or t3.small) | $15-30 |
| EBS 30GB gp3 | $2.40 |
| Elastic IP | $0 (while attached) |
| Data transfer (minimal) | ~$1 |
| **TOTAL** | **~$18-33** |

No S3, no CloudFront, no Fargate, no multi-broker Kafka. Everything on one box.

## Step 6: Smoke Test on AWS
- [ ] Map loads at `http://<public-ip>/`
- [ ] Events appear on map within 2-3 minutes of startup (GDELT/RSS are fastest)
- [ ] WebSocket indicator shows "LIVE" (green dot)
- [ ] Click a scatter point -> EventPanel shows details with source link
- [ ] Filters work (toggle event types and sources)
- [ ] Sidebar shows scrollable event feed
- [ ] Stats bar updates events/min in real-time
- [ ] System stable for 30+ minutes without crashes
- [ ] At least 3 of 5 sources producing events

## Step 7 (Optional): Benchmarking + Paper
Only if time permits. The deployment in Steps 1-6 is the submission.
- `benchmark/load_generator.py` already exists
- Scale to 3-node Cassandra on EC2 ONLY for the 2-hour benchmark window
- Run benchmark, collect data, tear down extra nodes immediately

---

# IMPLEMENTATION ORDER

**Do steps sequentially. Each step should be tested before moving to the next.**

1. **`run_all.py`** — unified runner (Step 1)
2. **Backend bug fixes** — freshness filter, geocache persist, WS recovery (Step 2)
3. **Frontend polish** — UX improvements (Step 3) — this is the most visible improvement
4. **Dockerize** — single Dockerfile + docker-compose.prod.yml + nginx (Step 4)
5. **Deploy** — EC2 + docker-compose up (Step 5)
6. **Smoke test** — verify everything works on AWS (Step 6)

---

## Rules & Conventions

- **No hallucinated data.** Every event traces to a real source URL.
- **No external AI APIs.** All NLP runs locally (spaCy + keyword classifier).
- **Schema-first.** All Kafka messages follow the unified schema.
- **Cache geocoding aggressively.** Pre-seed + persist learned cache.
- **Dark theme.** #0a0a1a background, #00ffc8 cyan accents.
- **Fail gracefully.** One source down != pipeline down.
- **Flat map only.** MapView, not GlobeView.
- **Python 3.12, TypeScript strict.**

## Key File Locations

| What | Where |
|------|-------|
| Producer base class | `ingestion/base_producer.py` |
| All producer configs/keywords | `ingestion/config.py` |
| NLP pipeline (NER/geocoder/classifier) | `processing/nlp/` |
| Kafka consumer + event routing | `processing/consumer.py` |
| Cassandra sink | `processing/sink.py` |
| Dedup logic | `processing/dedup.py` |
| FastAPI app + routes | `api/main.py`, `api/routes/` |
| WebSocket live feed | `api/routes/ws.py` |
| Cassandra queries | `api/db.py` |
| Deck.gl map component | `frontend/src/components/MapView.tsx` |
| Event type colors/classification | `frontend/src/utils/types.ts` |
| WebSocket hook | `frontend/src/hooks/useWebSocket.ts` |
| All CSS | `frontend/src/App.css` |
| Geocoding cache seed | `data/geo_cache_seed.json` |
| Cassandra schema | `infrastructure/cassandra/init.cql` |
| Docker (dev) | `docker-compose.yml` |
| Docker (prod) | `docker-compose.prod.yml` (to be created) |
| AWS CloudFormation (overengineered, DO NOT USE for cheap deploy) | `infrastructure/aws/cloudformation.yml` |
