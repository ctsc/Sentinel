# Sentinel

Real-time OSINT dashboard that pulls from five public data sources, runs each event
through a local NLP pipeline, and plots the results on a live map. Built as a solo
graduate project for CSC 6311 at Georgia State (Spring 2026).

Everything on the map traces back to a real, public source. No fabricated events
and no external AI APIs. Classification and geocoding run locally.

## What It Does

Five producers poll public feeds and push normalized JSON into Kafka. A consumer
pulls from Kafka, runs named entity recognition with spaCy, attempts to geocode
any location that lacks coordinates, classifies the event type with a keyword
model, and writes the enriched record to Cassandra. A FastAPI server exposes a
REST endpoint for historical queries and a WebSocket endpoint for the live feed.
The frontend is a React app that renders the stream on a dark Mapbox map using
Deck.gl scatter and heatmap layers.

Sources currently wired up:

- GDELT (15-minute event export)
- ACLED (conflict events, requires free account)
- RSS (a rotating list of news feeds)
- Bluesky firehose (filtered by keyword)
- Wikipedia recent-changes SSE stream

## Requirements

- Python 3.11 or 3.12. spaCy 3.7 does not publish wheels for 3.13 yet, so newer
  interpreters will fail on install.
- Node 20 or newer for the frontend.
- Docker and Docker Compose for Kafka, Zookeeper, and Cassandra.
- A Mapbox token (free tier is fine) for the base map tiles.
- Optional: an ACLED account if you want that producer to run. The other four
  work without any credentials.

## Environment Variables

Create a `.env` file in the project root:

```
MAPBOX_TOKEN=pk.your_token_here
VITE_MAPBOX_TOKEN=pk.your_token_here

# Optional
ACLED_EMAIL=you@example.com
ACLED_PASSWORD=your_password

# These default to localhost and usually do not need to be set
KAFKA_BOOTSTRAP_SERVERS=localhost:9092
CASSANDRA_HOSTS=localhost
```

## Running Locally

### 1. Start the infrastructure

```bash
docker-compose up -d
```

That brings up Zookeeper, a single-broker Kafka, and a single-node Cassandra.
Wait about a minute for Cassandra to finish bootstrapping, then initialize the
schema:

```bash
docker exec -it sentinel-cassandra cqlsh -f /docker-entrypoint-initdb.d/init.cql
```

### 2. Install the Python side

```bash
pip install -r requirements.txt
python -m spacy download en_core_web_lg
```

The spaCy model is about 500 MB. It only needs to be downloaded once.

### 3. Run the backend

The unified runner starts all producers, the consumer, and the API in one
process:

```bash
python run_all.py
```

You will see log lines prefixed with the thread name (`[gdelt]`, `[consumer]`,
`[api]`, and so on). The API listens on port 8000. Events typically start
reaching Cassandra within a minute or two, mostly from RSS and GDELT since those
are the fastest feeds.

If you want to run a single producer in isolation for debugging, each one can be
invoked directly, for example:

```bash
python -m ingestion.rss_producer
```

### 4. Run the frontend

In a separate terminal:

```bash
cd frontend
npm install
npm run dev
```

Open the URL Vite prints (usually `http://localhost:5173`). The dashboard should
connect to the WebSocket at `ws://localhost:8000/ws/live` and start plotting
events as they arrive.

### 5. Tests

With Docker running:

```bash
pytest tests/ -v
```

The end-to-end test spins up real Kafka and Cassandra connections, so it will
fail if the containers are not healthy.

## Project Layout

```
ingestion/        producers, one per source, plus a shared base class
processing/       Kafka consumer, NLP pipeline, Cassandra sink, dedup
api/              FastAPI app, REST routes, WebSocket route
frontend/         React + Deck.gl dashboard
infrastructure/   Cassandra schema, nginx config, Docker bits
data/             geocoding cache seed
tests/            pytest suite
run_all.py        unified runner for the whole backend
```

The Kafka message shape is documented at the top of `ingestion/base_producer.py`
and every producer normalizes to it before sending.

## Design Rationale

A few decisions are worth calling out because they are not obvious from the
code.

**Kafka in the middle, not a direct pipeline.** The producers could have called
the NLP code directly, but putting Kafka between ingestion and processing means
a slow or crashing consumer does not backpressure the producers, and it lets the
consumer be rewritten or scaled horizontally without touching the ingestion
layer. It also gave me a natural hook for the enriched-events WebSocket: the
consumer republishes to a second topic that the API subscribes to.

**Keyword classifier instead of a transformer.** An early version used
distilBERT for event classification. It worked but added roughly 300 MB of
PyTorch dependencies, took seconds to warm up, and produced classifications
that were often no better than a hand-tuned keyword matcher on this domain.
The current classifier runs in under a millisecond per event and the rules are
readable, which matters for a project where every classification needs to be
defensible.

**spaCy NER only where it is needed.** GDELT and ACLED already provide
coordinates, so running NER on them is wasted work. The consumer only invokes
the NER and geocoder paths for the unstructured sources (RSS, Bluesky,
Wikipedia).

**Cassandra, partitioned by region and time bucket.** The primary key is
`((region, time_bucket), event_time, event_id)` with clustering descending on
`event_time`. That means the common dashboard query, recent events in a given
region, is a single-partition read. The time bucket is hourly so partitions
stay bounded. This also lines up with the tunable-consistency experiments I
planned for the optional benchmarking phase: a real Cassandra cluster supports
per-query consistency levels, which Keyspaces does not.

**Flat MapView, not GlobeView.** Deck.gl's HeatmapLayer does not render on a
globe projection. I went with the flat Mercator view because the heatmap is
useful for showing density and I did not want two different visual modes.

**One process, not seven.** Running each producer in its own terminal was fine
during development but awful for demos and worse for deployment. `run_all.py`
wraps every long-running piece as a daemon thread with a shared shutdown flag
and restart-on-crash logic for the producers. The same entry point runs in
Docker and on a single EC2 host.

## Scalability Considerations

The current setup runs comfortably on one machine and could grow in a few
well-defined directions.

The ingestion layer is already partition-friendly. Each producer normalizes to
the same Kafka schema, so adding a new source means writing one class, not
changing downstream code. Poll intervals are per-source and tunable, which lets
me pull harder on sources that update quickly (RSS) and lightly on sources with
rate limits (ACLED, Bluesky).

Kafka is the main lever for horizontal scale. In the single-broker dev setup
every topic has one partition, but the consumer is written so that increasing
the partition count on `sentinel.events` and starting multiple consumer
instances in the same group would let processing fan out across nodes. The
NLP step is CPU-bound and mostly independent per event, so this is the first
place I would split if throughput became a bottleneck.

Cassandra scales along the region and hour dimensions. The partition key keeps
each partition bounded in size even as total event volume grows, because a new
`time_bucket` cuts over every hour. Adding nodes to the cluster expands both
read and write capacity proportionally, and the schema does not require any
secondary indexes for the dashboard queries, which keeps the write path cheap.

The NLP pipeline has two known hot spots. Geocoding hits Nominatim over HTTP,
which is rate-limited and slow. An in-memory LRU plus a seeded JSON cache of
common places handles the common case, but a Redis-backed shared cache would
be the right move for a multi-instance deployment. spaCy NER itself is fast
enough with the `en_core_web_lg` model to not need batching at current volumes.

The WebSocket path is the part most likely to misbehave under real load. Right
now a single FastAPI process fans out every enriched event to every connected
client. At the scale this project was designed for, a few dozen concurrent
viewers, that is fine. For a larger audience the right answer is to move the
fanout into Redis pub/sub or a proper broker and make the API servers stateless
behind a load balancer.

## Limitations

This is a class project with a deadline, and there are rough edges that I know
about but have not fixed.

The consumer's freshness filter is too aggressive. It drops any RSS text that
mentions a past year, even when the article is current and only refers back to
an earlier event. The timestamp-based age check is sufficient on its own and
the year regex should be removed for RSS.

The geocoding cache is not persisted across restarts. Learned coordinates are
held in an in-memory LRU and lost when the process stops, so a cold start
re-hits Nominatim for everything that is not in the seed file.

The WebSocket Kafka consumer thread has no restart logic. If it crashes, the
live feed silently stops until the whole API is restarted. Producers have a
retry wrapper in `run_all.py`; the WebSocket consumer should get the same
treatment.

The Bluesky producer leaks a daemon thread on error. The firehose reconnect
path swallows exceptions but does not clean up the old thread before starting
a new one.

The REST endpoint accepts `start`, `end`, and `source` query parameters but
currently ignores them. The Cassandra query always returns the most recent
window. Implementing these is straightforward but has not been done.

Cassandra runs as a single node. That is deliberate for local development and
for the budget-constrained deploy target, but it means there is no replication
and no tunable consistency to experiment with. The optional benchmarking phase
in the project plan would bring up a three-node cluster on EC2 for a short
window; that has not been executed yet.

The frontend is functional rather than polished. The UX pass documented in
`CLAUDE.md` (collapsible sidebar, hover tooltips, source branding, reconnect
indicator, and so on) is pending.

Finally, this system is not a replacement for an intelligence product. It is a
demonstration of a stream-processing architecture using public sources. Nothing
here has been reviewed for accuracy, timeliness, or completeness, and the
classifier's output is a heuristic, not ground truth.
