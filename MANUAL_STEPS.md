# Sentinel — Manual Steps Required From You

Everything Claude Code can automate (writing code, config files, tests) is already done or will be done by Claude. This document lists **only the things that require your manual action** — account signups, installs, UI verification, AWS console work, etc.

---

## One-Time Setup (Do These First)

### 1. Install Prerequisites
- [ ] **Docker Desktop** — Install and ensure it's running. Download from [docker.com](https://www.docker.com/products/docker-desktop/)
- [ ] **Python 3.12** — **Required version. Do NOT use 3.13 or 3.14** (spaCy 3.7 has no prebuilt Windows wheels for them and will fail without a C++ compiler).
  1. Download the Windows installer: [python-3.12.9-amd64.exe](https://www.python.org/ftp/python/3.12.9/python-3.12.9-amd64.exe) (from [python.org/downloads/release/python-3129](https://www.python.org/downloads/release/python-3129/))
  2. Run the installer. **Check both boxes** at the bottom of the first screen:
     - ✅ "Use admin privileges when installing py.exe"
     - ✅ "Add python.exe to PATH"
  3. Click "Install Now" — takes ~1 minute.
  4. Verify in a **new** terminal (close and reopen so PATH refreshes):
     ```
     py -3.12 --version
     ```
     Should print `Python 3.12.9`. If you already have another Python version, leave it alone — `py -3.12` targets 3.12 specifically via the Python launcher.
  5. Create the project venv with 3.12:
     ```powershell
     py -3.12 -m venv .venv
     .venv\Scripts\Activate.ps1
     python --version   # should now say 3.12.x
     ```
- [ ] **Node.js 18+** — Install if not already present. Verify: `node --version`
- [ ] **Git** — Already installed (repo exists)

### 2. Create API Accounts & Get Keys
- [ ] **ACLED** — Register a free myACLED account at [acleddata.com/user/register](https://acleddata.com/user/register). ACLED uses OAuth (not static API keys): the producer POSTs your email + password to `https://acleddata.com/oauth/token` to get a 24-hour bearer token, which it refreshes automatically. Put your credentials in `.env`:
  ```
  ACLED_EMAIL=<your email>
  ACLED_PASSWORD=<your password>
  ```
- [ ] **Mapbox** — Create a free account at [mapbox.com](https://www.mapbox.com/). Get your default public token from the account dashboard. Put it in `.env`:
  ```
  MAPBOX_TOKEN=<your token>
  ```
- [ ] **Copy `.env.example` to `.env`** and fill in the values above. Kafka/Cassandra defaults are fine for local dev.

### 3. Download spaCy Model
After `pip install -r requirements.txt`, run:
```bash
python -m spacy download en_core_web_lg
```
This is a ~560MB download. Only needed once.

---

## Phase 1 — Infrastructure Verification

**Kafka + Zookeeper + Cassandra all run inside Docker.** You do not install them separately. `docker-compose up -d` reads `docker-compose.yml` and starts all three as containers. `KAFKA_BOOTSTRAP_SERVERS=localhost:9092` in `.env` is correct — the Kafka container exposes port 9092 on your host.

- [ ] Run `docker-compose up -d` and wait ~60 seconds for all containers to be healthy
- [ ] Verify with `docker-compose ps` — all 3 containers (kafka, zookeeper, cassandra) should show "healthy"
- [ ] Run `pytest tests/test_phase1_infra.py -v` — all tests must pass
- [ ] Run `cd frontend && npm run dev` — verify the page loads in your browser at `http://localhost:5173`
- [ ] Run `cd frontend && npm run build` — verify zero errors/warnings

---

## Phase 2 — Producer Stability Test (Manual)

After automated tests pass (`pytest tests/test_producers.py tests/test_schema_consistency.py -v`):

- [ ] Open 6 terminal windows and run each of these simultaneously:
  ```
  Terminal 1: python -m ingestion.gdelt_producer
  Terminal 2: python -m ingestion.acled_producer
  Terminal 3: python -m ingestion.rss_producer
  Terminal 4: python -m ingestion.bluesky_producer
  Terminal 5: python -m ingestion.wikipedia_producer
  Terminal 6: (monitor) — watch for crashes in the other terminals
  ```
- [ ] Let all 5 run for **10 minutes** continuously
- [ ] Verify: no crashes, no memory leaks, all producers still running after 10 min

---

## Phase 3 — Pipeline Stability Test (Manual)

After automated tests pass (`pytest tests/test_nlp.py tests/test_dedup.py tests/test_pipeline_e2e.py -v`):

- [ ] Run all 5 producers (same as Phase 2) + the consumer:
  ```
  Terminal 6: python -m processing.consumer
  ```
- [ ] Let the full pipeline run for **30 minutes**
- [ ] Verify: no crashes, events accumulating in Cassandra, geocoding cache hit rate > 50% (printed in consumer logs)

---

## Phase 4 — Visual Verification (Manual)

After automated tests pass (`pytest tests/test_api.py -v`) and frontend builds clean.

### Start the full stack (7 terminals)
All from the Sentinel root with `.venv` activated (except the frontend terminal):
```
Terminal 1: python -m ingestion.gdelt_producer
Terminal 2: python -m ingestion.acled_producer
Terminal 3: python -m ingestion.rss_producer
Terminal 4: python -m ingestion.bluesky_producer
Terminal 5: python -m ingestion.wikipedia_producer
Terminal 6: python -m processing.consumer
Terminal 7: uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
Terminal 8 (frontend, no venv): cd frontend && npm run dev
```

Verify API is up: open `http://localhost:8000/health` in a browser — should return `{"status":"ok"}`.

### Open the frontend and verify:

- [ ] Map loads with dark Mapbox style — no missing tiles or errors
- [ ] Heatmap layer shows red/orange zones where events cluster
- [ ] Scatter points appear and are color-coded by event type
- [ ] Click a scatter point — EventPanel slides in showing title, source, type, confidence, source URL
- [ ] FilterBar: toggle an event type off — those points disappear
- [ ] FilterBar: select a country — only that country's events show
- [ ] StatsBar: events/min counter updates in real-time
- [ ] No visible lag or jank with 1K+ points on screen

---

## Phase 5 — AWS Setup (Manual Console Work)

### AWS Account & CLI
- [ ] Have an AWS account with billing enabled
- [ ] Install AWS CLI and configure: `aws configure` (access key, secret, region `us-east-1`)

### EC2 Instances
- [ ] Launch **3x t3.medium** EC2 instances for Kafka (Amazon Linux 2)
- [ ] Launch **1x t3.medium** (dev) or **3x t3.medium** (benchmark) for Cassandra
- [ ] Configure security groups:
  - Kafka: ports 9092 (broker), 2181 (ZK) open within VPC
  - Cassandra: port 9042 open within VPC
  - API: port 8000 open to CloudFront
- [ ] SSH into Kafka instances and install/configure Kafka (or use Docker)
- [ ] SSH into Cassandra instance(s) and install/configure Cassandra
- [ ] Run `init.cql` on the Cassandra cluster

### ECS Fargate
- [ ] Create an ECR repository for each Docker image (processor, api, frontend)
- [ ] Build and push Docker images:
  ```bash
  docker build -f infrastructure/docker/Dockerfile.processor -t sentinel-processor .
  docker build -f infrastructure/docker/Dockerfile.api -t sentinel-api .
  docker build -f infrastructure/docker/Dockerfile.frontend -t sentinel-frontend .
  # Tag and push to ECR
  ```
- [ ] Create ECS cluster, task definitions, and services for processor + API

### S3 + CloudFront
- [ ] Create S3 bucket `sentinel-raw-events` for JSON archive
- [ ] Create S3 bucket for frontend static files, upload built frontend
- [ ] Create CloudFront distribution pointing to frontend S3 + API ECS service
- [ ] Update `.env` with AWS endpoints (Kafka brokers, Cassandra hosts, S3 bucket)

### Smoke Test
- [ ] Verify each service health check via CloudFront URLs
- [ ] Verify end-to-end: event produced → Cassandra → frontend map
- [ ] Let all 5 producers run on AWS for 10 minutes without crashes
- [ ] Check S3 bucket is accumulating raw JSON files

---

## Phase 6 — Benchmarking (Manual)

### Scale Up
- [ ] Scale Cassandra to **3 nodes** for benchmark
- [ ] Verify all 3 nodes are in the ring: `nodetool status`

### Run Benchmarks
- [ ] Run load generator at each tier (1x, 5x, 10x, 25x, 50x) and collect results
- [ ] Run CAP experiment: switch between ONE and QUORUM consistency, measure latency
- [ ] Verify graphs are generated correctly (axes labeled, data visible)

### Demo Prep
- [ ] Do a full start-to-finish walkthrough: map loads → events flow → filters work → click events → source links work
- [ ] Record demo or prepare live demo environment

### Teardown
- [ ] **Immediately after benchmarking:** terminate all EC2 instances, delete ECS services, empty and delete S3 buckets, delete CloudFront distribution
- [ ] Verify in AWS billing console that no resources are still running

---

## Summary — What You Need Accounts For

| Service | Why | Cost |
|---------|-----|------|
| ACLED | myACLED account (OAuth) for conflict data | Free |
| Mapbox | Map tile rendering | Free tier (50K loads/mo) |
| AWS | Production deploy + benchmark | ~$60-70/mo dev, ~$40 for 2hr benchmark |
| Docker Hub | Pull container images | Free |
