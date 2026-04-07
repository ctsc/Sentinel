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
# ---------------------------------------------------------------------------
ACLED_API_URL = "https://api.acleddata.com/acled/read"
ACLED_API_KEY = os.getenv("ACLED_API_KEY", "")
ACLED_EMAIL = os.getenv("ACLED_EMAIL", "")
ACLED_POLL_INTERVAL = 3600  # 1 hour (conservative — 500 req/day limit)
ACLED_PAGE_SIZE = 5000

# ---------------------------------------------------------------------------
# RSS Feeds
# ---------------------------------------------------------------------------
RSS_FEEDS = [
    {"name": "BBC World", "url": "https://feeds.bbci.co.uk/news/world/rss.xml"},
    {"name": "Al Jazeera", "url": "https://www.aljazeera.com/xml/rss/all.xml"},
    {
        "name": "Google News (World)",
        "url": "https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGx1YlY4U0FtVnVHZ0pWVXigAQ",
    },
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
