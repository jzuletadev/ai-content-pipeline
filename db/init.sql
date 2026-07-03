-- init.sql — Schema completo de content_factory
-- Se ejecuta automáticamente cuando postgres arranca por primera vez.

-- ============================================================
-- SISTEMA A: Radar de nichos
-- ============================================================

CREATE TABLE IF NOT EXISTS channels (
    id              BIGSERIAL PRIMARY KEY,
    platform        TEXT NOT NULL,
    platform_id     TEXT NOT NULL,
    handle          TEXT,
    title           TEXT,
    niche_guess     TEXT,
    is_ai_content   BOOLEAN DEFAULT NULL,
    discovered_at   TIMESTAMPTZ DEFAULT now(),
    UNIQUE (platform, platform_id)
);

CREATE TABLE IF NOT EXISTS channel_snapshots (
    id              BIGSERIAL PRIMARY KEY,
    channel_id      BIGINT REFERENCES channels(id) ON DELETE CASCADE,
    captured_at     TIMESTAMPTZ DEFAULT now(),
    subscribers     BIGINT,
    total_views     BIGINT,
    video_count     INT
);

CREATE TABLE IF NOT EXISTS observed_videos (
    id              BIGSERIAL PRIMARY KEY,
    channel_id      BIGINT REFERENCES channels(id) ON DELETE CASCADE,
    platform_id     TEXT NOT NULL,
    title           TEXT,
    published_at    TIMESTAMPTZ,
    duration_sec    INT,
    captured_at     TIMESTAMPTZ DEFAULT now(),
    views           BIGINT,
    likes           BIGINT,
    comments        BIGINT,
    UNIQUE (platform_id, captured_at)
);

CREATE TABLE IF NOT EXISTS niches (
    id                  BIGSERIAL PRIMARY KEY,
    name                TEXT NOT NULL,
    demand_score        NUMERIC,
    saturation_score    NUMERIC,
    opportunity_score   NUMERIC,
    sample_channels     JSONB,
    computed_at         TIMESTAMPTZ DEFAULT now()
);

-- ============================================================
-- SISTEMA B: Fábrica de contenido
-- ============================================================

CREATE TABLE IF NOT EXISTS active_channels (
    id              BIGSERIAL PRIMARY KEY,
    name            TEXT NOT NULL,
    niche_id        BIGINT REFERENCES niches(id),
    style_config    JSONB,
    created_at      TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS topics (
    id                  BIGSERIAL PRIMARY KEY,
    active_channel_id   BIGINT REFERENCES active_channels(id) ON DELETE CASCADE,
    title               TEXT,
    source_ref          TEXT,
    trend_score         NUMERIC,
    status              TEXT DEFAULT 'pending' CHECK (status IN ('pending','selected','discarded')),
    detected_at         TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS videos (
    id                  BIGSERIAL PRIMARY KEY,
    topic_id            BIGINT REFERENCES topics(id),
    active_channel_id   BIGINT REFERENCES active_channels(id),
    status              TEXT DEFAULT 'queued' CHECK (status IN (
                            'queued','scripting','generating_assets',
                            'rendering','review','approved','rejected','published'
                        )),
    script              JSONB,
    metadata            JSONB,
    assets              JSONB,
    render_path         TEXT,
    audio_ref           TEXT,
    created_at          TIMESTAMPTZ DEFAULT now(),
    published_at        TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS video_results (
    id              BIGSERIAL PRIMARY KEY,
    video_id        BIGINT REFERENCES videos(id) ON DELETE CASCADE,
    captured_at     TIMESTAMPTZ DEFAULT now(),
    views           BIGINT,
    likes           BIGINT,
    comments        BIGINT,
    shares          BIGINT
);

-- ============================================================
-- Índices para queries frecuentes del radar
-- ============================================================

CREATE INDEX IF NOT EXISTS idx_channel_snapshots_channel_id ON channel_snapshots(channel_id);
CREATE INDEX IF NOT EXISTS idx_channel_snapshots_captured_at ON channel_snapshots(captured_at);
CREATE INDEX IF NOT EXISTS idx_observed_videos_channel_id ON observed_videos(channel_id);
CREATE INDEX IF NOT EXISTS idx_observed_videos_published_at ON observed_videos(published_at);
CREATE INDEX IF NOT EXISTS idx_videos_status ON videos(status);
CREATE INDEX IF NOT EXISTS idx_videos_active_channel ON videos(active_channel_id);
CREATE INDEX IF NOT EXISTS idx_topics_status ON topics(status);
