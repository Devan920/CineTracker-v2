"""Backfill missing poster_url, backdrop_url, and trailer_youtube_id on Supabase rows.

Usage:
    python scraper/backfill_posters.py [--limit 100] [--force]
"""

from __future__ import annotations

import argparse
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import httpx
from bs4 import BeautifulSoup
from supabase import create_client

SCRAPER_DIR = Path(__file__).resolve().parent
if str(SCRAPER_DIR) not in sys.path:
    sys.path.insert(0, str(SCRAPER_DIR))

from config.settings import get_settings  # noqa: E402
from enrichment.tmdb_client import TMDBClient  # noqa: E402
from scrapers.sacnilk_scraper import SacnilkScraper  # noqa: E402
from utils.logger import get_logger  # noqa: E402

logger = get_logger("backfill_posters")


def _extract_sacnilk_poster(
    client: httpx.Client,
    sacnilk_helper: SacnilkScraper,
    source_urls: list[str],
) -> str | None:
    sac_urls = [u for u in source_urls if "sacnilk.com/movie/" in u.lower()]
    if not sac_urls:
        return None
    for url in sac_urls[:2]:
        try:
            resp = client.get(url)
            if resp.status_code != 200 or not resp.text:
                continue
            soup = BeautifulSoup(resp.text, "html.parser")
            poster = sacnilk_helper._extract_poster_url(soup)
            if poster:
                return poster
        except Exception as exc:
            logger.debug("Sacnilk poster fetch skipped for %s: %s", url, exc)
    return None


def backfill_missing_posters(
    *,
    limit: int | None = None,
    force: bool = False,
    workers: int = 4,
    include_trailers: bool = True,
) -> dict[str, int]:
    """Resolve and patch missing poster_url, backdrop_url, and trailer_youtube_id in Supabase."""
    settings = get_settings()
    settings.validate_environment(require_supabase=True, require_tmdb=False)
    assert settings.supabase_url and settings.supabase_key

    sb = create_client(settings.supabase_url, settings.supabase_key)

    has_trailer_col = True
    select_cols = (
        "movie_slug,title,language,release_date,poster_url,backdrop_url,"
        "trailer_youtube_id,tmdb_id,cast_summary,source_urls"
    )
    try:
        sb.table("movies").select("trailer_youtube_id").limit(1).execute()
    except Exception:
        has_trailer_col = False
        select_cols = (
            "movie_slug,title,language,release_date,poster_url,backdrop_url,"
            "tmdb_id,cast_summary,source_urls"
        )
        logger.warning(
            "Column 'movies.trailer_youtube_id' not yet present in Supabase; "
            "run `ALTER TABLE public.movies ADD COLUMN IF NOT EXISTS trailer_youtube_id TEXT;` to persist trailers. "
            "Trailer IDs will still be cached locally in tmdb_cache.json."
        )

    all_rows: list[dict[str, Any]] = []
    offset = 0
    page_size = 500
    while True:
        resp = (
            sb.table("movies")
            .select(select_cols)
            .order("india_net_cr", desc=True)
            .range(offset, offset + page_size - 1)
            .execute()
        )
        batch = getattr(resp, "data", None) or []
        all_rows.extend(batch)
        if len(batch) < page_size:
            break
        offset += page_size

    targets = [
        row
        for row in all_rows
        if force
        or not row.get("poster_url")
        or not row.get("backdrop_url")
        or (include_trailers and has_trailer_col and not row.get("trailer_youtube_id"))
    ]
    if limit is not None and limit > 0:
        targets = targets[:limit]

    stats = {
        "total_scanned": len(all_rows),
        "targets": len(targets),
        "updated": 0,
        "tier1_tmdb": 0,
        "tier2_sacnilk": 0,
        "tier3_wikipedia": 0,
        "trailers_resolved": 0,
        "unresolved": 0,
    }
    if not targets:
        logger.info("All %d Supabase movie rows already have posters and trailers.", len(all_rows))
        return stats

    logger.info("Backfilling media for %d/%d Supabase movie rows...", len(targets), len(all_rows))
    sacnilk_helper = SacnilkScraper(settings=settings)
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        )
    }

    def _resolve_row(row: dict[str, Any]) -> tuple[str, dict[str, Any] | None, str, bool]:
        title = str(row.get("title") or "").strip()
        language = str(row.get("language") or "Hindi")
        rel_date = row.get("release_date")
        rel_year = (
            int(rel_date[:4])
            if isinstance(rel_date, str) and len(rel_date) >= 4 and rel_date[:4].isdigit()
            else None
        )
        source_urls = row.get("source_urls") if isinstance(row.get("source_urls"), list) else []

        poster_url: str | None = row.get("poster_url") if not force else None
        backdrop_url: str | None = row.get("backdrop_url") if not force else None
        trailer_id: str | None = row.get("trailer_youtube_id") if not force else None
        tmdb_id: int | None = row.get("tmdb_id")
        cast_summary: str | None = row.get("cast_summary")
        tier = "none"
        trailer_found = False

        with TMDBClient(settings=settings) as tmdb_client, httpx.Client(
            timeout=12.0, follow_redirects=True, headers=headers
        ) as page_client:
            # Tier 1: TMDB (Poster + Backdrop + Videos Trailer)
            meta, _, _ = tmdb_client.lookup(title, release_year=rel_year, language=language)
            if meta:
                if meta.poster_url and not poster_url:
                    poster_url = meta.poster_url
                    backdrop_url = meta.backdrop_url or backdrop_url or poster_url
                    tier = "tier1_tmdb"
                tmdb_id = meta.tmdb_id or tmdb_id
                cast_summary = meta.cast_summary or cast_summary
                if meta.trailer_youtube_id and not trailer_id:
                    trailer_id = meta.trailer_youtube_id
                    trailer_found = True

            # Tier 2: Sacnilk page og:image / poster img
            if not poster_url:
                sac_poster = _extract_sacnilk_poster(page_client, sacnilk_helper, source_urls)
                if sac_poster:
                    poster_url = sac_poster
                    backdrop_url = backdrop_url or sac_poster
                    tier = "tier2_sacnilk"

            # Tier 3: Wikipedia free MediaWiki API
            if not poster_url:
                wiki_poster, wiki_bg, _, _ = tmdb_client.lookup_wikipedia(
                    title, release_year=rel_year, language=language
                )
                if wiki_poster:
                    poster_url = wiki_poster
                    backdrop_url = backdrop_url or wiki_bg or wiki_poster
                    tier = "tier3_wikipedia"

            # YouTube fallback trailer search
            if include_trailers and not trailer_id:
                yt_id, _, _ = tmdb_client.lookup_youtube_trailer(
                    title, release_year=rel_year, language=language
                )
                if yt_id:
                    trailer_id = yt_id
                    trailer_found = True

        if poster_url and not backdrop_url:
            backdrop_url = poster_url

        patch: dict[str, Any] = {}
        if poster_url and poster_url != row.get("poster_url"):
            patch["poster_url"] = poster_url
        if backdrop_url and backdrop_url != row.get("backdrop_url"):
            patch["backdrop_url"] = backdrop_url
        if tmdb_id and tmdb_id != row.get("tmdb_id"):
            patch["tmdb_id"] = tmdb_id
        if cast_summary and not row.get("cast_summary"):
            patch["cast_summary"] = cast_summary
        if has_trailer_col and trailer_id and trailer_id != row.get("trailer_youtube_id"):
            patch["trailer_youtube_id"] = trailer_id

        time.sleep(0.15)
        return row["movie_slug"], (patch or None), tier, trailer_found

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = [pool.submit(_resolve_row, row) for row in targets]
        for idx, fut in enumerate(as_completed(futures), start=1):
            try:
                slug, patch, tier, trailer_found = fut.result()
                if trailer_found:
                    stats["trailers_resolved"] += 1
                if patch:
                    sb.table("movies").update(patch).eq("movie_slug", slug).execute()
                    stats["updated"] += 1
                    if tier in stats:
                        stats[tier] += 1
                elif not trailer_found:
                    stats["unresolved"] += 1
            except Exception as exc:
                stats["unresolved"] += 1
                logger.warning("Backfill failed on row: %s", exc)
            if idx % 25 == 0 or idx == len(targets):
                logger.info(
                    "Backfill progress: %d/%d (updated=%d, trailers=%d, sacnilk=%d, wiki=%d)",
                    idx,
                    len(targets),
                    stats["updated"],
                    stats["trailers_resolved"],
                    stats["tier2_sacnilk"],
                    stats["tier3_wikipedia"],
                )

    logger.info("Backfill complete: %s", stats)
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill missing movie posters and trailers in Supabase.")
    parser.add_argument("--limit", type=int, default=None, help="Maximum rows to process.")
    parser.add_argument("--force", action="store_true", help="Re-check rows that already have media.")
    parser.add_argument("--workers", type=int, default=4, help="Concurrent HTTP workers.")
    parser.add_argument("--no-trailers", action="store_true", help="Skip YouTube trailer resolution.")
    args = parser.parse_args()
    backfill_missing_posters(
        limit=args.limit,
        force=args.force,
        workers=args.workers,
        include_trailers=not args.no_trailers,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
