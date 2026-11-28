"""Zero-leak white-label sanitization utilities for public APIs, DB rows, reports, and logs."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

SOURCE_ALIAS_MAP: dict[str, str] = {
    "sacnilk": "cinetracker_bo",
    "sacnilk.com": "cinetracker_bo",
    "koimoi": "cinetracker_trade",
    "koimoi.com": "cinetracker_trade",
    "x": "cinetracker_pulse",
    "twitter": "cinetracker_pulse",
    "x_tracker": "cinetracker_pulse",
    "manual_admin": "cinetracker_editorial",
}

_SOURCE_URL_PATTERN = re.compile(
    r"https?://[^\s'\",\]\)]*(?:sacnilk|koimoi|twitter|x\.com|xcancel|nitter)[^\s'\",\]\)]*",
    re.IGNORECASE,
)

_BRAND_WORD_PATTERN = re.compile(
    r"\b(?:www\.)?(?:sacnilk(?:\.com)?|koimoi(?:\.com)?)\b",
    re.IGNORECASE,
)

# Public columns permitted for anon/client payloads (excludes source_urls & internal URLs)
PUBLIC_MOVIE_COLUMNS: tuple[str, ...] = (
    "id",
    "movie_slug",
    "title",
    "language",
    "original_language",
    "release_date",
    "tmdb_id",
    "poster_url",
    "backdrop_url",
    "trailer_youtube_id",
    "director",
    "synopsis",
    "cast_summary",
    "budget_cr",
    "india_net_cr",
    "india_gross_cr",
    "overseas_cr",
    "worldwide_gross_cr",
    "verdict",
    "day_count",
    "daily_breakdown",
    "primary_source",
    "variance_flag",
    "manual_override",
    "last_scraped_at",
    "created_at",
    "updated_at",
)

# Hosts whose poster CDN URLs should be neutralized or avoided in third-party leaks if needed;
# poster_url images are loaded strictly as image assets, while source_urls links are omitted.
_SENSITIVE_FIELDS = ("source_urls", "source_url")


def sanitize_source_name(source: str | None) -> str:
    """Normalize internal scraper source identifiers into white-labeled CineTracker labels."""
    if not source:
        return "cinetracker_bo"
    cleaned = str(source).strip().lower()
    if cleaned in SOURCE_ALIAS_MAP:
        return SOURCE_ALIAS_MAP[cleaned]
    if "sacnilk" in cleaned:
        return "cinetracker_bo"
    if "koimoi" in cleaned:
        return "cinetracker_trade"
    if cleaned in {"x", "twitter"} or "x_tracker" in cleaned or "nitter" in cleaned:
        return "cinetracker_pulse"
    return cleaned


def sanitize_whitelabel_text(text: str | None) -> str:
    """Scrub third-party tracker brand names and raw scrape URLs from text or log lines."""
    if not text:
        return ""
    scrubbed = _SOURCE_URL_PATTERN.sub("[redacted-feed-url]", str(text))
    scrubbed = _BRAND_WORD_PATTERN.sub(
        lambda m: "cinetracker_trade" if "koimoi" in m.group(0).lower() else "cinetracker_bo",
        scrubbed,
    )
    scrubbed = re.sub(r"\bscrapers\.x_tracker_scraper\b", "scrapers.pulse_feed", scrubbed)
    scrubbed = re.sub(r"\bscrapers\.sacnilk(?:_scraper)?\b", "scrapers.bo_feed", scrubbed)
    scrubbed = re.sub(r"\bscrapers\.koimoi(?:_scraper)?\b", "scrapers.trade_feed", scrubbed)
    return scrubbed


def sanitize_public_movie(row: dict[str, Any]) -> dict[str, Any]:
    """Return a clean white-labeled public movie payload with source_urls omitted."""
    cleaned: dict[str, Any] = {}
    for key, value in row.items():
        if key in _SENSITIVE_FIELDS:
            continue
        if key == "primary_source":
            cleaned[key] = sanitize_source_name(str(value) if value is not None else None)
        else:
            cleaned[key] = value
    if "primary_source" not in cleaned or not cleaned["primary_source"]:
        cleaned["primary_source"] = "cinetracker_bo"
    return cleaned


def sanitize_run_report(report: dict[str, Any] | None) -> dict[str, Any] | None:
    """White-label source keys, CLI args, and error URLs inside run reports exposed to Admin UI."""
    if not isinstance(report, dict):
        return None

    sanitized = dict(report)

    cli_args = sanitized.get("cli_args")
    if isinstance(cli_args, dict):
        cli_copy = dict(cli_args)
        if "source" in cli_copy and cli_copy["source"] != "all":
            cli_copy["source"] = sanitize_source_name(str(cli_copy["source"]))
        sanitized["cli_args"] = cli_copy

    sources = sanitized.get("sources")
    if isinstance(sources, dict):
        sanitized["sources"] = {
            sanitize_source_name(k): v for k, v in sources.items()
        }

    errors = sanitized.get("errors")
    if isinstance(errors, list):
        clean_errors: list[dict[str, Any]] = []
        for item in errors:
            if not isinstance(item, dict):
                continue
            err_copy = dict(item)
            if err_copy.get("source"):
                err_copy["source"] = sanitize_source_name(str(err_copy["source"]))
            if err_copy.get("url"):
                parsed = urlparse(str(err_copy["url"]))
                err_copy["url"] = f"{parsed.scheme}://redacted-source{parsed.path}" if parsed.scheme else "[redacted-url]"
            if err_copy.get("message"):
                err_copy["message"] = sanitize_whitelabel_text(str(err_copy["message"]))
            clean_errors.append(err_copy)
        sanitized["errors"] = clean_errors

    return sanitized
