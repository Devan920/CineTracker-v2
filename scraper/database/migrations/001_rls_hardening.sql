-- =============================================================================
-- Migration 001: Supabase RLS Hardening, app_config, Indexes & White-Label Sync
-- Safe to run multiple times (idempotent) in the Supabase SQL Editor.
-- =============================================================================

ALTER TABLE public.movies
    ADD COLUMN IF NOT EXISTS trailer_youtube_id TEXT,
    ADD COLUMN IF NOT EXISTS director TEXT,
    ADD COLUMN IF NOT EXISTS synopsis TEXT;

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

CREATE INDEX IF NOT EXISTS idx_movies_slug
    ON public.movies (movie_slug);

CREATE INDEX IF NOT EXISTS idx_movies_language_last_scraped_desc
    ON public.movies (language, last_scraped_at DESC);

CREATE INDEX IF NOT EXISTS idx_movies_last_scraped_desc
    ON public.movies (last_scraped_at DESC);

DROP TRIGGER IF EXISTS trg_app_config_set_updated_at ON public.app_config;
CREATE TRIGGER trg_app_config_set_updated_at
    BEFORE UPDATE ON public.app_config
    FOR EACH ROW
    EXECUTE FUNCTION public.set_updated_at();

-- Sanitize legacy third-party source identifiers inside DB rows
UPDATE public.movies
SET primary_source = CASE LOWER(primary_source)
    WHEN 'sacnilk' THEN 'cinetracker_bo'
    WHEN 'koimoi' THEN 'cinetracker_trade'
    WHEN 'x' THEN 'cinetracker_pulse'
    WHEN 'twitter' THEN 'cinetracker_pulse'
    ELSE primary_source
END
WHERE LOWER(primary_source) IN ('sacnilk', 'koimoi', 'x', 'twitter');

ALTER TABLE public.movies ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.daily_collections ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.app_config ENABLE ROW LEVEL SECURITY;

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
