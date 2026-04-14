"""Sentinel ingestion configuration — endpoints, poll intervals, keyword lists."""

import os
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Kafka
# ---------------------------------------------------------------------------
KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")

KAFKA_TOPICS = {
    "gdelt": "sentinel.raw.gdelt",
    "acled": "sentinel.raw.acled",
    "rss": "sentinel.raw.rss",
    "bluesky": "sentinel.raw.bluesky",
    "wikipedia": "sentinel.raw.wikipedia",
    "telegram": "sentinel.raw.telegram",
    # Enriched (post-NLP) events re-published by the consumer for live UI.
    "enriched": "sentinel.enriched",
}

# ---------------------------------------------------------------------------
# Cassandra
# ---------------------------------------------------------------------------
CASSANDRA_HOSTS = os.getenv("CASSANDRA_HOSTS", "localhost").split(",")
CASSANDRA_PORT = int(os.getenv("CASSANDRA_PORT", "9042"))
CASSANDRA_KEYSPACE = os.getenv("CASSANDRA_KEYSPACE", "sentinel")

# ---------------------------------------------------------------------------
# GDELT
# ---------------------------------------------------------------------------
GDELT_LAST_UPDATE_URL = "http://data.gdeltproject.org/gdeltv2/lastupdate.txt"
GDELT_API_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
GDELT_POLL_INTERVAL = 900  # 15 minutes

# ---------------------------------------------------------------------------
# ACLED
# ACLED uses OAuth (email + password → bearer token), not static API keys.
# ---------------------------------------------------------------------------
ACLED_API_URL = "https://acleddata.com/api/acled/read"
ACLED_OAUTH_URL = "https://acleddata.com/oauth/token"
ACLED_EMAIL = os.getenv("ACLED_EMAIL", "")
ACLED_PASSWORD = os.getenv("ACLED_PASSWORD", "")
ACLED_POLL_INTERVAL = 3600  # 1 hour (conservative — 500 req/day limit)
ACLED_PAGE_SIZE = 500
ACLED_MAX_PAGES_PER_POLL = 1

# ---------------------------------------------------------------------------
# Event freshness filter (applied by the consumer)
# Drop any event whose timestamp is older than this, regardless of source.
# Keeps the dashboard focused on real-time conflict activity.
# ---------------------------------------------------------------------------
MAX_EVENT_AGE_DAYS = 45
# On first poll (no watermark yet), only pull events from the last N days.
# Without this, ACLED returns oldest-first from 1997 and would exhaust the 500 req/day quota.
# Keep in sync with MAX_EVENT_AGE_DAYS so the consumer doesn't filter out everything we pull.
ACLED_BACKFILL_DAYS = 45

# ---------------------------------------------------------------------------
# RSS Feeds
# ---------------------------------------------------------------------------
RSS_FEEDS = [
    # Mainstream world news
    {"name": "BBC World", "url": "https://feeds.bbci.co.uk/news/world/rss.xml"},
    {"name": "BBC Middle East", "url": "https://feeds.bbci.co.uk/news/world/middle_east/rss.xml"},
    {"name": "Al Jazeera", "url": "https://www.aljazeera.com/xml/rss/all.xml"},
    {"name": "Guardian World", "url": "https://www.theguardian.com/world/rss"},
    {"name": "DW World", "url": "https://rss.dw.com/rdf/rss-en-world"},
    {"name": "France24 World", "url": "https://www.france24.com/en/rss"},
    {"name": "CNN World", "url": "http://rss.cnn.com/rss/edition_world.rss"},
    {"name": "NPR World", "url": "https://feeds.npr.org/1004/rss.xml"},
    {"name": "NBC World", "url": "http://feeds.nbcnews.com/nbcnews/public/world"},
    # Conflict / military focus
    {"name": "Times of Israel", "url": "https://www.timesofisrael.com/feed/"},
    {"name": "Al Monitor", "url": "https://www.al-monitor.com/rss"},
    {"name": "Defense News", "url": "https://www.defensenews.com/arc/outboundfeeds/rss/?outputType=xml"},
    {"name": "Kyiv Independent", "url": "https://kyivindependent.com/rss/"},
    # Reddit conflict subs (RSS, real-time, no auth)
    {"name": "Reddit r/worldnews", "url": "https://www.reddit.com/r/worldnews/new.rss"},
    {"name": "Reddit r/CombatFootage", "url": "https://www.reddit.com/r/CombatFootage/new.rss"},
    {"name": "Reddit r/UkraineWarVideoReport", "url": "https://www.reddit.com/r/UkraineWarVideoReport/new.rss"},
    {"name": "Reddit r/MilitaryNews", "url": "https://www.reddit.com/r/MilitaryNews/new.rss"},
    {"name": "Reddit r/syriancivilwar", "url": "https://www.reddit.com/r/syriancivilwar/new.rss"},
    # Google News feeds removed — their CBM... redirect URLs are unreliable
    # and often resolve to a Google News search page instead of the actual
    # publisher article, which violates the "every event has a real source
    # link" rule in CLAUDE.md.
]
RSS_POLL_INTERVAL = 60  # seconds

# ---------------------------------------------------------------------------
# Bluesky
# ---------------------------------------------------------------------------
BLUESKY_FIREHOSE_URL = "wss://bsky.network/xrpc/com.atproto.sync.subscribeRepos"
BLUESKY_MAX_EVENTS_PER_MIN = 100

# ---------------------------------------------------------------------------
# Wikipedia
# ---------------------------------------------------------------------------
WIKIPEDIA_SSE_URL = "https://stream.wikimedia.org/v2/stream/recentchange"

# ---------------------------------------------------------------------------
# Conflict / geopolitical keyword list (shared by Bluesky + Wikipedia + RSS classifier)
# ---------------------------------------------------------------------------
CONFLICT_KEYWORDS = [
    "war", "conflict", "attack", "bomb", "bombing", "missile", "airstrike",
    "air strike", "drone strike", "shelling", "artillery", "explosion",
    "military", "troops", "soldiers", "army", "navy", "combat", "battle",
    "invasion", "incursion", "offensive", "ceasefire", "cease-fire",
    "casualty", "casualties", "killed", "wounded", "dead", "death toll",
    "genocide", "massacre", "atrocity", "war crime",
    "protest", "demonstration", "riot", "uprising", "unrest", "revolt",
    "coup", "coup d'état", "martial law", "state of emergency",
    "terrorism", "terrorist", "extremist", "insurgent", "militia",
    "hostage", "kidnapping", "assassination", "shooting",
    "refugee", "displaced", "humanitarian crisis", "famine",
    "sanctions", "embargo", "blockade",
    "earthquake", "tsunami", "hurricane", "typhoon", "cyclone", "flood",
    "wildfire", "volcanic eruption", "landslide",
    "nuclear", "chemical weapon", "biological weapon",
]

# Pre-compiled set for O(1) lookups (used for single-word matching)
CONFLICT_KEYWORD_SET = set(CONFLICT_KEYWORDS)
