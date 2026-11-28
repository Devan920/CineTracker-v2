"""Secondary Koimoi scraper for Bollywood, Regional, and Pan-India cross-verification."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from bs4 import Tag

from scrapers.base_scraper import BaseScraper
from utils.currency_parser import (
    normalize_verdict,
    parse_inr_to_crores,
    parse_percentage,
)
from utils.logger import get_logger
from utils.models import DailyCollectionEntry, RawScrapedMovie

logger = get_logger("scrapers.koimoi")

_ARTICLE_URL_KEYWORDS = (
    "box-office-collection",
    "box-office-day-",
    "worldwide-box-office",
)
_NON_INDIAN_MARKERS = (
    "north america",
    "china box office",
    "global box office",
    "hollywood",
    "mcu",
    "dc",
)
_EDITORIAL_SKIP_MARKERS = (
    "advance-booking",
    "prediction",
    "pre-sales",
    "trailer",
    "review",
    "ott-release",
)
_PROSE_INR_RE = re.compile(
    r"(?:earned|minted|collected|opened\s+(?:at|to)|stands\s+at|total(?:ed|led)?\s+(?:of|to)?|india\s+net\s+(?:of|is|stands\s+at)?)"
    r"\s+(?:around|nearly|approximately|almost|over|close\s+to)?\s*"
    r"((?:₹|rs\.?|inr)?\s*\d+(?:,\d{2,3})*(?:\.\d+)?\s*(?:crores?|crs?\.?|cr\.?|lakhs?|lacs?|l\.?))",
    re.IGNORECASE,
)
_HEADLINE_SPLIT_RE = re.compile(
    r"\s+(?:worldwide\s+)?(?:hindi\s+)?box\s+office\b",
    re.IGNORECASE,
)
_DAY_NUM_RE = re.compile(r"\bDay\s+(\d+)\b", re.IGNORECASE)
_BULLET_METRIC_RE = re.compile(
    r"^\s*(?P<label>[A-Za-z\s]+?)\s*[–\-:]\s*(?P<val>.+?)\s*$"
)
_DAY_BULLET_RE = re.compile(
    r"^\s*Day\s+(?P<day>\d+)\s*(?:\([^)]*\))?\s*[–\-:]\s*(?P<val>.+?)\s*$",
    re.IGNORECASE,
)
_WEEK_BULLET_RE = re.compile(
    r"^\s*Week\s+(?P<week>\d+)\s*(?:\((?P<days>\d+)\s*days?\))?\s*[–\-:]\s*(?P<val>.+?)\s*$",
    re.IGNORECASE,
)


class KoimoiScraper(BaseScraper):
    """Scraper targeting Koimoi verdict tables and daily box office articles."""

    source_name = "koimoi"

    @staticmethod
    def _clean_header(text: str) -> str:
        return re.sub(r"\s+", " ", text).strip().lower()

    @staticmethod
    def _parse_article_title_to_movie(headline: str) -> tuple[str, str | None]:
        """Extract clean movie name and optional dubbed language from Koimoi article headline."""
        cleaned = re.sub(r"\s+", " ", headline).strip()
        parts = _HEADLINE_SPLIT_RE.split(cleaned, maxsplit=1)
        movie_part = parts[0].strip(" :-–—")
        lang_hint: str | None = None
        if re.search(r"\bhindi\b", cleaned, re.I):
            lang_hint = "Hindi"
        elif re.search(r"\bmalayalam\b|\bmollywood\b", cleaned, re.I):
            lang_hint = "Malayalam"
        elif re.search(r"\btamil\b|\bkollywood\b", cleaned, re.I):
            lang_hint = "Tamil"
        elif re.search(r"\btelugu\b|\btollywood\b", cleaned, re.I):
            lang_hint = "Telugu"
        elif re.search(r"\bkannada\b|\bsandalwood\b", cleaned, re.I):
            lang_hint = "Kannada"
        return movie_part, lang_hint

    def _parse_verdict_table(
        self,
        table: Tag,
        *,
        language: str,
        source_url: str,
        min_year: int,
    ) -> list[dict[str, Any]]:
        rows = table.find_all("tr")
        if len(rows) <= 1:
            return []

        headers = [
            self._clean_header(cell.get_text(" ", strip=True))
            for cell in rows[0].find_all(["th", "td"])
        ]
        col_idx: dict[str, int] = {}
        for idx, h in enumerate(headers):
            if "release year" in h or h == "year":
                col_idx["year"] = idx
            elif "movie name" in h or "film" in h or "movie" in h:
                col_idx["title"] = idx
            elif "worldwide" in h or "collections" == h:
                col_idx["worldwide"] = idx
            elif "india lifetime" in h or "india total" in h or "collection (inr cr)" in h:
                col_idx["india_net"] = idx
            elif "opening day" in h:
                col_idx["opening_day"] = idx
            elif "verdict" in h:
                col_idx["verdict"] = idx

        if "title" not in col_idx:
            return []

        items: list[dict[str, Any]] = []
        for tr in rows[1:]:
            cells = tr.find_all(["td", "th"])
            if col_idx["title"] >= len(cells):
                continue

            title = cells[col_idx["title"]].get_text(" ", strip=True)
            if not title:
                continue

            release_year: int | None = None
            if "year" in col_idx and col_idx["year"] < len(cells):
                yr_txt = cells[col_idx["year"]].get_text(" ", strip=True)
                if yr_txt.isdigit():
                    release_year = int(yr_txt)
                    if release_year < min_year:
                        continue

            def _get_cr(key: str) -> float | None:
                i = col_idx.get(key)
                if i is None or i >= len(cells):
                    return None
                return parse_inr_to_crores(cells[i].get_text(" ", strip=True))

            india_net = _get_cr("india_net")
            worldwide = _get_cr("worldwide")
            opening_day = _get_cr("opening_day")

            if india_net is None and worldwide is None and opening_day is None:
                continue

            verdict = None
            if "verdict" in col_idx and col_idx["verdict"] < len(cells):
                verdict = normalize_verdict(cells[col_idx["verdict"]].get_text(" ", strip=True))

            daily_breakdown: list[dict[str, Any]] = []
            if opening_day is not None and opening_day > 0:
                daily_breakdown.append(
                    {
                        "day": 1,
                        "date": None,
                        "india_net_cr": opening_day,
                        "change_pct": None,
                    }
                )

            items.append(
                {
                    "source": self.source_name,
                    "source_url": source_url,
                    "detail_url": None,
                    "has_inline_full_record": True,
                    "title": title,
                    "language": language,
                    "release_year": release_year,
                    "india_net_cr": india_net if india_net is not None else 0.0,
                    "worldwide_gross_cr": worldwide,
                    "verdict": verdict,
                    "day_count": len(daily_breakdown),
                    "daily_breakdown": daily_breakdown,
                }
            )

        return items

    def parse_listings(
        self,
        html: str,
        *,
        language: str | None = None,
        base_url: str | None = None,
    ) -> list[dict[str, Any]]:
        """Parse Koimoi verdict tables and recent Indian box office article links."""
        soup = self.make_soup(html)
        tree = self.make_tree(html)
        listing_sel = self.selectors.get("listing", {})
        eff_lang = (language or "Hindi").strip()
        src_url = base_url or self.base_url
        current_year = datetime.now().year
        min_year = current_year - 1

        candidates: list[dict[str, Any]] = []

        # 1. Extract TablePress / verdict tables if present on page
        tables = self.select_nodes(soup, listing_sel.get("verdict_table"), tree=tree)
        for tbl in tables:
            candidates.extend(
                self._parse_verdict_table(
                    tbl,
                    language=eff_lang,
                    source_url=src_url,
                    min_year=min_year,
                )
            )

        # 2. On hub pages (e.g. /box-office/), also collect daily Indian box office articles
        if not tables or src_url.rstrip("/").endswith("/box-office"):
            links = self.select_nodes(soup, listing_sel.get("daily_article_links"), tree=tree)
            seen_article_urls: set[str] = set()
            for a in links:
                href = a.get("href") or ""
                if not href or "/hits-flops/" in href or "/highest-grossers/" in href:
                    continue
                full_url = self.resolve_url(href)
                if full_url in seen_article_urls:
                    continue
                low_url = full_url.lower()
                if any(bad in low_url for bad in _EDITORIAL_SKIP_MARKERS):
                    continue
                if not any(kw in low_url for kw in _ARTICLE_URL_KEYWORDS):
                    continue
                text = a.get_text(" ", strip=True)
                combined = f"{text} {full_url}".lower()
                if any(bad in combined for bad in _NON_INDIAN_MARKERS):
                    continue

                movie_title, lang_hint = self._parse_article_title_to_movie(
                    text or full_url.rstrip("/").split("/")[-1].replace("-", " ").title()
                )
                if not movie_title or len(movie_title) < 2:
                    continue

                seen_article_urls.add(full_url)
                candidates.append(
                    {
                        "source": self.source_name,
                        "source_url": src_url,
                        "detail_url": full_url,
                        "has_inline_full_record": False,
                        "title": movie_title,
                        "language": lang_hint or eff_lang,
                        "release_year": current_year,
                    }
                )
                if len(seen_article_urls) >= 12:
                    break

        return candidates

    def parse_movie_details(
        self,
        html: str,
        listing_item: dict[str, Any],
    ) -> dict[str, Any]:
        """Parse a Koimoi daily box office article for India Net, Gross, Overseas, Worldwide & Days."""
        soup = self.make_soup(html)
        tree = self.make_tree(html)
        detail_sel = self.selectors.get("detail", {})

        title_nodes = self.select_nodes(soup, detail_sel.get("article_title"), tree=tree)
        headline = title_nodes[0].get_text(" ", strip=True) if title_nodes else listing_item.get("title", "")
        parsed_title, lang_hint = self._parse_article_title_to_movie(headline)
        title = parsed_title or listing_item.get("title", "")

        india_net: float | None = listing_item.get("india_net_cr")
        india_gross: float | None = listing_item.get("india_gross_cr")
        overseas: float | None = listing_item.get("overseas_cr")
        worldwide: float | None = listing_item.get("worldwide_gross_cr")
        budget: float | None = listing_item.get("budget_cr")
        verdict: str | None = listing_item.get("verdict")
        daily_map: dict[int, dict[str, Any]] = {}
        week_totals: dict[int, float] = {}

        # Parse bullet lists (e.g. "India net – 69.7 crore", "Week 1 – 581.58 crore", "Day 1 – 12.5 crore")
        list_items = self.select_nodes(soup, detail_sel.get("article_lists"), tree=tree)
        for li in list_items:
            line = li.get_text(" ", strip=True)
            if not line:
                continue

            day_m = _DAY_BULLET_RE.match(line)
            if day_m:
                day_num = int(day_m.group("day"))
                val = parse_inr_to_crores(day_m.group("val"))
                if val is not None:
                    daily_map[day_num] = {
                        "day": day_num,
                        "date": None,
                        "india_net_cr": val,
                        "change_pct": None,
                    }
                continue

            week_m = _WEEK_BULLET_RE.match(line)
            if week_m:
                week_num = int(week_m.group("week"))
                val = parse_inr_to_crores(week_m.group("val"))
                if val is not None:
                    week_totals[week_num] = val
                continue

            m = _BULLET_METRIC_RE.match(line)
            if not m:
                continue
            label = m.group("label").strip().lower()
            val = parse_inr_to_crores(m.group("val"))
            if val is None:
                continue
            if "india net" in label or label in {"total", "india total", "grand total", "net collection"}:
                india_net = val
            elif "india gross" in label:
                india_gross = val
            elif "overseas" in label:
                overseas = val
            elif "worldwide" in label:
                worldwide = val
            elif "budget" in label:
                budget = val

        # Parse embedded day-wise tables if present inside article
        tables = self.select_nodes(soup, detail_sel.get("article_tables"), tree=tree)
        for tbl in tables:
            rows = tbl.find_all("tr")
            if len(rows) <= 1:
                continue
            hdrs = [self._clean_header(c.get_text(" ", strip=True)) for c in rows[0].find_all(["th", "td"])]
            day_col = next((i for i, h in enumerate(hdrs) if "day" in h), None)
            val_col = next(
                (i for i, h in enumerate(hdrs) if "collection" in h or "net" in h or "cr" in h),
                1 if len(hdrs) > 1 else None,
            )
            pct_col = next((i for i, h in enumerate(hdrs) if "change" in h or "%" in h), None)
            if day_col is None or val_col is None:
                continue

            for tr in rows[1:]:
                cells = tr.find_all(["td", "th"])
                if max(day_col, val_col) >= len(cells):
                    continue
                day_txt = cells[day_col].get_text(" ", strip=True)
                dm = _DAY_NUM_RE.search(day_txt)
                if not dm:
                    continue
                day_num = int(dm.group(1))
                val = parse_inr_to_crores(cells[val_col].get_text(" ", strip=True))
                if val is None:
                    continue
                pct = (
                    parse_percentage(cells[pct_col].get_text(" ", strip=True))
                    if pct_col is not None and pct_col < len(cells)
                    else None
                )
                daily_map[day_num] = {
                    "day": day_num,
                    "date": None,
                    "india_net_cr": val,
                    "change_pct": pct,
                }

        # Headline day count fallback
        day_m_head = _DAY_NUM_RE.search(headline)
        headline_day = int(day_m_head.group(1)) if day_m_head else 0

        if india_net is None and week_totals:
            india_net = round(sum(week_totals.values()), 4)
        elif india_net is None and daily_map:
            # Only sum daily_map as total when it starts at Day 0/1 and is contiguous
            keys = sorted(daily_map)
            if keys[0] <= 1 and len(keys) >= keys[-1]:
                india_net = round(sum(item["india_net_cr"] for item in daily_map.values()), 4)
        elif india_net is None:
            # Prose fallback when Koimoi embeds INR figure in lead article paragraphs
            prose_txt = " ".join(p.get_text(" ", strip=True) for p in soup.select("article p, p")[:8])
            m_prose = _PROSE_INR_RE.search(prose_txt)
            if m_prose:
                india_net = parse_inr_to_crores(m_prose.group(1))
        if india_net is None and not daily_map:
            raise ValueError(f"No INR India Net collection found in Koimoi article: {headline}")

        daily_breakdown = [daily_map[k] for k in sorted(daily_map)]
        day_count = max(
            [headline_day, len(daily_breakdown), *(daily_map.keys() or [0])]
        )

        return {
            **listing_item,
            "title": title,
            "language": lang_hint or listing_item.get("language") or "Hindi",
            "budget_cr": budget,
            "india_net_cr": india_net,
            "india_gross_cr": india_gross,
            "overseas_cr": overseas,
            "worldwide_gross_cr": worldwide,
            "verdict": verdict,
            "day_count": day_count,
            "daily_breakdown": daily_breakdown,
        }

    def normalize(self, raw_record: dict[str, Any]) -> RawScrapedMovie:
        """Convert extracted Koimoi dictionary into a strict RawScrapedMovie."""
        daily_entries = [
            DailyCollectionEntry.model_validate(item)
            for item in (raw_record.get("daily_breakdown") or [])
        ]
        return RawScrapedMovie(
            source=self.source_name,
            source_url=raw_record.get("detail_url") or raw_record.get("source_url") or self.base_url,
            title=str(raw_record["title"]).strip(),
            language=str(raw_record.get("language") or "Hindi").strip(),
            release_date=raw_record.get("release_date"),
            release_year=raw_record.get("release_year"),
            budget_cr=raw_record.get("budget_cr"),
            india_net_cr=float(raw_record.get("india_net_cr") or 0.0),
            india_gross_cr=raw_record.get("india_gross_cr"),
            overseas_cr=raw_record.get("overseas_cr"),
            worldwide_gross_cr=raw_record.get("worldwide_gross_cr"),
            verdict=normalize_verdict(raw_record.get("verdict")),
            day_count=int(raw_record.get("day_count") or len(daily_entries)),
            daily_breakdown=daily_entries,
            cast_summary=raw_record.get("cast_summary"),
            original_language=raw_record.get("original_language"),
        )
