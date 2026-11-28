"""Primary Sacnilk box office scraper prioritizing live daily feeds and quicknews reports."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any

from bs4 import Tag

from scrapers.base_scraper import BaseScraper
from utils.currency_parser import (
    normalize_verdict,
    parse_date_flexible,
    parse_inr_to_crores,
    parse_percentage,
)
from utils.logger import get_logger
from utils.models import DailyCollectionEntry, RawScrapedMovie

logger = get_logger("scrapers.sacnilk")

_KNOWN_LANGUAGES = (
    "Malayalam",
    "Tamil",
    "Hindi",
    "Telugu",
    "Kannada",
    "English",
    "Marathi",
    "Bengali",
    "Punjabi",
    "Gujarati",
    "Assamese",
)
_LANG_META_RE = re.compile(
    r"\b(" + "|".join(_KNOWN_LANGUAGES) + r")\b\s*·",
    re.IGNORECASE,
)
_ANY_LANG_RE = re.compile(
    r"\b(" + "|".join(_KNOWN_LANGUAGES) + r")\b",
    re.IGNORECASE,
)
_INDUSTRY_TO_LANG = {
    "bollywood": "Hindi",
    "mollywood": "Malayalam",
    "kollywood": "Tamil",
    "tollywood": "Telugu",
    "sandalwood": "Kannada",
    "hollywood": "English",
}
_INDUSTRY_RE = re.compile(
    r"\b(Bollywood|Mollywood|Kollywood|Tollywood|Sandalwood|Hollywood)\b",
    re.IGNORECASE,
)
_RELEASED_RE = re.compile(
    r"released\s+(\d{1,2}\s+[A-Za-z]{3,9}(?:\s+\d{4})?)",
    re.IGNORECASE,
)
_RECENT_DATE_RE = re.compile(
    r"\b((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},\s+\d{4}|\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{4})\b",
    re.IGNORECASE,
)
_DAY_NUM_RE = re.compile(r"\bDay\s+(\d+)\b", re.IGNORECASE)
_TOTAL_DAYS_RE = re.compile(r"(?:Total\s*·\s*|Worldwide gross\s*·\s*)(\d+)\s*days?", re.IGNORECASE)
_YEAR_IN_TITLE_RE = re.compile(r"\b(20\d{2}|19\d{2})\b")
_QUICKNEWS_DAY_RE = re.compile(
    r"/quicknews/(?P<slug>[A-Za-z0-9_]+?)_Box_Office_Collection_Day_(?P<day>\d+)",
    re.IGNORECASE,
)
_LIVE_CARD_SKIP_RE = re.compile(
    r"(?:advance\s+booking|releases\s+(?:mon|tue|wed|thu|fri|sat|sun)|\bOTT\b|\b\d+\s+DAYS\s+\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec))",
    re.IGNORECASE,
)


class SacnilkScraper(BaseScraper):
    """Scraper targeting Sacnilk's live daily running movies, quicknews Day N feeds, and charts."""

    source_name = "sacnilk"

    @staticmethod
    def _extract_language_from_text(text: str) -> str | None:
        match = _LANG_META_RE.search(text)
        if match:
            return match.group(1).title()
        ind = _INDUSTRY_RE.search(text)
        if ind:
            return _INDUSTRY_TO_LANG.get(ind.group(1).lower())
        return None

    @staticmethod
    def _extract_verdict_from_cell(text: str) -> str | None:
        return normalize_verdict(text)

    @staticmethod
    def _slug_from_movie_url(url: str) -> str:
        return url.rstrip("/").split("/")[-1].split("?")[0]

    @staticmethod
    def _humanize_movie_slug(slug: str) -> str:
        cleaned = re.sub(r"_(?:20\d{2}|19\d{2})$", "", slug)
        cleaned = re.sub(r"_(?:part|chapter)_\d+$", lambda m: m.group(0).replace("_", " ").title(), cleaned, flags=re.I)
        return re.sub(r"\s+", " ", cleaned.replace("_", " ")).strip()

    @staticmethod
    def _parse_int(text: str) -> int | None:
        digits = re.sub(r"[^\d]", "", text or "")
        return int(digits) if digits else None

    @staticmethod
    def _parse_occupancy(text: str) -> float | None:
        val = parse_percentage(text)
        if val is None or val < 0 or val > 100:
            return None
        return val

    @staticmethod
    def _map_listing_columns(table: Tag) -> dict[str, int]:
        """Inspect table header row to map column names to zero-based indices."""
        mapping: dict[str, int] = {}
        header_row = table.find("tr")
        if not header_row:
            return mapping

        headers = [
            th.get_text(" ", strip=True).lower()
            for th in header_row.find_all(["th", "td"])
        ]
        for idx, hdr in enumerate(headers):
            if "film" in hdr or "movie" in hdr:
                mapping["film"] = idx
            elif "india net" in hdr or re.match(r"^\d+\s+days?$", hdr):
                mapping["india_net"] = idx
            elif "india gross" in hdr:
                mapping["india_gross"] = idx
            elif "overseas" in hdr:
                mapping["overseas"] = idx
            elif "worldwide" in hdr:
                mapping["worldwide"] = idx
        return mapping

    def _extract_quicknews_index(self, soup: Any, tree: Any) -> dict[str, tuple[int, str]]:
        """Map movie_slug -> (highest_day_num, quicknews_url) from page links."""
        listing_sel = self.selectors.get("listing", {})
        qn_links = self.select_nodes(soup, listing_sel.get("quicknews_day_link"), tree=tree)
        if not qn_links:
            qn_links = soup.select("a[href*='_Box_Office_Collection_Day_']")

        best_by_slug: dict[str, tuple[int, str]] = {}
        for a in qn_links:
            href = a.get("href") or ""
            m = _QUICKNEWS_DAY_RE.search(href)
            if not m:
                continue
            slug = m.group("slug")
            day_num = int(m.group("day"))
            full_url = self.resolve_url(href)
            prev = best_by_slug.get(slug)
            if prev is None or day_num > prev[0]:
                best_by_slug[slug] = (day_num, full_url)
        return best_by_slug

    @staticmethod
    def _parse_recent_release_date(text: str) -> str | None:
        m = _RECENT_DATE_RE.search(text)
        if not m:
            return None
        raw = m.group(1).replace(",", "")
        for fmt in ("%b %d %Y", "%B %d %Y", "%d %b %Y"):
            try:
                return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
            except ValueError:
                continue
        return None

    def _parse_live_homepage_and_recent(
        self,
        soup: Any,
        tree: Any,
        *,
        requested_lang: str,
        is_pan_india: bool,
        base_url: str,
        quicknews_by_slug: dict[str, tuple[int, str]],
    ) -> list[dict[str, Any]]:
        """Extract live running movies from Sacnilk homepage, RecentMoviesCollection, and Recent_Movies."""
        candidates: list[dict[str, Any]] = []
        seen_urls: set[str] = set()
        listing_sel = self.selectors.get("listing", {})
        today_iso = datetime.now().strftime("%Y-%m-%d")

        def _add_candidate(
            *,
            detail_url: str,
            title: str,
            detected_lang: str | None = None,
            release_date: str | None = None,
            india_net: float | None = None,
            worldwide: float | None = None,
            day_hint: int = 0,
            is_live_priority: bool = True,
        ) -> None:
            if not detail_url or detail_url in seen_urls:
                return
            if (
                requested_lang
                and not is_pan_india
                and requested_lang.lower() != "all"
                and detected_lang
                and detected_lang.lower() != requested_lang.lower()
            ):
                return

            slug = self._slug_from_movie_url(detail_url)
            qn_info = quicknews_by_slug.get(slug)
            seen_urls.add(detail_url)
            candidates.append(
                {
                    "source": self.source_name,
                    "source_url": base_url,
                    "detail_url": detail_url,
                    "quicknews_url": qn_info[1] if qn_info else None,
                    "title": title,
                    "language": (
                        "Pan-India"
                        if is_pan_india
                        else (detected_lang or requested_lang or "Hindi")
                    ),
                    "original_language": detected_lang,
                    "release_date": release_date,
                    "india_net_cr": india_net,
                    "india_gross_cr": None,
                    "overseas_cr": None,
                    "worldwide_gross_cr": worldwide,
                    "verdict": None,
                    "day_count": max(day_hint, qn_info[0] if qn_info else 0),
                    "is_live_priority": is_live_priority,
                }
            )

        # 1. Homepage live table (table.boxoffice-table: Ramayana, Scene, O.M Operation Mole, etc.)
        live_tables = self.select_nodes(soup, listing_sel.get("live_table"), tree=tree)
        for tbl in live_tables:
            col_map = self._map_listing_columns(tbl)
            for tr in tbl.find_all("tr")[1:]:
                link = tr.select_one("a[href*='/movie/']")
                if not link or not link.get("href"):
                    continue
                detail_url = self.resolve_url(link["href"])
                cells = tr.find_all(["td", "th"])
                row_txt = cells[0].get_text(" ", strip=True) if cells else ""
                # Strip trailing "Bollywood • 2026" from title cell
                clean_title = re.sub(
                    r"\s+(?:Bollywood|Mollywood|Kollywood|Tollywood|Sandalwood|Hollywood)\s*•.*$",
                    "",
                    row_txt,
                    flags=re.I,
                ).strip()
                if not clean_title or clean_title.lower() == "details":
                    clean_title = self._humanize_movie_slug(self._slug_from_movie_url(detail_url))
                detected_lang = self._extract_language_from_text(row_txt)
                net_idx = col_map.get("india_net", 1)
                ww_idx = col_map.get("worldwide", 2)
                india_net = (
                    parse_inr_to_crores(cells[net_idx].get_text(" ", strip=True))
                    if net_idx < len(cells)
                    else None
                )
                worldwide = (
                    parse_inr_to_crores(cells[ww_idx].get_text(" ", strip=True))
                    if ww_idx < len(cells)
                    else None
                )
                _add_candidate(
                    detail_url=detail_url,
                    title=clean_title,
                    detected_lang=detected_lang,
                    india_net=india_net,
                    worldwide=worldwide,
                )

        # 2. Live running cards & RecentMoviesCollection top cards & Recent_Movies theatrical cards
        is_recent_movies_page = "recent_movies" in base_url.lower()
        recent_cutoff_iso = (datetime.now() - timedelta(days=24)).strftime("%Y-%m-%d")
        for a in soup.select("a[href*='/movie/']"):
            if a.find_parent("table"):
                continue
            href = a.get("href") or ""
            detail_url = self.resolve_url(href)
            if detail_url in seen_urls:
                continue

            anchor_txt = a.get_text(" ", strip=True)
            parent_txt = a.parent.get_text(" ", strip=True) if a.parent else anchor_txt

            # Recent_Movies page wraps all cards inside a single parent container, so inspect anchor_txt directly!
            card_txt = anchor_txt if is_recent_movies_page else (parent_txt or anchor_txt)
            if _LIVE_CARD_SKIP_RE.search(card_txt):
                continue

            # Identify whether this non-table link is a running theatrical movie card
            day_match = _DAY_NUM_RE.search(card_txt)
            rel_date = self._parse_recent_release_date(card_txt)
            has_live_marker = any(
                tok in card_txt.lower()
                for tok in ("release week", "running", "live estimate", "day 1, estimate")
            )

            if not (day_match or has_live_marker or (is_recent_movies_page and rel_date)):
                continue

            # Skip unreleased future movies and older archive cards (>35 days) on Recent_Movies
            if rel_date and rel_date > today_iso:
                continue
            if is_recent_movies_page and rel_date and rel_date < recent_cutoff_iso:
                continue

            slug = self._slug_from_movie_url(detail_url)
            title = ""
            if anchor_txt and anchor_txt.lower() not in {"details", "box office"} and not is_recent_movies_page:
                title = anchor_txt
            elif is_recent_movies_page and rel_date:
                # Extract title between date and first language/genre token
                after_date = _RECENT_DATE_RE.split(anchor_txt, maxsplit=1)[-1].strip()
                before_lang = _ANY_LANG_RE.split(after_date, maxsplit=1)[0].strip()
                title = before_lang or self._humanize_movie_slug(slug)
            else:
                # Homepage live card wraps card with empty anchor; take text before Day N / Release week
                title = re.split(
                    r"\s+(?:Release\s+week|Day\s+\d+|Running)\b",
                    card_txt,
                    maxsplit=1,
                    flags=re.I,
                )[0].strip()
                if not title or len(title) > 65:
                    title = self._humanize_movie_slug(slug)

            # First listed language on Recent_Movies / live card is primary language
            lang_match = _ANY_LANG_RE.search(card_txt)
            detected_lang = lang_match.group(1).title() if lang_match else self._extract_language_from_text(card_txt)

            # On regional queries against Recent_Movies, skip if card explicitly states another primary language
            if (
                requested_lang
                and not is_pan_india
                and requested_lang.lower() != "all"
                and detected_lang
                and detected_lang.lower() != requested_lang.lower()
            ):
                # Allow if requested language is listed in card's language list (e.g. Malayalam, Tamil, Telugu)
                all_langs = {m.group(1).lower() for m in _ANY_LANG_RE.finditer(card_txt)}
                if requested_lang.lower() not in all_langs:
                    continue
                # If movie is multi-lingual dubbed, still record its true primary language unless matched
                if is_recent_movies_page and detected_lang.lower() != requested_lang.lower():
                    continue

            _add_candidate(
                detail_url=detail_url,
                title=title,
                detected_lang=detected_lang,
                release_date=rel_date,
                day_hint=int(day_match.group(1)) if day_match else 0,
            )

        # 3. Any quicknews Day N feed movie not yet discovered via cards (e.g. Cosmic Samson / Yeh Prem Mol Liya)
        for slug, (day_num, qn_url) in quicknews_by_slug.items():
            detail_url = self.resolve_url(f"/movie/{slug}")
            if detail_url in seen_urls:
                continue
            if requested_lang and not is_pan_india and requested_lang.lower() != "all":
                continue
            _add_candidate(
                detail_url=detail_url,
                title=self._humanize_movie_slug(slug),
                day_hint=day_num,
            )

        return candidates

    def parse_listings(
        self,
        html: str,
        *,
        language: str | None = None,
        base_url: str | None = None,
    ) -> list[dict[str, Any]]:
        """Parse live running Sacnilk cards, quicknews feeds, and leaderboard tables."""
        soup = self.make_soup(html)
        tree = self.make_tree(html)
        listing_sel = self.selectors.get("listing", {})
        src_url = base_url or self.base_url

        requested_lang = (language or "").strip()
        is_pan_india_category = requested_lang.lower() == "pan-india"
        quicknews_by_slug = self._extract_quicknews_index(soup, tree)

        # Prioritize live running feeds & recent November 2026 theatrical releases first
        live_candidates = self._parse_live_homepage_and_recent(
            soup,
            tree,
            requested_lang=requested_lang,
            is_pan_india=is_pan_india_category,
            base_url=src_url,
            quicknews_by_slug=quicknews_by_slug,
        )

        candidates: list[dict[str, Any]] = list(live_candidates)
        seen_urls: set[str] = {c["detail_url"] for c in candidates if c.get("detail_url")}
        shared_col_map: dict[str, int] = {}

        tables = self.select_nodes(soup, listing_sel.get("table"), tree=tree)
        for table in tables:
            # Skip live homepage boxoffice-table already handled above
            if "boxoffice-table" in (table.get("class") or []):
                continue

            col_map = self._map_listing_columns(table)
            if col_map:
                shared_col_map = col_map
            effective_cols = col_map or shared_col_map

            first_row = table.find("tr")
            if first_row:
                hdr_txt = first_row.get_text(" ", strip=True).lower()
                if "share" in hdr_txt and "language" in hdr_txt:
                    continue

            rows = self.select_nodes(table, listing_sel.get("row"))
            if not rows:
                rows = table.find_all("tr")

            for row in rows:
                link_nodes = self.select_nodes(row, listing_sel.get("movie_link"))
                if not link_nodes:
                    continue
                link = link_nodes[0]
                href = link.get("href")
                if not href:
                    continue

                detail_url = self.resolve_url(href)
                if detail_url in seen_urls:
                    continue

                cells = row.find_all(["td", "th"])
                film_idx = effective_cols.get(
                    "film",
                    int(listing_sel.get("film_cell_index", 1)),
                )
                if film_idx >= len(cells):
                    continue

                film_cell_text = cells[film_idx].get_text(" ", strip=True)
                title = link.get_text(" ", strip=True)
                if not title or "total," in film_cell_text.lower():
                    continue

                detected_lang = self._extract_language_from_text(film_cell_text)

                if (
                    requested_lang
                    and not is_pan_india_category
                    and requested_lang.lower() != "all"
                    and detected_lang
                    and detected_lang.lower() != requested_lang.lower()
                ):
                    continue

                rel_match = _RELEASED_RE.search(film_cell_text)
                release_date = (
                    parse_date_flexible(rel_match.group(1))
                    if rel_match
                    else None
                )
                listing_verdict = self._extract_verdict_from_cell(film_cell_text)

                def _cell_cr(key: str, default_idx: int | None = None) -> float | None:
                    idx = effective_cols.get(key, default_idx)
                    if idx is not None and idx < len(cells):
                        return parse_inr_to_crores(cells[idx].get_text(" ", strip=True))
                    return None

                india_net = _cell_cr("india_net", 2 if len(cells) == 6 else 3)
                india_gross = _cell_cr("india_gross", 3 if len(cells) == 6 else 4)
                overseas = _cell_cr("overseas", 4 if len(cells) == 6 else 5)
                worldwide = _cell_cr("worldwide", 5 if len(cells) == 6 else 6)

                slug = self._slug_from_movie_url(detail_url)
                qn_info = quicknews_by_slug.get(slug)

                seen_urls.add(detail_url)
                candidates.append(
                    {
                        "source": self.source_name,
                        "source_url": src_url,
                        "detail_url": detail_url,
                        "quicknews_url": qn_info[1] if qn_info else None,
                        "title": title,
                        "language": (
                            "Pan-India"
                            if is_pan_india_category
                            else (detected_lang or requested_lang or "Hindi")
                        ),
                        "original_language": detected_lang,
                        "release_date": release_date,
                        "india_net_cr": india_net,
                        "india_gross_cr": india_gross,
                        "overseas_cr": overseas,
                        "worldwide_gross_cr": worldwide,
                        "verdict": listing_verdict,
                        "day_count": qn_info[0] if qn_info else 0,
                        "is_live_priority": False,
                    }
                )

        return candidates

    def _select_primary_day_table(self, tables: list[Tag]) -> Tag | None:
        """Select the overall India Net day-wise table rather than a dubbed-language sub-table."""
        if not tables:
            return None

        for tbl in tables:
            hdr = tbl.find("tr")
            if not hdr:
                continue
            hdr_text = hdr.get_text(" ", strip=True).lower()
            if "india net" in hdr_text:
                return tbl

        return tables[0]

    def _parse_day_table(
        self,
        table: Tag | None,
        *,
        release_date: str | None,
        fallback_year: int | None,
    ) -> tuple[list[dict[str, Any]], float | None, float | None, int]:
        """Parse Sacnilk movie or quicknews day-wise table including shows & occupancy %."""
        if table is None:
            return [], None, None, 0

        rows = table.find_all("tr")
        if len(rows) <= 1:
            return [], None, None, 0

        hdr_cells = [c.get_text(" ", strip=True).lower() for c in rows[0].find_all(["th", "td"])]
        net_col = 1
        gross_col: int | None = None
        pct_col: int | None = 3
        shows_col: int | None = None
        occ_col: int | None = None

        for idx, h in enumerate(hdr_cells):
            if "net" in h:
                net_col = idx
            elif "gross" in h:
                gross_col = idx
            elif "vs day" in h or "change" in h:
                pct_col = idx
            elif "show" in h:
                shows_col = idx
            elif "occ" in h:
                occ_col = idx

        entries: list[dict[str, Any]] = []
        total_net_cr: float | None = None
        total_gross_cr: float | None = None
        max_day_seen = 0

        release_dt: datetime | None = None
        if release_date:
            try:
                release_dt = datetime.strptime(release_date, "%Y-%m-%d")
            except ValueError:
                release_dt = None

        base_year = (release_dt.year if release_dt else None) or fallback_year or datetime.now().year
        prev_month: int | None = None

        for tr in rows[1:]:
            cells = tr.find_all(["td", "th"])
            if len(cells) <= net_col:
                continue

            col0 = cells[0].get_text(" ", strip=True)
            if not col0:
                continue

            if col0.lower().startswith("total"):
                total_net_cr = parse_inr_to_crores(cells[net_col].get_text(" ", strip=True))
                if gross_col is not None and gross_col < len(cells):
                    total_gross_cr = parse_inr_to_crores(cells[gross_col].get_text(" ", strip=True))
                m_total = _TOTAL_DAYS_RE.search(col0)
                if m_total:
                    max_day_seen = max(max_day_seen, int(m_total.group(1)))
                continue

            # Skip cumulative week summary rows ("Week 1 Days 1–2 · so far")
            if col0.lower().startswith("week"):
                continue

            day_match = _DAY_NUM_RE.search(col0)
            if not day_match:
                continue

            day_num = int(day_match.group(1))
            net_cell_txt = cells[net_col].get_text(" ", strip=True)
            net_val = parse_inr_to_crores(net_cell_txt)
            if net_val is None:
                continue

            change_val = (
                parse_percentage(cells[pct_col].get_text(" ", strip=True))
                if pct_col is not None and pct_col < len(cells)
                else None
            )
            if change_val is None and "%" in net_cell_txt:
                change_val = parse_percentage(net_cell_txt)

            shows_val = (
                self._parse_int(cells[shows_col].get_text(" ", strip=True))
                if shows_col is not None and shows_col < len(cells)
                else None
            )
            occ_val = (
                self._parse_occupancy(cells[occ_col].get_text(" ", strip=True))
                if occ_col is not None and occ_col < len(cells)
                else None
            )

            parsed_date = parse_date_flexible(col0, default_year=base_year)
            if parsed_date:
                dt = datetime.strptime(parsed_date, "%Y-%m-%d")
                if prev_month is not None and dt.month < prev_month and prev_month >= 11:
                    base_year += 1
                    dt = dt.replace(year=base_year)
                    parsed_date = dt.strftime("%Y-%m-%d")
                prev_month = dt.month
            elif release_dt is not None:
                parsed_date = (release_dt + timedelta(days=day_num - 1)).strftime("%Y-%m-%d")

            entries.append(
                {
                    "day": day_num,
                    "date": parsed_date,
                    "india_net_cr": net_val,
                    "change_pct": change_val,
                    "shows": shows_val,
                    "occupancy_pct": occ_val,
                }
            )
            max_day_seen = max(max_day_seen, day_num)

        entries.sort(key=lambda item: item["day"])
        return entries, total_net_cr, total_gross_cr, max_day_seen

    def parse_quicknews_day_page(
        self,
        html: str,
        *,
        release_date: str | None = None,
        fallback_year: int | None = None,
    ) -> dict[str, Any]:
        """Parse Sacnilk /quicknews/*_Box_Office_Collection_Day_* live feed page."""
        soup = self.make_soup(html)
        tree = self.make_tree(html)
        detail_sel = self.selectors.get("detail", {})

        tables = self.select_nodes(soup, detail_sel.get("quicknews_tables"), tree=tree)
        primary_tbl = self._select_primary_day_table(tables)
        daily_breakdown, total_net_cr, total_gross_cr, max_day_seen = self._parse_day_table(
            primary_tbl,
            release_date=release_date,
            fallback_year=fallback_year,
        )

        # Extract Theatrical Release date & Languages if missing on listing
        detected_lang: str | None = None
        detected_release = release_date
        for card in soup.select("div.bg-white.rounded-lg"):
            txt = card.get_text(" ", strip=True)
            if "Languages:" in txt and not detected_lang:
                m_lang = re.search(r"Languages:\s*([A-Za-z,\s]+)", txt)
                if m_lang:
                    first_lang = _ANY_LANG_RE.search(m_lang.group(1))
                    if first_lang:
                        detected_lang = first_lang.group(1).title()
            if "Theatrical Release:" in txt and not detected_release:
                m_rel = re.search(
                    r"Theatrical Release:\s*([0-9]{1,2}\s+[A-Za-z]{3,9}\s+\d{4}|\d{4}-\d{2}-\d{2})",
                    txt,
                    re.I,
                )
                if m_rel:
                    detected_release = parse_date_flexible(m_rel.group(1))

        return {
            "daily_breakdown": daily_breakdown,
            "india_net_cr": total_net_cr,
            "india_gross_cr": total_gross_cr,
            "max_day_seen": max_day_seen,
            "detected_language": detected_lang,
            "release_date": detected_release,
        }

    def _merge_quicknews_into_detail(
        self,
        detail: dict[str, Any],
        qn_data: dict[str, Any],
        quicknews_url: str,
    ) -> dict[str, Any]:
        """Merge newer live Day N quicknews collections, shows, and occupancy onto movie details."""
        existing_map: dict[int, dict[str, Any]] = {
            int(item["day"]): dict(item)
            for item in (detail.get("daily_breakdown") or [])
        }
        for q_item in qn_data.get("daily_breakdown") or []:
            day = int(q_item["day"])
            if day not in existing_map:
                existing_map[day] = dict(q_item)
            else:
                cur = existing_map[day]
                if q_item.get("india_net_cr") is not None and (cur.get("india_net_cr") or 0) <= 0:
                    cur["india_net_cr"] = q_item["india_net_cr"]
                if cur.get("shows") is None and q_item.get("shows") is not None:
                    cur["shows"] = q_item["shows"]
                if cur.get("occupancy_pct") is None and q_item.get("occupancy_pct") is not None:
                    cur["occupancy_pct"] = q_item["occupancy_pct"]
                if cur.get("change_pct") is None and q_item.get("change_pct") is not None:
                    cur["change_pct"] = q_item["change_pct"]
                if not cur.get("date") and q_item.get("date"):
                    cur["date"] = q_item["date"]

        merged_daily = [existing_map[d] for d in sorted(existing_map)]
        qn_net = qn_data.get("india_net_cr")
        qn_gross = qn_data.get("india_gross_cr")

        # Update totals if quicknews has live Day N estimate beyond movie detail page
        cur_net = float(detail.get("india_net_cr") or 0.0)
        if qn_net is not None and qn_net > cur_net:
            detail["india_net_cr"] = qn_net
        elif merged_daily and sum(d["india_net_cr"] for d in merged_daily) > cur_net:
            detail["india_net_cr"] = round(sum(d["india_net_cr"] for d in merged_daily), 4)

        cur_gross = detail.get("india_gross_cr")
        if qn_gross is not None and (cur_gross is None or qn_gross > cur_gross):
            detail["india_gross_cr"] = qn_gross

        if detail.get("india_gross_cr") is not None:
            overseas = float(detail.get("overseas_cr") or 0.0)
            derived_ww = round(float(detail["india_gross_cr"]) + overseas, 4)
            cur_ww = detail.get("worldwide_gross_cr")
            if cur_ww is None or derived_ww > float(cur_ww):
                detail["worldwide_gross_cr"] = derived_ww

        if not detail.get("release_date") and qn_data.get("release_date"):
            detail["release_date"] = qn_data["release_date"]

        if qn_data.get("detected_language") and not detail.get("original_language"):
            detail["original_language"] = qn_data["detected_language"]
            detail["language"] = qn_data["detected_language"]

        detail["daily_breakdown"] = merged_daily
        detail["day_count"] = max(
            int(detail.get("day_count") or 0),
            int(qn_data.get("max_day_seen") or 0),
            len([d for d in merged_daily if d["day"] >= 1]),
        )
        detail["quicknews_url"] = quicknews_url
        return detail

    @staticmethod
    def _is_valid_poster_url(url: str | None) -> bool:
        if not url:
            return False
        low = url.strip().lower()
        if not low.startswith(("http://", "https://", "/")):
            return False
        if any(
            bad in low
            for bad in (
                "sacnilknewlogo",
                "/logo",
                "logo.",
                "favicon",
                ".svg",
                "sprite",
                "placeholder",
                "blank.",
                "/news300/",
            )
        ):
            return False
        return True

    def _extract_poster_url(self, soup: BeautifulSoup) -> str | None:
        """Tier-2 Sacnilk poster extraction via og:image, twitter:image, and movie <img> tags."""
        meta_candidates = [
            ("meta", {"property": "og:image"}),
            ("meta", {"name": "twitter:image"}),
            ("meta", {"property": "twitter:image"}),
        ]
        for tag_name, attrs in meta_candidates:
            tag = soup.find(tag_name, attrs=attrs)
            if tag:
                content = (tag.get("content") or "").strip()
                resolved = self.resolve_url(content) if content else ""
                if self._is_valid_poster_url(resolved):
                    return resolved

        for selector in (
            "img[src*='/image/movie/']",
            "img[data-src*='/image/movie/']",
            "img.max-w-xs",
            "img",
        ):
            for img in soup.select(selector):
                raw_src = (img.get("src") or img.get("data-src") or "").strip()
                if not raw_src:
                    continue
                resolved = self.resolve_url(raw_src)
                if self._is_valid_poster_url(resolved):
                    return resolved
        return None

    def parse_movie_details(
        self,
        html: str,
        listing_item: dict[str, Any],
    ) -> dict[str, Any]:
        """Parse Sacnilk movie page for full financial figures, language, verdict, cast, and daily breakdown."""
        soup = self.make_soup(html)
        tree = self.make_tree(html)
        detail_sel = self.selectors.get("detail", {})

        title_nodes = self.select_nodes(soup, detail_sel.get("title"), tree=tree)
        page_title = title_nodes[0].get_text(" ", strip=True) if title_nodes else ""
        title = page_title or listing_item.get("title", "")

        hero_nodes = self.select_nodes(soup, detail_sel.get("hero_worldwide"), tree=tree)
        hero_worldwide = (
            parse_inr_to_crores(hero_nodes[0].get_text(" ", strip=True))
            if hero_nodes
            else None
        )

        hero_lbl = soup.select_one(".ds-hero-fig__lbl")
        hero_days = 0
        if hero_lbl:
            m_days = _TOTAL_DAYS_RE.search(hero_lbl.get_text(" ", strip=True))
            if m_days:
                hero_days = int(m_days.group(1))

        india_net = listing_item.get("india_net_cr")
        india_gross = listing_item.get("india_gross_cr")
        overseas = listing_item.get("overseas_cr")
        budget = None
        verdict = listing_item.get("verdict")

        stat_cards = self.select_nodes(soup, detail_sel.get("stat_cards"), tree=tree)
        key_sel = (detail_sel.get("stat_key") or {}).get("css", ".ds-stat__k")
        val_sel = (detail_sel.get("stat_value") or {}).get("css", ".ds-stat__v")

        for card in stat_cards:
            k_el = card.select_one(key_sel)
            v_el = card.select_one(val_sel)
            if not k_el or not v_el:
                continue
            key_txt = k_el.get_text(" ", strip=True).lower()
            val_txt = v_el.get_text(" ", strip=True)

            if "india net" in key_txt:
                parsed = parse_inr_to_crores(val_txt)
                if parsed is not None:
                    india_net = parsed
            elif "india gross" in key_txt:
                parsed = parse_inr_to_crores(val_txt)
                if parsed is not None:
                    india_gross = parsed
            elif "overseas" in key_txt:
                parsed = parse_inr_to_crores(val_txt)
                if parsed is not None:
                    overseas = parsed
            elif "budget" in key_txt:
                parsed = parse_inr_to_crores(val_txt)
                if parsed is not None:
                    budget = parsed
            elif "verdict" in key_txt:
                parsed_v = normalize_verdict(val_txt)
                if parsed_v:
                    verdict = parsed_v

        # Release Date & Primary Language from Key Details / Release Information cards
        release_date = listing_item.get("release_date")
        detected_original_lang = listing_item.get("original_language")
        for card in soup.select("div.bg-white.rounded-lg"):
            txt = card.get_text(" ", strip=True)
            if "Theatrical Release:" in txt:
                m_rel = re.search(
                    r"Theatrical Release:\s*([0-9]{1,2}\s+[A-Za-z]{3,9}\s+\d{4}|\d{4}-\d{2}-\d{2})",
                    txt,
                    re.I,
                )
                if m_rel:
                    parsed_rel = parse_date_flexible(m_rel.group(1))
                    if parsed_rel:
                        release_date = parsed_rel
            if not detected_original_lang and "Languages:" in txt and "Theatrical Release" not in txt:
                m_lang = re.search(r"Languages:\s*([A-Za-z,\s]+)", txt)
                if m_lang:
                    first_lang = _ANY_LANG_RE.search(m_lang.group(1))
                    if first_lang:
                        detected_original_lang = first_lang.group(1).title()

        # Fallback language from description paragraph ("Here is the Telugu movie ...")
        if not detected_original_lang:
            for p in soup.select("p.text-gray-600"):
                ptxt = p.get_text(" ", strip=True)
                m_desc = re.search(r"\b(" + "|".join(_KNOWN_LANGUAGES) + r")\s+movie\b", ptxt, re.I)
                if m_desc:
                    detected_original_lang = m_desc.group(1).title()
                    break

        # Cast summary
        cast_summary: str | None = None
        cast_headings = [
            h for h in soup.find_all(["h2", "h3"])
            if "cast" in h.get_text(" ", strip=True).lower()
        ]
        if cast_headings:
            parent_box = cast_headings[0].parent
            if parent_box:
                raw_cast_tokens = [
                    el.get_text(" ", strip=True)
                    for el in parent_box.select("a, span, div")
                ]
                seen_names: list[str] = []
                noise = {
                    "cast",
                    "crew",
                    "cast & crew",
                    "director:",
                    "music director:",
                    "cinematographer:",
                    "editor:",
                    "production:",
                    "distribution:",
                }
                for tok in raw_cast_tokens:
                    # Strip leading/trailing emojis & punctuation before checking against heading noise
                    clean_tok = re.sub(r"^[^\w]+|[^\w]+$", "", tok, flags=re.UNICODE).strip()
                    low_tok = re.sub(r"[^a-z&\s]", "", clean_tok.lower()).strip()
                    if (
                        2 <= len(clean_tok) <= 40
                        and ":" not in tok
                        and "+" not in tok
                        and clean_tok.lower() not in noise
                        and low_tok not in noise
                        and "cast" not in low_tok
                        and "crew" not in low_tok
                        and re.search(r"[A-Za-z]{2}", clean_tok)
                        and not any(ch.isdigit() for ch in clean_tok)
                        and clean_tok not in seen_names
                    ):
                        seen_names.append(clean_tok)
                    if len(seen_names) >= 5:
                        break
                if seen_names:
                    cast_summary = ", ".join(seen_names)

        fallback_year = None
        if release_date and len(release_date) >= 4:
            fallback_year = int(release_date[:4])
        elif soup.title:
            m_yr = _YEAR_IN_TITLE_RE.search(soup.title.get_text())
            if m_yr:
                fallback_year = int(m_yr.group(1))

        day_tables = self.select_nodes(soup, detail_sel.get("day_tables"), tree=tree)
        primary_day_tbl = self._select_primary_day_table(day_tables)
        daily_breakdown, table_total_net, table_total_gross, max_day_seen = self._parse_day_table(
            primary_day_tbl,
            release_date=release_date,
            fallback_year=fallback_year,
        )

        if india_net is None and table_total_net is not None:
            india_net = table_total_net
        if india_net is None and daily_breakdown:
            india_net = round(sum(d["india_net_cr"] for d in daily_breakdown), 4)
        if india_gross is None and table_total_gross is not None:
            india_gross = table_total_gross

        worldwide = hero_worldwide or listing_item.get("worldwide_gross_cr")
        if worldwide is None and india_gross is not None and overseas is not None:
            worldwide = round(india_gross + overseas, 4)

        theatrical_days = len([d for d in daily_breakdown if d["day"] >= 1])
        day_count = max(max_day_seen, hero_days, theatrical_days, int(listing_item.get("day_count") or 0))

        # Discover matching quicknews Day N URL strictly belonging to this movie's slug
        detail_url = listing_item.get("detail_url") or ""
        movie_slug = self._slug_from_movie_url(detail_url) if detail_url else ""
        quicknews_url = listing_item.get("quicknews_url")
        if movie_slug and not quicknews_url:
            best_day = 0
            for a in soup.select("a[href*='_Box_Office_Collection_Day_']"):
                href = a.get("href") or ""
                m_qn = _QUICKNEWS_DAY_RE.search(href)
                if m_qn and m_qn.group("slug").lower() == movie_slug.lower():
                    d_num = int(m_qn.group("day"))
                    if d_num > best_day:
                        best_day = d_num
                        quicknews_url = self.resolve_url(href)

        effective_lang = (
            detected_original_lang
            if listing_item.get("language") in {None, "", "Pan-India"}
            and detected_original_lang
            else (detected_original_lang or listing_item.get("language") or "Hindi")
        )

        poster_url = self._extract_poster_url(soup) or listing_item.get("poster_url")

        return {
            **listing_item,
            "title": title,
            "language": effective_lang,
            "original_language": detected_original_lang,
            "release_date": release_date,
            "release_year": fallback_year,
            "budget_cr": budget,
            "india_net_cr": india_net if india_net is not None else 0.0,
            "india_gross_cr": india_gross,
            "overseas_cr": overseas,
            "worldwide_gross_cr": worldwide,
            "verdict": verdict,
            "day_count": day_count,
            "daily_breakdown": daily_breakdown,
            "cast_summary": cast_summary,
            "poster_url": poster_url,
            "quicknews_url": quicknews_url,
            "max_day_seen": max_day_seen,
        }

    def scrape(
        self,
        *,
        language: str | None = None,
        limit: int | None = None,
    ) -> tuple[list[RawScrapedMovie], dict[str, int], list[dict[str, Any]]]:
        """Scrape Sacnilk prioritizing live feeds, merging /quicknews Day N estimates when newer."""
        category_urls = self.get_category_urls(language=language)
        metrics = {
            "category_pages_fetched": 0,
            "listings_discovered": 0,
            "movies_scraped": 0,
            "movie_errors": 0,
        }
        error_events: list[dict[str, Any]] = []
        candidates_by_key: dict[str, dict[str, Any]] = {}

        for cat_lang, url in category_urls:
            try:
                logger.info("[%s] Fetching %s listing: %s", self.source_name, cat_lang, url)
                html = self.fetch_html(url)
                metrics["category_pages_fetched"] += 1
                items = self.parse_listings(html, language=cat_lang, base_url=url)
                for item in items:
                    dedup_key = item.get("detail_url") or f"{item.get('language')}:{item.get('title')}"
                    if dedup_key not in candidates_by_key:
                        candidates_by_key[dedup_key] = item
                    else:
                        existing = candidates_by_key[dedup_key]
                        for k, v in item.items():
                            if existing.get(k) is None and v is not None:
                                existing[k] = v
                        if item.get("is_live_priority"):
                            existing["is_live_priority"] = True
            except Exception as exc:
                metrics["movie_errors"] += 1
                logger.error("[%s] Failed category listing %s (%s): %s", self.source_name, cat_lang, url, exc)
                error_events.append(
                    {
                        "stage": "scrape_listing",
                        "source": self.source_name,
                        "url": url,
                        "movie_title": None,
                        "exception_type": type(exc).__name__,
                        "message": str(exc),
                    }
                )

        # Keep live running movies prioritized ahead of static archive rows
        candidates = sorted(
            candidates_by_key.values(),
            key=lambda c: (not bool(c.get("is_live_priority")), -(int(c.get("day_count") or 0) > 0)),
        )
        if limit is not None and limit > 0:
            candidates = candidates[:limit]
        metrics["listings_discovered"] = len(candidates)

        results: list[RawScrapedMovie] = []
        req_lang_lower = (language or "all").strip().lower()
        total_candidates = len(candidates)

        for idx, item in enumerate(candidates, start=1):
            if idx == 1 or idx % 20 == 0 or idx == total_candidates:
                logger.info("[%s] Scraping movie %d/%d: %s", self.source_name, idx, total_candidates, item.get("title"))
            movie_title = item.get("title", "Unknown")
            detail_url = item.get("detail_url")
            try:
                detail_html = self.fetch_html(detail_url) if detail_url else ""
                raw_detail = (
                    self.parse_movie_details(detail_html, item)
                    if detail_html
                    else dict(item)
                )

                # If a live /quicknews/*_Box_Office_Collection_Day_* URL exists and adds missing or newer Day N data, fetch it
                qn_url = raw_detail.get("quicknews_url")
                qn_match = _QUICKNEWS_DAY_RE.search(qn_url) if qn_url else None
                qn_day_num = int(qn_match.group("day")) if qn_match else 0
                cur_max_day = int(raw_detail.get("max_day_seen") or 0)
                needs_quicknews = bool(
                    qn_url
                    and (
                        raw_detail.get("india_net_cr") in {None, 0, 0.0}
                        or not raw_detail.get("daily_breakdown")
                        or qn_day_num > cur_max_day
                    )
                )
                if needs_quicknews and qn_url:
                    try:
                        qn_html = self.fetch_html(qn_url)
                        qn_parsed = self.parse_quicknews_day_page(
                            qn_html,
                            release_date=raw_detail.get("release_date"),
                            fallback_year=raw_detail.get("release_year"),
                        )
                        raw_detail = self._merge_quicknews_into_detail(raw_detail, qn_parsed, qn_url)
                    except Exception as qn_exc:
                        logger.debug("[%s] Quicknews enrichment skipped for '%s': %s", self.source_name, movie_title, qn_exc)

                # Skip small un-tracked releases that have zero box office figures anywhere on Sacnilk
                if (
                    float(raw_detail.get("india_net_cr") or 0.0) <= 0.0
                    and raw_detail.get("worldwide_gross_cr") is None
                    and raw_detail.get("india_gross_cr") is None
                    and not raw_detail.get("daily_breakdown")
                ):
                    continue

                # Regional language filter safeguard after full Key Details language detection
                if (
                    req_lang_lower not in {"all", "pan-india"}
                    and str(raw_detail.get("language") or "").lower() != req_lang_lower
                ):
                    continue

                normalized = self.normalize(raw_detail)
                results.append(normalized)
                metrics["movies_scraped"] += 1
            except Exception as exc:
                metrics["movie_errors"] += 1
                logger.exception(
                    "[%s] Isolated parse failure for '%s' (%s): %s",
                    self.source_name,
                    movie_title,
                    detail_url or item.get("source_url"),
                    exc,
                )
                error_events.append(
                    {
                        "stage": "scrape_movie",
                        "source": self.source_name,
                        "url": detail_url or item.get("source_url"),
                        "movie_title": movie_title,
                        "exception_type": type(exc).__name__,
                        "message": str(exc),
                    }
                )

        return results, metrics, error_events

    def normalize(self, raw_record: dict[str, Any]) -> RawScrapedMovie:
        """Convert extracted Sacnilk dictionary into a strict RawScrapedMovie."""
        daily_entries = [
            DailyCollectionEntry.model_validate(item)
            for item in (raw_record.get("daily_breakdown") or [])
        ]
        india_net = raw_record.get("india_net_cr")
        if india_net is None:
            india_net = round(sum(e.india_net_cr for e in daily_entries), 4)

        extra_metrics: dict[str, Any] = {}
        if daily_entries:
            latest_entry = daily_entries[-1]
            if latest_entry.shows is not None:
                extra_metrics["latest_shows"] = latest_entry.shows
            if latest_entry.occupancy_pct is not None:
                extra_metrics["latest_occupancy_pct"] = latest_entry.occupancy_pct
        if raw_record.get("quicknews_url"):
            extra_metrics["quicknews_url"] = raw_record["quicknews_url"]

        return RawScrapedMovie(
            source=self.source_name,
            source_url=raw_record.get("detail_url") or raw_record.get("source_url") or self.base_url,
            title=str(raw_record["title"]).strip(),
            language=str(raw_record.get("language") or "Hindi").strip(),
            release_date=raw_record.get("release_date"),
            release_year=raw_record.get("release_year"),
            budget_cr=raw_record.get("budget_cr"),
            india_net_cr=float(india_net or 0.0),
            india_gross_cr=raw_record.get("india_gross_cr"),
            overseas_cr=raw_record.get("overseas_cr"),
            worldwide_gross_cr=raw_record.get("worldwide_gross_cr"),
            verdict=normalize_verdict(raw_record.get("verdict")),
            day_count=int(
                raw_record.get("day_count")
                or len([e for e in daily_entries if e.day >= 1])
            ),
            daily_breakdown=daily_entries,
            cast_summary=raw_record.get("cast_summary"),
            original_language=raw_record.get("original_language"),
            poster_url=raw_record.get("poster_url"),
            backdrop_url=raw_record.get("backdrop_url"),
            extra_metrics=extra_metrics,
        )
