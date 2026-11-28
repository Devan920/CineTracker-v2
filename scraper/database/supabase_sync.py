"""Batch Supabase upsert engine with manual_override financial protection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from supabase import Client, create_client

from config.settings import Settings, get_settings
from utils.logger import get_logger
from utils.models import MovieBoxOfficeRecord
from utils.whitelabel import sanitize_source_name

logger = get_logger("database.supabase_sync")

# Financial fields protected when an existing row has manual_override == True
LOCKED_FINANCIAL_FIELDS = (
    "india_net_cr",
    "india_gross_cr",
    "overseas_cr",
    "worldwide_gross_cr",
    "budget_cr",
    "day_count",
    "daily_breakdown",
    "verdict",
    "manual_override",
    "variance_flag",
)

EXISTING_SELECT_COLUMNS = ",".join(
    ["id", "movie_slug", "poster_url", "backdrop_url", "trailer_youtube_id", *LOCKED_FINANCIAL_FIELDS]
)
EXISTING_SELECT_COLUMNS_NO_TRAILER = ",".join(
    ["id", "movie_slug", "poster_url", "backdrop_url", *LOCKED_FINANCIAL_FIELDS]
)


@dataclass
class SyncStats:
    """Summary counters produced by SupabaseSync.sync_records()."""

    upserted: int = 0
    manual_override_locked: int = 0
    daily_rows_synced: int = 0
    errors: int = 0


def _chunked(items: list[Any], size: int) -> list[list[Any]]:
    return [items[idx : idx + size] for idx in range(0, len(items), size)]


class SupabaseSync:
    """Batch upsert coordinator for movies and daily_collections tables."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        client: Client | Any | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._trailer_column_supported = True
        if client is not None:
            self.client = client
        else:
            self.settings.validate_environment(require_supabase=True, require_tmdb=False)
            assert self.settings.supabase_url and self.settings.supabase_key
            self.client = create_client(
                self.settings.supabase_url,
                self.settings.supabase_key,
            )

    @staticmethod
    def _is_missing_trailer_col_error(exc: Exception) -> bool:
        msg = str(exc).lower()
        return "trailer_youtube_id" in msg and ("42703" in msg or "pgrst204" in msg or "does not exist" in msg or "schema cache" in msg)

    def _fetch_existing_rows(self, slugs: list[str]) -> dict[str, dict[str, Any]]:
        """Inspect existing movies rows in batches so manual_override locks are respected."""
        existing: dict[str, dict[str, Any]] = {}
        if not slugs:
            return existing

        batch_size = self.settings.supabase_batch_size
        for batch_slugs in _chunked(slugs, batch_size):
            cols = (
                EXISTING_SELECT_COLUMNS
                if self._trailer_column_supported
                else EXISTING_SELECT_COLUMNS_NO_TRAILER
            )
            try:
                response = (
                    self.client.table("movies")
                    .select(cols)
                    .in_("movie_slug", batch_slugs)
                    .execute()
                )
            except Exception as exc:
                if self._trailer_column_supported and self._is_missing_trailer_col_error(exc):
                    self._trailer_column_supported = False
                    logger.warning(
                        "Supabase column 'movies.trailer_youtube_id' missing; omitting trailer field until "
                        "`ALTER TABLE public.movies ADD COLUMN IF NOT EXISTS trailer_youtube_id TEXT;` is applied."
                    )
                    response = (
                        self.client.table("movies")
                        .select(EXISTING_SELECT_COLUMNS_NO_TRAILER)
                        .in_("movie_slug", batch_slugs)
                        .execute()
                    )
                else:
                    raise
            rows = getattr(response, "data", None) or []
            for row in rows:
                slug = row.get("movie_slug")
                if slug:
                    existing[slug] = row
        return existing

    @staticmethod
    def _apply_manual_override_lock(
        payload: dict[str, Any],
        existing_row: dict[str, Any],
    ) -> dict[str, Any]:
        """Preserve locked financial columns while letting metadata fields update."""
        protected = dict(payload)
        for field in LOCKED_FINANCIAL_FIELDS:
            if field in existing_row:
                protected[field] = existing_row[field]
        protected["manual_override"] = True
        return protected

    def sync_records(self, records: list[MovieBoxOfficeRecord]) -> SyncStats:
        """Upsert movie records and normalized daily_collections rows in batches."""
        stats = SyncStats()
        if not records:
            logger.info("No movie records to sync to Supabase.")
            return stats

        # Deduplicate records by movie_slug within the same run (latest/highest wins)
        deduped_map: dict[str, MovieBoxOfficeRecord] = {}
        for rec in records:
            deduped_map[rec.movie_slug] = rec
        deduped = list(deduped_map.values())

        slugs = [r.movie_slug for r in deduped]
        existing_by_slug = self._fetch_existing_rows(slugs)

        locked_slugs: set[str] = set()
        upsert_payloads: list[dict[str, Any]] = []
        for record in deduped:
            payload = record.to_supabase_dict()
            # White-label primary_source in persisted Supabase rows (e.g., sacnilk -> cinetracker_bo)
            payload["primary_source"] = sanitize_source_name(payload.get("primary_source"))
            # Normalize blank date strings to None for PostgreSQL DATE column compatibility
            if not payload.get("release_date"):
                payload["release_date"] = None
            existing = existing_by_slug.get(record.movie_slug)
            if existing:
                if not payload.get("poster_url") and existing.get("poster_url"):
                    payload["poster_url"] = existing["poster_url"]
                if not payload.get("backdrop_url") and existing.get("backdrop_url"):
                    payload["backdrop_url"] = existing["backdrop_url"]
                if not payload.get("trailer_youtube_id") and existing.get("trailer_youtube_id"):
                    payload["trailer_youtube_id"] = existing["trailer_youtube_id"]
            if not self._trailer_column_supported:
                payload.pop("trailer_youtube_id", None)
            if existing and bool(existing.get("manual_override")):
                payload = self._apply_manual_override_lock(payload, existing)
                locked_slugs.add(record.movie_slug)
                stats.manual_override_locked += 1
                logger.info(
                    "manual_override=True for '%s': locked financial fields, updating metadata only.",
                    record.movie_slug,
                )
            upsert_payloads.append(payload)

        batch_size = self.settings.supabase_batch_size
        slug_to_id: dict[str, str] = {
            slug: str(row["id"])
            for slug, row in existing_by_slug.items()
            if row.get("id")
        }

        for batch in _chunked(upsert_payloads, batch_size):
            try:
                response = (
                    self.client.table("movies")
                    .upsert(batch, on_conflict="movie_slug")
                    .execute()
                )
            except Exception as exc:
                if self._trailer_column_supported and self._is_missing_trailer_col_error(exc):
                    self._trailer_column_supported = False
                    logger.warning(
                        "Omitting trailer_youtube_id during upsert until "
                        "`ALTER TABLE public.movies ADD COLUMN IF NOT EXISTS trailer_youtube_id TEXT;` is executed in Supabase."
                    )
                    stripped_batch = [
                        {k: v for k, v in item.items() if k != "trailer_youtube_id"}
                        for item in batch
                    ]
                    response = (
                        self.client.table("movies")
                        .upsert(stripped_batch, on_conflict="movie_slug")
                        .execute()
                    )
                else:
                    raise
            returned = getattr(response, "data", None) or []
            for row in returned:
                if row.get("movie_slug") and row.get("id"):
                    slug_to_id[row["movie_slug"]] = str(row["id"])
            stats.upserted += len(batch)

        # Resolve any newly inserted movie IDs if PostgREST response omitted data
        missing_id_slugs = [
            rec.movie_slug
            for rec in deduped
            if rec.movie_slug not in locked_slugs
            and rec.daily_breakdown
            and rec.movie_slug not in slug_to_id
        ]
        if missing_id_slugs:
            refreshed = self._fetch_existing_rows(missing_id_slugs)
            for slug, row in refreshed.items():
                if row.get("id"):
                    slug_to_id[slug] = str(row["id"])

        # Prepare daily_collections rows ONLY for non-locked movies
        daily_rows: list[dict[str, Any]] = []
        for record in deduped:
            if record.movie_slug in locked_slugs:
                continue
            movie_id = slug_to_id.get(record.movie_slug)
            if not movie_id:
                continue
            for entry in record.daily_breakdown:
                daily_rows.append(
                    {
                        "movie_id": movie_id,
                        "movie_slug": record.movie_slug,
                        "day_number": entry.day,
                        "collection_date": entry.date or None,
                        "india_net_cr": entry.india_net_cr,
                        "change_pct": entry.change_pct,
                    }
                )

        for batch in _chunked(daily_rows, batch_size * 2):
            self.client.table("daily_collections").upsert(
                batch, on_conflict="movie_id,day_number"
            ).execute()
            stats.daily_rows_synced += len(batch)

        logger.info(
            "Supabase sync complete: %d movies upserted (%d manual_override locked), %d daily rows synced.",
            stats.upserted,
            stats.manual_override_locked,
            stats.daily_rows_synced,
        )
        return stats
