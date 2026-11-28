-- =============================================================================
-- CineTracker Indian Box Office Engine - Hardened Supabase / PostgreSQL Schema
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- -----------------------------------------------------------------------------
-- 1. Trigger helper for automatic updated_at maintenance
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.set_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

-- -----------------------------------------------------------------------------
-- 2. Master movies table (Strict Data Contract + Enrichment columns)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.movies (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    movie_slug          TEXT NOT NULL UNIQUE,
    title               TEXT NOT NULL,
    language            TEXT NOT NULL,
    original_language   TEXT,
    release_date        DATE,
    tmdb_id             BIGINT,
    poster_url          TEXT,
    backdrop_url        TEXT,
    trailer_youtube_id  TEXT,
    director            TEXT,
    synopsis            TEXT,
    cast_summary        TEXT,
    budget_cr           NUMERIC(12, 4) CHECK (budget_cr IS NULL OR budget_cr >= 0),
    india_net_cr        NUMERIC(12, 4) NOT NULL DEFAULT 0 CHECK (india_net_cr >= 0),
    india_gross_cr      NUMERIC(12, 4) CHECK (india_gross_cr IS NULL OR india_gross_cr >= 0),
    overseas_cr         NUMERIC(12, 4) CHECK (overseas_cr IS NULL OR overseas_cr >= 0),
    worldwide_gross_cr  NUMERIC(12, 4) CHECK (worldwide_gross_cr IS NULL OR worldwide_gross_cr >= 0),
    verdict             TEXT,
    day_count           INTEGER NOT NULL DEFAULT 0 CHECK (day_count >= 0),
    daily_breakdown     JSONB NOT NULL DEFAULT '[]'::jsonb,
    primary_source      TEXT NOT NULL DEFAULT 'cinetracker_bo',
    source_urls         TEXT[] NOT NULL DEFAULT '{}'::text[],
    variance_flag       BOOLEAN NOT NULL DEFAULT FALSE,
    manual_override     BOOLEAN NOT NULL DEFAULT FALSE,
    last_scraped_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE public.movies
    ADD COLUMN IF NOT EXISTS trailer_youtube_id TEXT,
    ADD COLUMN IF NOT EXISTS director TEXT,
    ADD COLUMN IF NOT EXISTS synopsis TEXT;

-- -----------------------------------------------------------------------------
-- 3. Normalized day-wise collections table
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.daily_collections (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    movie_id            UUID NOT NULL REFERENCES public.movies(id) ON DELETE CASCADE,
    movie_slug          TEXT NOT NULL,
    day_number          INTEGER NOT NULL CHECK (day_number >= 0),
    collection_date     DATE,
    india_net_cr        NUMERIC(12, 4) NOT NULL DEFAULT 0 CHECK (india_net_cr >= 0),
    change_pct          NUMERIC(8, 2),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_daily_collections_movie_day UNIQUE (movie_id, day_number)
);

-- -----------------------------------------------------------------------------
-- 4. Application configuration table (Admin-managed, selective public read)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.app_config (
    key                 TEXT PRIMARY KEY,
    value               JSONB NOT NULL DEFAULT '{}'::jsonb,
    is_public           BOOLEAN NOT NULL DEFAULT FALSE,
    description         TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO public.app_config (key, value, is_public, description)
VALUES
    ('brand_display', '{"name": "CineTracker", "tagline": "Live Indian & Malayalam Box Office Intelligence"}'::jsonb, TRUE, 'Public brand metadata'),
    ('api_cache_policy', '{"movies_ttl_sec": 60}'::jsonb, TRUE, 'Public cache telemetry configuration')
ON CONFLICT (key) DO NOTHING;

-- -----------------------------------------------------------------------------
-- 5. Performance indexes (<20ms targeted queries)
-- -----------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_movies_slug
    ON public.movies (movie_slug);

CREATE INDEX IF NOT EXISTS idx_movies_language
    ON public.movies (language);

CREATE INDEX IF NOT EXISTS idx_movies_language_last_scraped_desc
    ON public.movies (language, last_scraped_at DESC);

CREATE INDEX IF NOT EXISTS idx_movies_last_scraped_desc
    ON public.movies (last_scraped_at DESC);

CREATE INDEX IF NOT EXISTS idx_movies_release_date
    ON public.movies (release_date DESC NULLS LAST);

CREATE INDEX IF NOT EXISTS idx_movies_india_net
    ON public.movies (india_net_cr DESC);

CREATE INDEX IF NOT EXISTS idx_movies_worldwide_gross
    ON public.movies (worldwide_gross_cr DESC NULLS LAST);

CREATE INDEX IF NOT EXISTS idx_movies_tmdb_id
    ON public.movies (tmdb_id)
    WHERE tmdb_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_movies_variance_flag
    ON public.movies (variance_flag)
    WHERE variance_flag = TRUE;

CREATE INDEX IF NOT EXISTS idx_daily_collections_movie_day
    ON public.daily_collections (movie_id, day_number);

CREATE INDEX IF NOT EXISTS idx_daily_collections_slug
    ON public.daily_collections (movie_slug);

CREATE INDEX IF NOT EXISTS idx_daily_collections_date
    ON public.daily_collections (collection_date DESC NULLS LAST);

-- -----------------------------------------------------------------------------
-- 6. updated_at triggers
-- -----------------------------------------------------------------------------
DROP TRIGGER IF EXISTS trg_movies_set_updated_at ON public.movies;
CREATE TRIGGER trg_movies_set_updated_at
    BEFORE UPDATE ON public.movies
    FOR EACH ROW
    EXECUTE FUNCTION public.set_updated_at();

DROP TRIGGER IF EXISTS trg_daily_collections_set_updated_at ON public.daily_collections;
CREATE TRIGGER trg_daily_collections_set_updated_at
    BEFORE UPDATE ON public.daily_collections
    FOR EACH ROW
    EXECUTE FUNCTION public.set_updated_at();

DROP TRIGGER IF EXISTS trg_app_config_set_updated_at ON public.app_config;
CREATE TRIGGER trg_app_config_set_updated_at
    BEFORE UPDATE ON public.app_config
    FOR EACH ROW
    EXECUTE FUNCTION public.set_updated_at();

-- -----------------------------------------------------------------------------
-- 7. Strict Column-Level Grants & Row Level Security (RLS)
-- -----------------------------------------------------------------------------
ALTER TABLE public.movies ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.daily_collections ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.app_config ENABLE ROW LEVEL SECURITY;

-- Enforce least privilege: anon can ONLY SELECT non-sensitive public columns (no source_urls)
REVOKE ALL ON TABLE public.movies FROM PUBLIC, anon, authenticated;
GRANT SELECT (
    id,
    movie_slug,
    title,
    language,
    original_language,
    release_date,
    tmdb_id,
    poster_url,
    backdrop_url,
    trailer_youtube_id,
    director,
    synopsis,
    cast_summary,
    budget_cr,
    india_net_cr,
    india_gross_cr,
    overseas_cr,
    worldwide_gross_cr,
    verdict,
    day_count,
    daily_breakdown,
    primary_source,
    variance_flag,
    manual_override,
    last_scraped_at,
    created_at,
    updated_at
) ON TABLE public.movies TO anon;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.movies TO authenticated, service_role;

REVOKE ALL ON TABLE public.daily_collections FROM PUBLIC, anon, authenticated;
GRANT SELECT ON TABLE public.daily_collections TO anon;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.daily_collections TO authenticated, service_role;

REVOKE ALL ON TABLE public.app_config FROM PUBLIC, anon, authenticated;
GRANT SELECT (key, value, is_public, description, updated_at) ON TABLE public.app_config TO anon;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.app_config TO authenticated, service_role;

-- Movies RLS policies
DROP POLICY IF EXISTS "Allow public read access on movies" ON public.movies;
CREATE POLICY "Allow public read access on movies"
    ON public.movies
    FOR SELECT
    TO anon, authenticated
    USING (true);

DROP POLICY IF EXISTS "Allow authenticated admin writes on movies" ON public.movies;
DROP POLICY IF EXISTS "Allow authenticated admin insert on movies" ON public.movies;
CREATE POLICY "Allow authenticated admin insert on movies"
    ON public.movies
    FOR INSERT
    TO authenticated
    WITH CHECK (auth.role() = 'authenticated');

DROP POLICY IF EXISTS "Allow authenticated admin update on movies" ON public.movies;
CREATE POLICY "Allow authenticated admin update on movies"
    ON public.movies
    FOR UPDATE
    TO authenticated
    USING (auth.role() = 'authenticated')
    WITH CHECK (auth.role() = 'authenticated');

DROP POLICY IF EXISTS "Allow authenticated admin delete on movies" ON public.movies;
CREATE POLICY "Allow authenticated admin delete on movies"
    ON public.movies
    FOR DELETE
    TO authenticated
    USING (auth.role() = 'authenticated');

DROP POLICY IF EXISTS "Allow service_role full access on movies" ON public.movies;
CREATE POLICY "Allow service_role full access on movies"
    ON public.movies
    FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

-- Daily collections RLS policies
DROP POLICY IF EXISTS "Allow public read access on daily_collections" ON public.daily_collections;
CREATE POLICY "Allow public read access on daily_collections"
    ON public.daily_collections
    FOR SELECT
    TO anon, authenticated
    USING (true);

DROP POLICY IF EXISTS "Allow authenticated admin writes on daily_collections" ON public.daily_collections;
DROP POLICY IF EXISTS "Allow authenticated admin insert on daily_collections" ON public.daily_collections;
CREATE POLICY "Allow authenticated admin insert on daily_collections"
    ON public.daily_collections
    FOR INSERT
    TO authenticated
    WITH CHECK (auth.role() = 'authenticated');

DROP POLICY IF EXISTS "Allow authenticated admin update on daily_collections" ON public.daily_collections;
CREATE POLICY "Allow authenticated admin update on daily_collections"
    ON public.daily_collections
    FOR UPDATE
    TO authenticated
    USING (auth.role() = 'authenticated')
    WITH CHECK (auth.role() = 'authenticated');

DROP POLICY IF EXISTS "Allow authenticated admin delete on daily_collections" ON public.daily_collections;
CREATE POLICY "Allow authenticated admin delete on daily_collections"
    ON public.daily_collections
    FOR DELETE
    TO authenticated
    USING (auth.role() = 'authenticated');

DROP POLICY IF EXISTS "Allow service_role full access on daily_collections" ON public.daily_collections;
CREATE POLICY "Allow service_role full access on daily_collections"
    ON public.daily_collections
    FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

-- app_config RLS policies
DROP POLICY IF EXISTS "Allow public read of public app_config" ON public.app_config;
CREATE POLICY "Allow public read of public app_config"
    ON public.app_config
    FOR SELECT
    TO anon, authenticated
    USING (is_public = TRUE OR auth.role() = 'authenticated');

DROP POLICY IF EXISTS "Allow authenticated admin write on app_config" ON public.app_config;
CREATE POLICY "Allow authenticated admin write on app_config"
    ON public.app_config
    FOR ALL
    TO authenticated
    USING (auth.role() = 'authenticated')
    WITH CHECK (auth.role() = 'authenticated');

DROP POLICY IF EXISTS "Allow service_role full access on app_config" ON public.app_config;
CREATE POLICY "Allow service_role full access on app_config"
    ON public.app_config
    FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

-- Ensure Realtime Postgres Changes publication includes movies
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_publication_tables
        WHERE pubname = 'supabase_realtime'
          AND schemaname = 'public'
          AND tablename = 'movies'
    ) THEN
        ALTER PUBLICATION supabase_realtime ADD TABLE public.movies;
    END IF;
END;
$$;
