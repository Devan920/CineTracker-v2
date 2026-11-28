"""Multi-tier movie metadata & cover art enrichment client (TMDB v3 -> Sacnilk -> Wikipedia)."""

from __future__ import annotations

import json
import re
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from config.settings import Settings, get_settings
from utils.logger import get_logger
from utils.models import MovieBoxOfficeRecord
from utils.title_matcher import TitleMatcher, normalize_title

logger = get_logger("enrichment.tmdb")

TMDB_API_BASE = "https://api.themoviedb.org/3"
TMDB_POSTER_BASE = "https://image.tmdb.org/t/p/w500"
TMDB_BACKDROP_BASE = "https://image.tmdb.org/t/p/w1280"
WIKIPEDIA_API_URL = "https://en.wikipedia.org/w/api.php"
YOUTUBE_SEARCH_URL = "https://www.youtube.com/results"

_YT_RENDERER_RE = re.compile(
    r'"videoRenderer":\{"videoId":"([A-Za-z0-9_-]{11})".*?"title":\{"runs":\[\{"text":"([^"\\]*(?:\\.[^"\\]*)*)"',
    re.DOTALL,
)
_YT_SKIP_TITLE_RE = re.compile(
    r"\b(?:reaction|review|explained|breakdown|roast|spoof|parody|fan[\s\-]*made|concept|interview|box\s*office|full\s*movie|making|jukebox)\b",
    re.IGNORECASE,
)

_NOISE_TAGS_RE = re.compile(
    r"[\(\[\{]\s*(?:hindi|malayalam|tamil|telugu|kannada|english|marathi|punjabi|bengali|"
    r"pan[- ]india|dubbed|3d|imax|4dx|uhd|day\s*\d+|20\d{2}|19\d{2})\s*[\)\]\}]",
    re.IGNORECASE,
)
_DAY_SUFFIX_RE = re.compile(r"\b(?:day\s*\d+|box\s+office(?:\s+collection)?|live|estimate)\b.*$", re.I)
_YEAR_SUFFIX_RE = re.compile(r"[\s\-:]+(?:20\d{2}|19\d{2})\s*$")
_REGIONAL_SUFFIX_RE = re.compile(
    r"[\s\-:]+(?:hindi|malayalam|tamil|telugu|kannada|english|marathi|punjabi|bengali|"
    r"pan[- ]india|dubbed|movie|film)\s*$",
    re.IGNORECASE,
)
_PART_SUFFIX_RE = re.compile(r"[\s\-:]+(?:part|chapter|vol\.?|volume)\s*(?:1|i|one)\s*$", re.I)
_WIKI_SKIP_TITLE_RE = re.compile(
    r"\((?:soundtrack|novel|book|album|song|character|disambiguation|franchise|tv\s+series)\)|"
    r"^(?:production of|discography|filmography|list of)\b",
    re.IGNORECASE,
)
_BAD_IMAGE_RE = re.compile(
    r"(?:\.svg(?:\?|$)|flag_of_|commons-logo|edit-clear|ambox|symbol_|question_book|no_image|placeholder)",
    re.IGNORECASE,
)


def build_fuzzy_title_variants(title: str) -> list[str]:
    """Generate progressively simpler search queries by stripping years, language tags, Day N, and suffixes."""
    raw = str(title or "").strip()
    if not raw:
        return []

    cleaned = _NOISE_TAGS_RE.sub(" ", raw)
    cleaned = _DAY_SUFFIX_RE.sub("", cleaned)
    cleaned = _YEAR_SUFFIX_RE.sub("", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" :-–—")

    variants: list[str] = []
    for cand in (
        cleaned,
        _REGIONAL_SUFFIX_RE.sub("", cleaned).strip(" :-–—"),
    ):
        if cand and cand not in variants:
            variants.append(cand)

    no_part = _PART_SUFFIX_RE.sub("", variants[-1]).strip(" :-–—") if variants else ""
    if no_part and no_part not in variants:
        variants.append(no_part)

    # Also try base title before subtitle delimiters like ":" or " - "
    if variants:
        base_split = re.split(r"\s*(?::|—|–|\s-\s)\s*", variants[0], maxsplit=1)[0].strip()
        if len(base_split) >= 2 and base_split not in variants:
            variants.append(base_split)

    norm_sub = normalize_title(raw, strip_subtitle=True)
    if norm_sub and norm_sub.lower() not in {v.lower() for v in variants}:
        variants.append(norm_sub)

    return variants or [raw]

LANGUAGE_TO_ISO: dict[str, str] = {
    "malayalam": "ml",
    "tamil": "ta",
    "hindi": "hi",
    "telugu": "te",
    "kannada": "kn",
    "english": "en",
    "marathi": "mr",
    "bengali": "bn",
    "punjabi": "pa",
    "gujarati": "gu",
}

ISO_TO_LANGUAGE: dict[str, str] = {v: k.title() for k, v in LANGUAGE_TO_ISO.items()}


class _TMDBTransientError(RuntimeError):
    """Transient HTTP error eligible for exponential backoff retry."""


@dataclass
class TMDBMetadata:
    """Normalized metadata resolved from TMDB."""

    tmdb_id: int | None = None
    poster_url: str | None = None
    backdrop_url: str | None = None
    trailer_youtube_id: str | None = None
    cast_summary: str | None = None
    original_language: str | None = None
    release_date: str | None = None
    matched_title: str | None = None
    match_score: float = 0.0


_CACHE_IO_LOCK = threading.Lock()


class TMDBClient:
    """Fuzzy-matching TMDB client backed by local JSON caching."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        cache_path: Path | None = None,
        settings: Settings | None = None,
        http_client: httpx.Client | None = None,
        wiki_http_client: httpx.Client | None = None,
        youtube_http_client: httpx.Client | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.api_key = api_key if api_key is not None else self.settings.tmdb_api_key
        if self.settings._is_placeholder(self.api_key):
            self.api_key = None

        self.cache_path = cache_path or self.settings.tmdb_cache_path
        self.matcher = TitleMatcher(threshold=74.0)
        self._owns_client = http_client is None
        self._client = http_client or httpx.Client(
            base_url=TMDB_API_BASE,
            timeout=self.settings.request_timeout_sec,
            headers={"Accept": "application/json"},
        )
        self._owns_wiki_client = wiki_http_client is None
        self._wiki_client = wiki_http_client or httpx.Client(
            timeout=self.settings.request_timeout_sec,
            follow_redirects=True,
            headers={
                "User-Agent": "CineTrackerV3/1.0 (https://cinetracker.local; boxoffice@cinetracker.local)",
                "Accept": "application/json",
            },
        )
        self._owns_yt_client = youtube_http_client is None
        self._youtube_client = youtube_http_client or httpx.Client(
            timeout=min(15, self.settings.request_timeout_sec),
            follow_redirects=True,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
                ),
                "Accept-Language": "en-US,en;q=0.9",
            },
        )
        self._cache: dict[str, dict[str, Any]] = self._load_cache()
        self._warned_no_key = False

    def close(self) -> None:
        if self._owns_client:
            self._client.close()
        if self._owns_wiki_client:
            self._wiki_client.close()
        if self._owns_yt_client:
            self._youtube_client.close()

    def __enter__(self) -> "TMDBClient":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.close()

    def _load_cache(self) -> dict[str, dict[str, Any]]:
        if not self.cache_path.exists():
            return {}
        try:
            with _CACHE_IO_LOCK:
                raw = json.loads(self.cache_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                return raw
        except Exception as exc:
            logger.warning("Failed to read TMDB cache '%s': %s. Starting fresh.", self.cache_path, exc)
        return {}

    def save_cache(self) -> None:
        """Atomically persist local TMDB cache JSON to disk (thread-safe on Windows)."""
        with _CACHE_IO_LOCK:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            disk_cache: dict[str, dict[str, Any]] = {}
            if self.cache_path.exists():
                try:
                    loaded = json.loads(self.cache_path.read_text(encoding="utf-8"))
                    if isinstance(loaded, dict):
                        disk_cache.update(loaded)
                except Exception:
                    pass
            disk_cache.update(self._cache)
            self._cache = disk_cache
            tmp_path = self.cache_path.with_name(f"{self.cache_path.stem}.{uuid.uuid4().hex[:8]}.tmp")
            tmp_path.write_text(
                json.dumps(disk_cache, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            tmp_path.replace(self.cache_path)

    @staticmethod
    def _build_cache_key(title: str, year: int | None, language: str | None) -> str:
        norm = normalize_title(title, strip_subtitle=False)
        lang_iso = LANGUAGE_TO_ISO.get((language or "").strip().lower(), "")
        return f"{norm}|{year or ''}|{lang_iso}"

    def _is_cache_entry_fresh(self, entry: dict[str, Any]) -> bool:
        cached_at_str = entry.get("cached_at")
        if not cached_at_str:
            return False
        try:
            cached_at = datetime.fromisoformat(cached_at_str)
            if cached_at.tzinfo is None:
                cached_at = cached_at.replace(tzinfo=timezone.utc)
        except ValueError:
            return False

        # Retry negative misses faster (24h) than positive matches (configured TTL)
        is_positive = (
            entry.get("tmdb_id") is not None
            or bool(entry.get("poster_url"))
            or bool(entry.get("trailer_youtube_id"))
        )
        ttl_hours = (
            self.settings.tmdb_cache_ttl_hours
            if is_positive
            else min(24, self.settings.tmdb_cache_ttl_hours)
        )
        return datetime.now(timezone.utc) - cached_at < timedelta(hours=ttl_hours)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1.5, min=1, max=12),
        retry=retry_if_exception_type((_TMDBTransientError, httpx.TransportError)),
        reraise=True,
    )
    def _tmdb_get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        merged = {"api_key": self.api_key, **params}
        response = self._client.get(path, params=merged)
        if response.status_code in {429, 500, 502, 503, 504}:
            raise _TMDBTransientError(
                f"TMDB transient HTTP {response.status_code} on {path}"
            )
        response.raise_for_status()
        return response.json()

    def _score_candidate(
        self,
        *,
        query_title: str,
        expected_year: int | None,
        expected_lang_iso: str | None,
        candidate: dict[str, Any],
    ) -> float:
        title_score = self.matcher.similarity(
            query_title, candidate.get("title") or ""
        )
        orig_score = self.matcher.similarity(
            query_title, candidate.get("original_title") or ""
        )
        score = max(title_score, orig_score)
        if score <= 0:
            return 0.0

        release_str = candidate.get("release_date") or ""
        cand_year = None
        if len(release_str) >= 4 and release_str[:4].isdigit():
            cand_year = int(release_str[:4])

        if expected_year and cand_year:
            diff = abs(cand_year - expected_year)
            if diff == 0:
                score += 8.0
            elif diff == 1:
                score += 4.0
            elif diff >= 3:
                score -= 22.0

        cand_lang = (candidate.get("original_language") or "").lower()
        if expected_lang_iso and cand_lang == expected_lang_iso:
            score += 6.0

        # Tiny popularity tie-breaker (bounded to +2)
        popularity = float(candidate.get("popularity") or 0.0)
        score += min(2.0, popularity / 50.0)
        return round(min(100.0, max(0.0, score)), 2)

    def lookup(
        self,
        title: str,
        *,
        release_year: int | None = None,
        language: str | None = None,
    ) -> tuple[TMDBMetadata | None, bool, bool]:
        """Search and match a movie on TMDB.

        Returns:
            (metadata_or_none, cache_hit, api_called)
        """
        cache_key = self._build_cache_key(title, release_year, language)
        cached = self._cache.get(cache_key)
        if cached and self._is_cache_entry_fresh(cached):
            if cached.get("tmdb_id") is None:
                return None, True, False
            return (
                TMDBMetadata(
                    tmdb_id=cached.get("tmdb_id"),
                    poster_url=cached.get("poster_url"),
                    backdrop_url=cached.get("backdrop_url"),
                    trailer_youtube_id=cached.get("trailer_youtube_id"),
                    cast_summary=cached.get("cast_summary"),
                    original_language=cached.get("original_language"),
                    release_date=cached.get("release_date"),
                    matched_title=cached.get("matched_title"),
                    match_score=float(cached.get("match_score") or 0.0),
                ),
                True,
                False,
            )

        if not self.api_key:
            if not self._warned_no_key:
                logger.warning(
                    "TMDB_API_KEY not configured; skipping live TMDB API lookups (cache-only mode)."
                )
                self._warned_no_key = True
            return None, False, False

        expected_lang_iso = LANGUAGE_TO_ISO.get((language or "").strip().lower())
        search_queries = build_fuzzy_title_variants(title)
        primary_query = search_queries[0] if search_queries else title

        candidates: list[dict[str, Any]] = []
        for q in search_queries:
            params: dict[str, Any] = {"query": q, "include_adult": "false"}
            if release_year:
                params["year"] = release_year
            payload = self._tmdb_get("/search/movie", params)
            results = payload.get("results") or []
            candidates.extend(results)
            if results:
                break

        # Retry without strict year filter if year-filtered search returned empty
        if not candidates and release_year:
            for q in search_queries:
                payload = self._tmdb_get(
                    "/search/movie", {"query": q, "include_adult": "false"}
                )
                results = payload.get("results") or []
                if results:
                    candidates.extend(results)
                    break

        best_candidate: dict[str, Any] | None = None
        best_score = 0.0
        for cand in candidates:
            sc = self._score_candidate(
                query_title=primary_query,
                expected_year=release_year,
                expected_lang_iso=expected_lang_iso,
                candidate=cand,
            )
            if sc > best_score:
                best_score = sc
                best_candidate = cand

        if not best_candidate or best_score < 74.0:
            self._cache[cache_key] = {
                "tmdb_id": None,
                "cached_at": datetime.now(timezone.utc).isoformat(),
            }
            self.save_cache()
            return None, False, True

        tmdb_id = int(best_candidate["id"])
        details = self._tmdb_get(
            f"/movie/{tmdb_id}", {"append_to_response": "credits,videos"}
        )

        videos_payload = details.get("videos")
        if not isinstance(videos_payload, dict) or "results" not in videos_payload:
            try:
                videos_payload = self._tmdb_get(f"/movie/{tmdb_id}/videos", {})
            except Exception:
                videos_payload = {}
        trailer_youtube_id = self._extract_best_youtube_trailer(videos_payload)

        poster_path = details.get("poster_path") or best_candidate.get("poster_path")
        backdrop_path = details.get("backdrop_path") or best_candidate.get("backdrop_path")
        cast_items = (details.get("credits") or {}).get("cast") or []
        top_cast = [
            member.get("name", "").strip()
            for member in cast_items[:5]
            if member.get("name")
        ]
        orig_lang_iso = (
            details.get("original_language")
            or best_candidate.get("original_language")
            or expected_lang_iso
        )
        orig_lang_display = ISO_TO_LANGUAGE.get(
            (orig_lang_iso or "").lower(), orig_lang_iso
        )

        meta = TMDBMetadata(
            tmdb_id=tmdb_id,
            poster_url=f"{TMDB_POSTER_BASE}{poster_path}" if poster_path else None,
            backdrop_url=f"{TMDB_BACKDROP_BASE}{backdrop_path}" if backdrop_path else None,
            trailer_youtube_id=trailer_youtube_id,
            cast_summary=", ".join(top_cast) if top_cast else None,
            original_language=orig_lang_display,
            release_date=details.get("release_date") or best_candidate.get("release_date") or None,
            matched_title=details.get("title") or best_candidate.get("title"),
            match_score=best_score,
        )

        self._cache[cache_key] = {
            "tmdb_id": meta.tmdb_id,
            "poster_url": meta.poster_url,
            "backdrop_url": meta.backdrop_url,
            "trailer_youtube_id": meta.trailer_youtube_id,
            "cast_summary": meta.cast_summary,
            "original_language": meta.original_language,
            "release_date": meta.release_date,
            "matched_title": meta.matched_title,
            "match_score": meta.match_score,
            "cached_at": datetime.now(timezone.utc).isoformat(),
        }
        self.save_cache()
        return meta, False, True

    @staticmethod
    def _extract_best_youtube_trailer(videos_payload: dict[str, Any] | None) -> str | None:
        """Select official YouTube Trailer key from TMDB /videos payload."""
        results = (videos_payload or {}).get("results") or []
        trailers = [
            v
            for v in results
            if isinstance(v, dict)
            and str(v.get("site") or "").strip().lower() == "youtube"
            and str(v.get("type") or "").strip().lower() == "trailer"
            and v.get("key")
        ]
        if not trailers:
            return None
        trailers.sort(key=lambda v: (not bool(v.get("official")),))
        return str(trailers[0]["key"]).strip() or None

    def _score_youtube_result(
        self,
        *,
        clean_title: str,
        raw_video_title: str,
        release_year: int | None,
    ) -> float:
        try:
            video_title = json.loads(f'"{raw_video_title}"')
        except Exception:
            video_title = raw_video_title

        if not video_title or _YT_SKIP_TITLE_RE.search(video_title):
            return 0.0

        low = video_title.lower()
        clean_norm = normalize_title(clean_title, strip_subtitle=False)
        clean_tokens = [tok for tok in clean_norm.split() if len(tok) >= 2]
        vid_norm = normalize_title(video_title, strip_subtitle=False)
        if not vid_norm:
            return 0.0

        # Ensure every significant title token (or high fuzzy match) appears in the YouTube result title
        token_hits = sum(1 for tok in clean_tokens if tok in vid_norm.split() or tok in vid_norm)
        token_coverage = (token_hits / len(clean_tokens)) if clean_tokens else 0.0
        if token_coverage < 0.7:
            return 0.0

        score = token_coverage * 65.0
        if "official trailer" in low:
            score += 22.0
        elif "trailer" in low:
            score += 14.0
        elif "teaser" in low:
            score += 6.0
        if release_year and str(release_year) in low:
            score += 6.0
        return round(min(100.0, score), 2)

    def lookup_youtube_trailer(
        self,
        title: str,
        *,
        release_year: int | None = None,
        language: str | None = None,
    ) -> tuple[str | None, bool, bool]:
        """Fallback trailer search returning (youtube_video_id, cache_hit, api_called)."""
        variants = build_fuzzy_title_variants(title)
        primary_clean = variants[0] if variants else title
        yt_key = f"yt|{self._build_cache_key(primary_clean, release_year, language)}"
        cached = self._cache.get(yt_key)
        if cached and self._is_cache_entry_fresh(cached):
            return cached.get("trailer_youtube_id"), True, False

        yr_part = f" {release_year}" if release_year else ""
        lang_clean = (language or "").strip()
        queries: list[str] = []
        if lang_clean and lang_clean.lower() not in {"pan-india", "english", "all"}:
            queries.append(f"{primary_clean} {lang_clean}{yr_part} Official Trailer")
        queries.append(f"{primary_clean}{yr_part} Official Trailer")
        if yr_part:
            queries.append(f"{primary_clean} Official Trailer")

        best_id: str | None = None
        best_score = 0.0
        api_called = False

        for q in queries:
            try:
                api_called = True
                resp = self._youtube_client.get(YOUTUBE_SEARCH_URL, params={"search_query": q})
                resp.raise_for_status()
            except Exception as exc:
                logger.debug("YouTube search failed for '%s' (%s): %s", title, q, exc)
                continue

            for vid_id, vid_title in _YT_RENDERER_RE.findall(resp.text)[:8]:
                sc = self._score_youtube_result(
                    clean_title=primary_clean,
                    raw_video_title=vid_title,
                    release_year=release_year,
                )
                if sc > best_score:
                    best_score = sc
                    best_id = vid_id

            if best_id and best_score >= 78.0:
                break

        resolved_id = best_id if best_score >= 68.0 else None
        self._cache[yt_key] = {
            "trailer_youtube_id": resolved_id,
            "match_score": best_score,
            "cached_at": datetime.now(timezone.utc).isoformat(),
        }
        self.save_cache()
        return resolved_id, False, api_called

    def _score_wikipedia_page(
        self,
        *,
        clean_title: str,
        release_year: int | None,
        language: str | None,
        page: dict[str, Any],
    ) -> float:
        page_title = str(page.get("title") or "").strip()
        if not page_title or _WIKI_SKIP_TITLE_RE.search(page_title):
            return 0.0

        thumb = (page.get("thumbnail") or {}).get("source") or ""
        orig = (page.get("original") or {}).get("source") or ""
        img_url = thumb or orig
        if not img_url or _BAD_IMAGE_RE.search(img_url):
            return 0.0

        base_page_title = re.sub(r"\s*\([^)]*\)\s*$", "", page_title).strip()
        sim = self.matcher.similarity(clean_title, base_page_title)
        # Allow Wikipedia subtitle matches like "Aadu 3: One Last Ride" vs "Aadu 3"
        if ":" in base_page_title and sim < 75.0:
            left_part = base_page_title.split(":", 1)[0].strip()
            sim = max(sim, self.matcher.similarity(clean_title, left_part) - 2.0)

        if sim < 60.0:
            return 0.0

        lower_pt = page_title.lower()
        score = sim
        if "film)" in lower_pt:
            score += 10.0
        if release_year and str(release_year) in lower_pt:
            score += 6.0
        if language and language.lower() != "pan-india" and language.lower() in lower_pt:
            score += 4.0
        return round(min(100.0, score), 2)

    def lookup_wikipedia(
        self,
        title: str,
        *,
        release_year: int | None = None,
        language: str | None = None,
    ) -> tuple[str | None, str | None, bool, bool]:
        """Tier-3 MediaWiki/Wikipedia public API fallback returning (poster_url, backdrop_url, cache_hit, api_called)."""
        variants = build_fuzzy_title_variants(title)
        primary_clean = variants[0] if variants else title
        wiki_key = f"wiki|{self._build_cache_key(primary_clean, release_year, language)}"
        cached = self._cache.get(wiki_key)
        if cached and self._is_cache_entry_fresh(cached):
            return cached.get("poster_url"), cached.get("backdrop_url"), True, False

        queries: list[str] = []
        if release_year:
            queries.append(f"{primary_clean} ({release_year} film)")
        if language and language.strip().lower() not in {"", "pan-india"}:
            queries.append(f"{primary_clean} ({language.strip()} film)")
        queries.append(f"{primary_clean} film")
        for v in variants[1:3]:
            q_v = f"{v} film"
            if q_v not in queries:
                queries.append(q_v)

        best_page: dict[str, Any] | None = None
        best_score = 0.0
        api_called = False

        for q in queries:
            try:
                api_called = True
                resp = self._wiki_client.get(
                    WIKIPEDIA_API_URL,
                    params={
                        "action": "query",
                        "generator": "search",
                        "gsrsearch": q,
                        "gsrlimit": 4,
                        "prop": "pageimages",
                        "pilicense": "any",
                        "piprop": "original|thumbnail",
                        "pithumbsize": 600,
                        "format": "json",
                    },
                )
                resp.raise_for_status()
                pages_dict = (resp.json().get("query") or {}).get("pages") or {}
            except Exception as exc:
                logger.debug("Wikipedia lookup failed for '%s' (%s): %s", title, q, exc)
                continue

            for page in pages_dict.values():
                sc = self._score_wikipedia_page(
                    clean_title=primary_clean,
                    release_year=release_year,
                    language=language,
                    page=page,
                )
                if sc > best_score:
                    best_score = sc
                    best_page = page

            if best_page is not None and best_score >= 82.0:
                break

        poster_url: str | None = None
        backdrop_url: str | None = None
        if best_page is not None and best_score >= 68.0:
            thumb_src = (best_page.get("thumbnail") or {}).get("source")
            orig_src = (best_page.get("original") or {}).get("source")
            chosen_poster = thumb_src or orig_src
            if chosen_poster and not _BAD_IMAGE_RE.search(chosen_poster):
                poster_url = chosen_poster
                backdrop_url = chosen_poster

        self._cache[wiki_key] = {
            "poster_url": poster_url,
            "backdrop_url": backdrop_url,
            "matched_title": best_page.get("title") if best_page else None,
            "match_score": best_score,
            "cached_at": datetime.now(timezone.utc).isoformat(),
        }
        self.save_cache()
        return poster_url, backdrop_url, False, api_called

    def enrich_records(
        self,
        records: list[MovieBoxOfficeRecord],
    ) -> tuple[list[MovieBoxOfficeRecord], dict[str, int]]:
        """Enrich MovieBoxOfficeRecord items via 3-tier fallback: TMDB -> Sacnilk -> Wikipedia."""
        stats = {
            "tmdb_matched": 0,
            "tmdb_cache_hits": 0,
            "tmdb_api_calls": 0,
            "tmdb_skipped_or_missed": 0,
            "sacnilk_poster_used": 0,
            "wikipedia_matched": 0,
            "wikipedia_cache_hits": 0,
            "trailers_tmdb": 0,
            "trailers_youtube": 0,
        }

        for record in records:
            release_year: int | None = None
            if record.release_date and len(record.release_date) >= 4:
                try:
                    release_year = int(record.release_date[:4])
                except ValueError:
                    release_year = None

            # Tier 1: TMDB API v3
            tmdb_matched = False
            try:
                meta, cache_hit, api_called = self.lookup(
                    record.title,
                    release_year=release_year,
                    language=record.language,
                )
                if cache_hit:
                    stats["tmdb_cache_hits"] += 1
                if api_called:
                    stats["tmdb_api_calls"] += 1

                if meta is not None and meta.tmdb_id is not None:
                    record.tmdb_id = meta.tmdb_id
                    record.poster_url = meta.poster_url or record.poster_url
                    record.backdrop_url = meta.backdrop_url or record.backdrop_url
                    if meta.trailer_youtube_id:
                        record.trailer_youtube_id = meta.trailer_youtube_id
                        stats["trailers_tmdb"] += 1
                    record.original_language = meta.original_language or record.original_language
                    record.cast_summary = meta.cast_summary or record.cast_summary
                    if not record.release_date and meta.release_date:
                        record.release_date = meta.release_date
                    stats["tmdb_matched"] += 1
                    tmdb_matched = bool(meta.poster_url)
                else:
                    stats["tmdb_skipped_or_missed"] += 1
            except Exception as exc:
                stats["tmdb_skipped_or_missed"] += 1
                logger.warning(
                    "TMDB enrichment failed for '%s': %s", record.title, exc
                )

            # Tier 2: Sacnilk extracted poster preserved on record.poster_url
            if not tmdb_matched and record.poster_url:
                stats["sacnilk_poster_used"] += 1

            # Tier 3: Wikipedia MediaWiki free API fallback when cover art is still absent
            if not record.poster_url:
                try:
                    wiki_poster, wiki_backdrop, w_hit, _ = self.lookup_wikipedia(
                        record.title,
                        release_year=release_year,
                        language=record.language,
                    )
                    if w_hit:
                        stats["wikipedia_cache_hits"] += 1
                    if wiki_poster:
                        record.poster_url = wiki_poster
                        record.backdrop_url = record.backdrop_url or wiki_backdrop or wiki_poster
                        stats["wikipedia_matched"] += 1
                except Exception as exc:
                    logger.warning("Wikipedia fallback failed for '%s': %s", record.title, exc)

            # YouTube Trailer fallback when TMDB has no trailer key
            if not record.trailer_youtube_id:
                try:
                    yt_id, _, _ = self.lookup_youtube_trailer(
                        record.title,
                        release_year=release_year,
                        language=record.language,
                    )
                    if yt_id:
                        record.trailer_youtube_id = yt_id
                        stats["trailers_youtube"] += 1
                except Exception as exc:
                    logger.warning("YouTube trailer fallback failed for '%s': %s", record.title, exc)

            # Ensure backdrop_url has a crisp visual fallback whenever a poster exists
            if record.poster_url and not record.backdrop_url:
                record.backdrop_url = record.poster_url

        return records, stats
