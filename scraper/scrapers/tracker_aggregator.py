"""Multi-source box office reconciliation, anomaly detection, and day-wise merger."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from config.settings import Settings, get_settings
from utils.logger import get_logger
from utils.models import DailyCollectionEntry, MovieBoxOfficeRecord, RawScrapedMovie
from utils.title_matcher import TitleMatcher, canonical_slug

logger = get_logger("scrapers.aggregator")


class TrackerAggregator:
    """Reconciles scraped movie collections across multiple box office trackers."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        source_weights: dict[str, float] | None = None,
        variance_threshold: float | None = None,
        title_match_threshold: float | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.source_weights = source_weights or dict(self.settings.source_weights)
        self.variance_threshold = (
            variance_threshold
            if variance_threshold is not None
            else self.settings.variance_threshold
        )
        self.matcher = TitleMatcher(
            threshold=(
                title_match_threshold
                if title_match_threshold is not None
                else self.settings.title_match_threshold
            )
        )

    def _weight_for(self, source: str) -> float:
        return float(self.source_weights.get(source.lower(), 0.5))

    @staticmethod
    def _languages_compatible(a: RawScrapedMovie, b: RawScrapedMovie) -> bool:
        la = (a.original_language or a.language or "").strip().lower()
        lb = (b.original_language or b.language or "").strip().lower()
        if not la or not lb or la == lb:
            return True
        if "pan-india" in {la, lb}:
            return True
        # Same-title distinct-language remakes (e.g. Drishyam 3 Hindi vs Malayalam) stay separate
        return False

    @staticmethod
    def _years_compatible(a: RawScrapedMovie, b: RawScrapedMovie) -> bool:
        ya = a.release_year or (int(a.release_date[:4]) if a.release_date and len(a.release_date) >= 4 else None)
        yb = b.release_year or (int(b.release_date[:4]) if b.release_date and len(b.release_date) >= 4 else None)
        if ya and yb and abs(ya - yb) > 1:
            return False
        return True

    def _cluster_records(self, records: list[RawScrapedMovie]) -> list[list[RawScrapedMovie]]:
        """Group equivalent movie records across sources via fuzzy title matching."""
        # Sort by source priority weight descending so primary titles anchor clusters cleanly
        ordered = sorted(
            records,
            key=lambda r: (
                -self._weight_for(r.source),
                -len(r.daily_breakdown),
                -(r.india_net_cr or 0.0),
            ),
        )
        clusters: list[list[RawScrapedMovie]] = []

        for rec in ordered:
            placed = False
            for cluster in clusters:
                anchor = cluster[0]
                if not self._languages_compatible(anchor, rec):
                    continue
                if not self._years_compatible(anchor, rec):
                    continue
                if self.matcher.is_match(
                    anchor.title,
                    rec.title,
                    language_a=anchor.language,
                    language_b=rec.language,
                ):
                    cluster.append(rec)
                    placed = True
                    break
            if not placed:
                clusters.append([rec])

        return clusters

    @staticmethod
    def _relative_variance(a: float, b: float) -> float:
        denom = max(abs(a), abs(b))
        if denom <= 0:
            return 0.0
        return abs(a - b) / denom

    def _detect_variance_anomaly(self, cluster: list[RawScrapedMovie]) -> bool:
        """Return True if any metric across distinct sources diverges by > variance_threshold."""
        if len(cluster) < 2:
            return False

        # Compare india_net_cr across distinct sources
        net_values = [
            r.india_net_cr
            for r in cluster
            if r.india_net_cr is not None and r.india_net_cr > 0
        ]
        if len(net_values) >= 2:
            var_net = self._relative_variance(max(net_values), min(net_values))
            if var_net > self.variance_threshold:
                logger.warning(
                    "Variance anomaly (>%.0f%%) on india_net_cr for '%s': values=%s (variance=%.1f%%)",
                    self.variance_threshold * 100,
                    cluster[0].title,
                    net_values,
                    var_net * 100,
                )
                return True

        # Compare worldwide_gross_cr across distinct sources
        ww_values = [
            r.worldwide_gross_cr
            for r in cluster
            if r.worldwide_gross_cr is not None and r.worldwide_gross_cr > 0
        ]
        if len(ww_values) >= 2:
            var_ww = self._relative_variance(max(ww_values), min(ww_values))
            if var_ww > self.variance_threshold:
                logger.warning(
                    "Variance anomaly (>%.0f%%) on worldwide_gross_cr for '%s': values=%s (variance=%.1f%%)",
                    self.variance_threshold * 100,
                    cluster[0].title,
                    ww_values,
                    var_ww * 100,
                )
                return True

        return False

    def _pick_weighted_value(
        self,
        cluster: list[RawScrapedMovie],
        field: str,
        *,
        allow_zero: bool = False,
    ) -> Any:
        """Select field value from the highest-priority-weighted source with valid data."""
        ranked = sorted(
            cluster,
            key=lambda r: (
                -self._weight_for(r.source),
                -len(r.daily_breakdown),
                -(r.india_net_cr or 0.0),
            ),
        )
        for rec in ranked:
            val = getattr(rec, field, None)
            if val is None:
                continue
            if isinstance(val, (int, float)) and not allow_zero and val <= 0:
                continue
            return val
        return 0.0 if allow_zero and field == "india_net_cr" else None

    def _merge_daily_breakdowns(
        self,
        cluster: list[RawScrapedMovie],
        *,
        release_date: str | None,
    ) -> list[DailyCollectionEntry]:
        """Merge daily collection arrays across sources using source priority weights."""
        ranked = sorted(
            cluster,
            key=lambda r: (-self._weight_for(r.source), -len(r.daily_breakdown)),
        )
        by_day: dict[int, DailyCollectionEntry] = {}

        for rec in ranked:
            for entry in rec.daily_breakdown:
                if entry.day not in by_day:
                    by_day[entry.day] = entry.model_copy()
                else:
                    # Backfill missing date, change_pct, shows, or occupancy_pct from secondary source
                    existing = by_day[entry.day]
                    if not existing.date and entry.date:
                        existing.date = entry.date
                    if existing.change_pct is None and entry.change_pct is not None:
                        existing.change_pct = entry.change_pct
                    if existing.shows is None and entry.shows is not None:
                        existing.shows = entry.shows
                    if existing.occupancy_pct is None and entry.occupancy_pct is not None:
                        existing.occupancy_pct = entry.occupancy_pct

        release_dt: datetime | None = None
        if release_date:
            try:
                release_dt = datetime.strptime(release_date, "%Y-%m-%d")
            except ValueError:
                release_dt = None

        merged = [by_day[d] for d in sorted(by_day)]
        for idx, entry in enumerate(merged):
            if not entry.date and release_dt is not None:
                entry.date = (release_dt + timedelta(days=entry.day - 1)).strftime("%Y-%m-%d")
            if entry.change_pct is None and idx > 0:
                prev = merged[idx - 1]
                if prev.day >= 1 and prev.day == entry.day - 1 and prev.india_net_cr > 0:
                    entry.change_pct = round(
                        ((entry.india_net_cr - prev.india_net_cr) / prev.india_net_cr) * 100.0,
                        2,
                    )

        return merged

    def reconcile(
        self,
        raw_records: list[RawScrapedMovie],
    ) -> tuple[list[MovieBoxOfficeRecord], dict[str, Any]]:
        """Reconcile multi-source RawScrapedMovie records into canonical MovieBoxOfficeRecords."""
        if not raw_records:
            return [], {
                "total_movies": 0,
                "multi_source_matches": 0,
                "variance_anomalies": 0,
                "flagged_slugs": [],
            }

        clusters = self._cluster_records(raw_records)
        reconciled: list[MovieBoxOfficeRecord] = []
        used_slugs: dict[str, str] = {}
        multi_source_matches = 0
        flagged_slugs: list[str] = []

        for cluster in clusters:
            ranked = sorted(
                cluster,
                key=lambda r: (
                    -self._weight_for(r.source),
                    -len(r.daily_breakdown),
                    -(r.india_net_cr or 0.0),
                ),
            )
            primary = ranked[0]
            distinct_sources = {r.source for r in ranked}
            if len(distinct_sources) > 1:
                multi_source_matches += 1

            # Resolve language cleanly (prefer specific original language over generic Pan-India)
            language = next(
                (
                    r.original_language or r.language
                    for r in ranked
                    if (r.original_language or r.language)
                    and (r.original_language or r.language).lower() != "pan-india"
                ),
                primary.language,
            )

            # Deterministic canonical slug across matched titles
            slug = self.matcher.choose_canonical_slug(
                [r.title for r in ranked],
                language=None,
            )
            # Disambiguate if another distinct-language film already owns this exact slug
            if slug in used_slugs and used_slugs[slug].lower() != language.lower():
                slug = canonical_slug(primary.title, language=language, strip_subtitle=False)
            used_slugs[slug] = language

            release_date = self._pick_weighted_value(ranked, "release_date")
            india_net_cr = self._pick_weighted_value(ranked, "india_net_cr", allow_zero=True)
            india_gross_cr = self._pick_weighted_value(ranked, "india_gross_cr")
            overseas_cr = self._pick_weighted_value(ranked, "overseas_cr")
            worldwide_gross_cr = self._pick_weighted_value(ranked, "worldwide_gross_cr")
            budget_cr = self._pick_weighted_value(ranked, "budget_cr")
            verdict = self._pick_weighted_value(ranked, "verdict")
            cast_summary = self._pick_weighted_value(ranked, "cast_summary")
            original_language = self._pick_weighted_value(ranked, "original_language")
            poster_url = self._pick_weighted_value(ranked, "poster_url")
            backdrop_url = self._pick_weighted_value(ranked, "backdrop_url")

            daily_breakdown = self._merge_daily_breakdowns(
                ranked,
                release_date=release_date,
            )
            theatrical_days = len([e for e in daily_breakdown if e.day >= 1])
            day_count = max(
                [r.day_count for r in ranked]
                + [e.day for e in daily_breakdown]
                + [theatrical_days]
            )

            variance_flag = self._detect_variance_anomaly(ranked)
            if variance_flag:
                flagged_slugs.append(slug)

            # Deduplicate source URLs preserving priority order
            source_urls: list[str] = []
            for rec in ranked:
                if rec.source_url and rec.source_url not in source_urls:
                    source_urls.append(rec.source_url)

            # Choose fullest descriptive title from primary source (cleanest display)
            display_title = max(
                [r.title for r in ranked if r.source == primary.source] or [primary.title],
                key=len,
            )

            record = MovieBoxOfficeRecord(
                movie_slug=slug,
                title=display_title,
                language=language,
                release_date=release_date,
                poster_url=poster_url,
                backdrop_url=backdrop_url,
                budget_cr=budget_cr,
                india_net_cr=float(india_net_cr or 0.0),
                india_gross_cr=india_gross_cr,
                overseas_cr=overseas_cr,
                worldwide_gross_cr=worldwide_gross_cr,
                verdict=verdict,
                day_count=day_count,
                daily_breakdown=daily_breakdown,
                primary_source=primary.source,
                source_urls=source_urls,
                variance_flag=variance_flag,
                manual_override=False,
                last_scraped_at=datetime.now(timezone.utc).isoformat(),
                original_language=original_language,
                cast_summary=cast_summary,
            )
            reconciled.append(record)

        summary = {
            "total_movies": len(reconciled),
            "multi_source_matches": multi_source_matches,
            "variance_anomalies": len(flagged_slugs),
            "flagged_slugs": flagged_slugs,
        }
        return reconciled, summary
