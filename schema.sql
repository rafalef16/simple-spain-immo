-- Simple Spain — Supabase schema
-- Run this SQL in your Supabase project: Dashboard → SQL Editor → New query

CREATE TABLE IF NOT EXISTS listings (
    id                  TEXT PRIMARY KEY,
    url                 TEXT UNIQUE NOT NULL,
    site                TEXT NOT NULL,
    site_family         TEXT,
    type                TEXT,
    title               TEXT,
    prix_eur            BIGINT,
    prix_display        TEXT,
    ville               TEXT,
    ville_canonical     TEXT,
    lat                 FLOAT,
    lon                 FLOAT,
    terrain_m2          INTEGER,
    construction_m2     INTEGER,
    description_raw     TEXT,
    description_clean   TEXT,
    cover_image_url     TEXT,
    photos              JSONB DEFAULT '[]',
    ref                 TEXT,
    dedup_hash          TEXT,
    scrap_timestamp     TIMESTAMPTZ DEFAULT NOW(),
    deleted_at          TIMESTAMPTZ DEFAULT NULL,
    admin_notes         TEXT
);

-- Full-text search index on description (Spanish stemming)
CREATE INDEX IF NOT EXISTS listings_description_fts
    ON listings USING GIN (to_tsvector('spanish', coalesce(description_clean, '')));

CREATE TABLE IF NOT EXISTS client_profiles (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name                TEXT NOT NULL,
    raw_text            TEXT,
    budget_min          BIGINT,
    budget_max          BIGINT,
    terrain_min         INTEGER,
    terrain_max         INTEGER,
    construction_min    INTEGER,
    construction_max    INTEGER,
    villes              TEXT[],
    types               TEXT[],
    keywords_must       TEXT[],
    keywords_must_not   TEXT[],
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS client_matches (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id   UUID REFERENCES client_profiles(id) ON DELETE CASCADE,
    listing_id  TEXT REFERENCES listings(id) ON DELETE CASCADE,
    matched_at  TIMESTAMPTZ DEFAULT NOW(),
    notified    BOOLEAN DEFAULT FALSE,
    UNIQUE(client_id, listing_id)
);

CREATE TABLE IF NOT EXISTS translations (
    listing_id              TEXT REFERENCES listings(id) ON DELETE CASCADE,
    lang                    TEXT NOT NULL,
    title_tr                TEXT,
    desc_tr                 TEXT,
    terrain_m2_public       INTEGER,
    construction_m2_public  INTEGER,
    location_anon           TEXT,
    created_at              TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (listing_id, lang)
);

CREATE TABLE IF NOT EXISTS dedup_events (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    action      TEXT,
    listing_id  TEXT,
    reason      TEXT,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);
