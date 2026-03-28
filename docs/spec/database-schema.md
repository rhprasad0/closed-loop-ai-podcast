> Part of the [Implementation Spec](../../IMPLEMENTATION_SPEC.md)

# Database Schema

DDL for `sql/schema.sql`. The database and tables below have already been created on the RDS instance — do not re-run this DDL.

```sql
-- 0 Stars, 10/10 — Database Schema
-- Run with: psql <postgres-connection-string> -f sql/schema.sql

CREATE DATABASE zerostars;
\c zerostars

CREATE TABLE IF NOT EXISTS episodes (
    episode_id      SERIAL PRIMARY KEY,
    air_date        DATE NOT NULL,
    repo_url        TEXT NOT NULL,
    repo_name       TEXT NOT NULL,
    developer_github TEXT NOT NULL,
    developer_name  TEXT,
    star_count_at_recording INTEGER,
    script_text     TEXT NOT NULL,
    research_json   JSONB,
    cover_art_prompt TEXT,
    s3_mp3_path     TEXT,
    s3_mp4_path     TEXT,
    s3_cover_art_path TEXT,
    producer_attempts INTEGER DEFAULT 1,
    execution_id    TEXT,
    language        TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS episode_metrics (
    metric_id       SERIAL PRIMARY KEY,
    episode_id      INTEGER NOT NULL REFERENCES episodes(episode_id),
    linkedin_post_url TEXT,
    views           INTEGER DEFAULT 0,
    likes           INTEGER DEFAULT 0,
    comments        INTEGER DEFAULT 0,
    shares          INTEGER DEFAULT 0,
    snapshot_date   DATE NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_episode_metrics_episode_id ON episode_metrics(episode_id);
ALTER TABLE episode_metrics ADD CONSTRAINT episode_metrics_episode_snapshot_unique UNIQUE (episode_id, snapshot_date);

CREATE TABLE IF NOT EXISTS featured_developers (
    developer_github TEXT PRIMARY KEY,
    episode_id      INTEGER NOT NULL REFERENCES episodes(episode_id),
    featured_date   DATE NOT NULL
);
```
