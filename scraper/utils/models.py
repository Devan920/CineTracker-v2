"""Strict Pydantic data contracts for scraped, reconciled, and synced box office records."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field, field_validator


class DailyCollectionEntry(BaseModel):
    """Single day collection entry inside daily_breakdown (Day 0 = paid previews)."""

    day: int = Field(ge=0)
    date: str | None = None
    india_net_cr: float = Field(ge=0.0)
    change_pct: float | None = None
    shows: int | None = Field(default=None, ge=0)
    occupancy_pct: float | None = Field(default=None, ge=0.0, le=100.0)

    @field_validator("india_net_cr")
    @classmethod
    def _round_collection(cls, value: float) -> float:
        return round(float(value), 4)

    @field_validator("change_pct")
    @classmethod
    def _round_change(cls, value: float | None) -> float | None:
        if value is None:
            return None
        return round(float(value), 2)


class RawScrapedMovie(BaseModel):
    """Intermediate normalized output emitted by an individual source scraper."""

    source: str
    source_url: str
    title: str
    language: str
    release_date: str | None = None
    release_year: int | None = None
    budget_cr: float | None = None
    india_net_cr: float = 0.0
    india_gross_cr: float | None = None
    overseas_cr: float | None = None
    worldwide_gross_cr: float | None = None
    verdict: str | None = None
    day_count: int = 0
    daily_breakdown: list[DailyCollectionEntry] = Field(default_factory=list)
    cast_summary: str | None = None
    original_language: str | None = None
    poster_url: str | None = None
    backdrop_url: str | None = None
    scraped_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    extra_metrics: dict[str, Any] = Field(default_factory=dict)


class MovieBoxOfficeRecord(BaseModel):
    """Strict canonical record matching Supabase schema and JSON data contract."""

    movie_slug: str
    title: str
    language: str
    release_date: str | None = None
    tmdb_id: int | None = None
    poster_url: str | None = None
    backdrop_url: str | None = None
    budget_cr: float | None = None
    india_net_cr: float = 0.0
    india_gross_cr: float | None = None
    overseas_cr: float | None = None
    worldwide_gross_cr: float | None = None
    verdict: str | None = None
    day_count: int = 0
    daily_breakdown: list[DailyCollectionEntry] = Field(default_factory=list)
    primary_source: str
    source_urls: list[str] = Field(default_factory=list)
    variance_flag: bool = False
    manual_override: bool = False
    last_scraped_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    # Optional enrichment metadata fields stored in Supabase alongside strict contract
    original_language: str | None = None
    cast_summary: str | None = None
    trailer_youtube_id: str | None = None

    def to_contract_dict(self) -> dict[str, Any]:
        """Serialize strictly to the canonical JSON data contract."""
        return {
            "movie_slug": self.movie_slug,
            "title": self.title,
            "language": self.language,
            "release_date": self.release_date,
            "tmdb_id": self.tmdb_id,
            "poster_url": self.poster_url,
            "backdrop_url": self.backdrop_url,
            "budget_cr": self.budget_cr,
            "india_net_cr": round(float(self.india_net_cr), 4),
            "india_gross_cr": (
                round(float(self.india_gross_cr), 4)
                if self.india_gross_cr is not None
                else None
            ),
            "overseas_cr": (
                round(float(self.overseas_cr), 4)
                if self.overseas_cr is not None
                else None
            ),
            "worldwide_gross_cr": (
                round(float(self.worldwide_gross_cr), 4)
                if self.worldwide_gross_cr is not None
                else None
            ),
            "verdict": self.verdict,
            "day_count": self.day_count,
            "daily_breakdown": [entry.model_dump() for entry in self.daily_breakdown],
            "primary_source": self.primary_source,
            "source_urls": self.source_urls,
            "variance_flag": self.variance_flag,
            "manual_override": self.manual_override,
            "last_scraped_at": self.last_scraped_at,
        }

    def to_supabase_dict(self) -> dict[str, Any]:
        """Serialize full database row including TMDB enrichment columns."""
        payload = self.to_contract_dict()
        payload["original_language"] = self.original_language
        payload["cast_summary"] = self.cast_summary
        payload["trailer_youtube_id"] = self.trailer_youtube_id
        return payload
