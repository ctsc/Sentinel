-- Sentinel Cassandra Schema
-- Run: cqlsh -f infrastructure/cassandra/init.cql

CREATE KEYSPACE IF NOT EXISTS sentinel WITH replication = {
  'class': 'SimpleStrategy', 'replication_factor': 1
};

CREATE TABLE IF NOT EXISTS sentinel.events (
    region text,
    time_bucket text,
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
