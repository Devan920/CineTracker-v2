"""Unit tests for currency parsing, fuzzy matching, HTML parsers, reconciliation, TMDB, and Supabase sync."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from config.settings import ConfigurationError, Settings
from database.supabase_sync import SupabaseSync
from enrichment.tmdb_client import TMDBClient, build_fuzzy_title_variants
from utils.tmdb_client import TMDBClient as UtilsTMDBClient
from scrapers.koimoi_scraper import KoimoiScraper
from scrapers.sacnilk_scraper import SacnilkScraper
from scrapers.tracker_aggregator import TrackerAggregator
from utils.currency_parser import (
    normalize_verdict,
    parse_date_flexible,
    parse_inr_to_crores,
    parse_percentage,
)
from utils.models import DailyCollectionEntry, MovieBoxOfficeRecord, RawScrapedMovie
from utils.title_matcher import TitleMatcher, canonical_slug, normalize_title


# =============================================================================
# 1. Currency, Percentage, Date & Verdict Parser Tests
# =============================================================================


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("₹ 12.45 Cr", 12.45),
        ("₹1,149.30 Cr", 1149.3),
        ("45.2 Lakhs", 0.452),
        ("₹45 L", 0.45),
        ("1.20 Crore", 1.2),
        ("1.20 Crores", 1.2),
        ("1803.1*", 1803.1),
        ("242 (4-day)", 242.0),
        ("581.58 (8-day)", 581.58),
        ("₹ 50,00,000", 0.5),
        ("TBA", None),
        ("-", None),
        ("—", None),
        ("N/A", None),
        ("", None),
        (None, None),
        ("$500 million", None),
        ("-5.0 Cr", None),
    ],
)
def test_parse_inr_to_crores_edge_cases(raw: Any, expected: float | None) -> None:
    result = parse_inr_to_crores(raw)
    if expected is None:
        assert result is None
    else:
        assert result == pytest.approx(expected, rel=1e-4)


def test_parse_percentage_variants() -> None:
    assert parse_percentage("down ▼ 12.4%") == -12.4
    assert parse_percentage("up ▲ 45.3%") == 45.3
    assert parse_percentage("no change = 0.0%") == 0.0
    assert parse_percentage("+18.5%") == 18.5
    assert parse_percentage("-22.1%") == -22.1
    assert parse_percentage("—") is None


def test_parse_date_flexible_and_verdict() -> None:
    assert parse_date_flexible("21 Aug 2026") == "2026-08-21"
    assert parse_date_flexible("Day 1 Thu 5 Nov", default_year=2026) == "2026-11-05"
    assert parse_date_flexible("2026-11-05") == "2026-11-05"
    assert normalize_verdict("All Time Blockbuster") == "All Time Blockbuster"
    assert normalize_verdict("SUPER DUPER HIT") == "Super Hit"
    assert normalize_verdict("Below Average") == "Below Average"
    assert normalize_verdict("—") is None


# =============================================================================
# 2. Fuzzy Title Matching & Canonical Slug Tests
# =============================================================================


def test_title_matcher_subtitle_and_canonical_slug() -> None:
    matcher = TitleMatcher(threshold=84.0)
    assert matcher.is_match("Aadu 3: One Last Ride", "Aadu 3")
    assert matcher.is_match("Dhurandhar 2: The Revenge", "Dhurandhar 2")
    assert matcher.is_match("Pushpa Part II", "Pushpa 2")

    # Order-independent canonical slug resolution
    slug_a = matcher.choose_canonical_slug(["Aadu 3: One Last Ride", "Aadu 3"])
    slug_b = matcher.choose_canonical_slug(["Aadu 3", "Aadu 3: One Last Ride"])
    assert slug_a == "aadu-3"
    assert slug_b == "aadu-3"


def test_title_matcher_sequel_guard_blocks_false_positives() -> None:
    matcher = TitleMatcher(threshold=84.0)
    assert not matcher.is_match("Drishyam 2", "Drishyam 3")
    assert not matcher.is_match("Aadu 2", "Aadu 3")
    assert not matcher.is_match("KGF Chapter 1", "KGF Chapter 2")
    assert not matcher.is_match("Dhurandhar", "Dhurandhar 2")
    assert not matcher.is_match("Dhurandhar", "Dhurandhar 2: The Revenge")
    assert matcher.is_match("Ramayana", "Ramayana Part 1")
    assert normalize_title("I, Nobody (Malayalam)") == "i nobody"
    assert canonical_slug("Drishyam 3 (Hindi)", language="Hindi") == "drishyam-3-hindi"


# =============================================================================
# 3. Sacnilk & Koimoi HTML Fixture Parsing Tests
# =============================================================================


SACNILK_LISTING_HTML = """
<html>
  <body>
    <table class="ds-t ds-bt ds-bt--lang">
      <tr>
        <th>#</th><th>Film</th><th>Malayalam net ▼</th><th>India net</th>
        <th>India gross</th><th>Overseas</th><th>Worldwide</th>
      </tr>
      <tr>
        <td>1</td>
        <td>
          <a href="/movie/Aadu_3_2026">Aadu 3</a>
          Malayalam · Mollywood · released 19 Mar 2026 Blockbuster
        </td>
        <td>₹95.20 Cr</td>
        <td>₹102.50 Cr</td>
        <td>₹118.40 Cr</td>
        <td>₹64.10 Cr</td>
        <td>₹182.50 Cr</td>
      </tr>
      <tr>
        <td>2</td>
        <td>
          <a href="/movie/ramayana_part_1_2026">Ramayana</a>
          Hindi · Bollywood · released 5 Nov 2026 Day 23 ₹8.45 Cr down ▼ 12.4%
        </td>
        <td>₹54.30 Cr</td>
        <td>₹1,000.55 Cr</td>
        <td>₹1,195.10 Cr</td>
        <td>₹595.00 Cr</td>
        <td>₹1,790.10 Cr</td>
      </tr>
    </table>
    <table class="ds-t ds-bt">
      <tr><td></td><td>Total, 2 films shown</td><td>₹149.50 Cr</td><td>₹1,103.05 Cr</td><td>₹1,313.50 Cr</td><td>₹659.10 Cr</td><td>₹1,972.60 Cr</td></tr>
    </table>
  </body>
</html>
"""

SACNILK_DETAIL_HTML = """
<html>
  <head>
    <title>Aadu 3 (2026) Box Office Collection | Sacnilk</title>
    <meta property="og:image" content="https://cdn.sacnilk.com/image/movie/2026/aadu3.jpg" />
  </head>
  <body>
    <img src="https://cdn.sacnilk.com/image/SacnilkNewLogo100.png" alt="Sacnilk Logo" />
    <h1>Aadu 3: One Last Ride</h1>
    <div class="ds-hero-fig">
      <div class="ds-hero-fig__lbl">Worldwide gross · 3 days</div>
      <div class="ds-hero-fig__v">₹182.50 Cr</div>
    </div>
    <div class="ds-stats ds-mv-stats">
      <div class="ds-stat"><div class="ds-stat__k">India net</div><div class="ds-stat__v">₹102.50 Cr</div></div>
      <div class="ds-stat"><div class="ds-stat__k">India gross</div><div class="ds-stat__v">₹118.40 Cr</div></div>
      <div class="ds-stat"><div class="ds-stat__k">Overseas</div><div class="ds-stat__v">₹64.10 Cr</div></div>
      <div class="ds-stat"><div class="ds-stat__k">Budget</div><div class="ds-stat__v">₹35.00 Cr</div></div>
      <div class="ds-stat"><div class="ds-stat__k">Verdict</div><div class="ds-stat__v">Blockbuster</div></div>
    </div>
    <div class="bg-white rounded-lg p-4 border border-gray-200">
      <span>Theatrical Release: 19 Mar 2026</span>
    </div>
    <div class="cast-box">
      <h3>Cast &amp; Crew</h3>
      <span>🎭 Cast</span>
      <span>Jayasurya</span>
      <span>Vinayakan</span>
      <span>Saiju Kurup</span>
    </div>
    <table class="ds-t ds-ww-t">
      <tr><th>Day</th><th>India net</th><th>India gross</th><th>vs day before</th><th>Shows</th><th>Occupancy</th></tr>
      <tr><td>Day 0 Wed 18 Mar · 400 shows</td><td>₹1.25 Cr</td><td>₹1.45 Cr</td><td>—</td><td>400</td><td>52%</td></tr>
      <tr><td>Day 1 Thu 19 Mar · 1,400 shows</td><td>₹8.50 Cr</td><td>₹9.90 Cr</td><td>—</td><td>1400</td><td>62%</td></tr>
      <tr><td>Day 2 Fri 20 Mar · 1,450 shows</td><td>₹6.80 Cr</td><td>₹7.90 Cr</td><td>down ▼ 20.0%</td><td>1450</td><td>54%</td></tr>
      <tr><td>Day 3 Sat 21 Mar · 1,500 shows</td><td>₹45 L</td><td>₹52 L</td><td>down ▼ 93.4%</td><td>1500</td><td>48%</td></tr>
      <tr><td>Total · 3 days</td><td>₹17.00 Cr</td><td>₹19.77 Cr</td><td>—</td><td>4750</td><td></td></tr>
    </table>
  </body>
</html>
"""

KOIMOI_VERDICT_HTML = """
<html>
  <body>
    <table class="tablepress tablepress-id-550">
      <tr>
        <th>Release Year</th>
        <th>Movie Name</th>
        <th>Worldwide Total (INR Cr)</th>
        <th>India Total (INR Cr)</th>
        <th>Opening Day (INR Cr)</th>
        <th>Opening Week (INR Cr)</th>
        <th>Verdict</th>
      </tr>
      <tr>
        <td>2026</td>
        <td>Aadu 3</td>
        <td>185.0*</td>
        <td>104.0*</td>
        <td>8.75</td>
        <td>52.00</td>
        <td>HIT</td>
      </tr>
      <tr>
        <td>2019</td>
        <td>Old Film</td>
        <td>20.0</td>
        <td>15.0</td>
        <td>2.0</td>
        <td>10.0</td>
        <td>FLOP</td>
      </tr>
    </table>
  </body>
</html>
"""

KOIMOI_ARTICLE_HTML = """
<html>
  <body>
    <h1 class="entry-title">OM Worldwide Box Office Day 7: Crosses Milestone</h1>
    <div class="td-post-content">
      <ul>
        <li>India net – 69.7 crore</li>
        <li>India gross – 82.26 crore</li>
        <li>Overseas gross – 27.25 crore</li>
        <li>Worldwide gross – 109.51 crore</li>
      </ul>
      <table>
        <tr><th>Day</th><th>India Net Collection</th><th>Change</th></tr>
        <tr><td>Day 1</td><td>18.10 Cr</td><td>—</td></tr>
        <tr><td>Day 2</td><td>12.40 Cr</td><td>-31.49%</td></tr>
      </table>
    </div>
  </body>
</html>
"""


def test_sacnilk_listing_and_detail_parsing() -> None:
    scraper = SacnilkScraper()
    # Regional Malayalam filter should exclude dubbed Hindi entry 'Ramayana'
    listings = scraper.parse_listings(SACNILK_LISTING_HTML, language="Malayalam")
    assert len(listings) == 1
    assert listings[0]["title"] == "Aadu 3"
    assert listings[0]["language"] == "Malayalam"
    assert listings[0]["release_date"] == "2026-03-19"

    # Pan-India category includes both
    pan_listings = scraper.parse_listings(SACNILK_LISTING_HTML, language="Pan-India")
    assert len(pan_listings) == 2

    raw_detail = scraper.parse_movie_details(SACNILK_DETAIL_HTML, listings[0])
    normalized = scraper.normalize(raw_detail)
    assert normalized.title == "Aadu 3: One Last Ride"
    assert normalized.india_net_cr == pytest.approx(102.5)
    assert normalized.worldwide_gross_cr == pytest.approx(182.5)
    assert normalized.budget_cr == pytest.approx(35.0)
    assert normalized.verdict == "Blockbuster"
    assert normalized.day_count == 3
    assert len(normalized.daily_breakdown) == 4
    assert normalized.daily_breakdown[0].day == 0
    assert normalized.daily_breakdown[0].india_net_cr == pytest.approx(1.25)
    assert normalized.daily_breakdown[1].date == "2026-03-19"
    assert normalized.daily_breakdown[1].shows == 1400
    assert normalized.daily_breakdown[1].occupancy_pct == pytest.approx(62.0)
    assert normalized.daily_breakdown[3].india_net_cr == pytest.approx(0.45)
    assert normalized.daily_breakdown[2].change_pct == pytest.approx(-20.0)
    assert normalized.poster_url == "https://cdn.sacnilk.com/image/movie/2026/aadu3.jpg"
    assert "Jayasurya" in (normalized.cast_summary or "")
    assert "Cast" not in (normalized.cast_summary or "")


def test_sacnilk_homepage_live_feed_and_quicknews_merge() -> None:
    scraper = SacnilkScraper()
    homepage_html = """
    <html><body>
      <div>
        <a href="/movie/Avengers_Doomsday_2026"></a>
        Avengers: Doomsday Advance booking Hindi · Releases Thu 17 Dec ₹71.47 Cr
      </div>
      <div>
        <a href="/movie/Hail_Mary_2026"></a>
        Hail Mary Release week · Day 2 Malayalam · Released Thu 26 Nov ₹1.20 Cr
        <a href="/quicknews/Hail_Mary_2026_Box_Office_Collection_Day_2">Day 2 collection</a>
      </div>
      <div>
        <a href="/movie/The_Great_Punjab_Robbery_2026">The Great Punjab Robbery OTT 27 DAYS 25 Dec</a>
      </div>
      <table class="w-full boxoffice-table">
        <tr><th>Movie</th><th>30 Days</th><th>Worldwide</th><th>Details</th></tr>
        <tr>
          <td>Ramayana Bollywood • 2026</td>
          <td>₹1,000.55 Cr</td>
          <td>₹1,790.10 Cr</td>
          <td><a href="/movie/ramayana_part_1_2026">Details</a></td>
        </tr>
      </table>
      <a href="/quicknews/Cosmic_Samson_2026_Box_Office_Collection_Day_2">Day 2</a>
    </body></html>
    """
    candidates = scraper.parse_listings(
        homepage_html, language="Pan-India", base_url="https://www.sacnilk.com/"
    )
    slugs = [c["detail_url"].split("/")[-1] for c in candidates]
    # Upcoming advance booking & OTT cards must be excluded
    assert "Avengers_Doomsday_2026" not in slugs
    assert "The_Great_Punjab_Robbery_2026" not in slugs
    assert "Ramayana" in [c["title"] for c in candidates]
    assert "Hail_Mary_2026" in slugs
    assert "Cosmic_Samson_2026" in slugs

    qn_html = """
    <html><body>
      <div class="bg-white rounded-lg">Languages: Malayalam</div>
      <div class="bg-white rounded-lg">Theatrical Release: 26 Nov 2026</div>
      <table class="ds-t ds-dp-t">
        <tr><th>Day</th><th>India net</th><th>India gross</th><th>Change</th><th>Shows</th><th>Occ.</th></tr>
        <tr><td>Day 1 Thu 26 Nov</td><td>₹75 L —</td><td>₹87 L</td><td>—</td><td>717</td><td>27.0%</td></tr>
        <tr><td>Day 2 Live Fri 27 Nov</td><td>₹1.20 Cr —</td><td>₹1.40 Cr</td><td>up ▲ 60.0%</td><td>707</td><td>42.0%</td></tr>
        <tr><td>Total · 2 days</td><td>₹1.95 Cr</td><td>₹2.27 Cr</td><td></td><td>1,424</td><td></td></tr>
      </table>
    </body></html>
    """
    qn_parsed = scraper.parse_quicknews_day_page(qn_html)
    assert qn_parsed["india_net_cr"] == pytest.approx(1.95)
    assert qn_parsed["india_gross_cr"] == pytest.approx(2.27)
    assert qn_parsed["detected_language"] == "Malayalam"
    assert qn_parsed["daily_breakdown"][1]["shows"] == 707
    assert qn_parsed["daily_breakdown"][1]["occupancy_pct"] == pytest.approx(42.0)

    merged = scraper._merge_quicknews_into_detail(
        {"india_net_cr": 0.0, "daily_breakdown": []},
        qn_parsed,
        "https://www.sacnilk.com/quicknews/Hail_Mary_2026_Box_Office_Collection_Day_2",
    )
    assert merged["india_net_cr"] == pytest.approx(1.95)
    assert merged["worldwide_gross_cr"] == pytest.approx(2.27)
    assert merged["day_count"] == 2


def test_koimoi_table_and_article_parsing() -> None:
    scraper = KoimoiScraper()
    items = scraper.parse_listings(KOIMOI_VERDICT_HTML, language="Malayalam")
    # 2019 film should be filtered out as historical
    assert len(items) == 1
    rec = scraper.normalize(items[0])
    assert rec.title == "Aadu 3"
    assert rec.india_net_cr == pytest.approx(104.0)
    assert rec.worldwide_gross_cr == pytest.approx(185.0)
    assert rec.verdict == "Hit"
    assert rec.daily_breakdown[0].india_net_cr == pytest.approx(8.75)

    detail = scraper.parse_movie_details(
        KOIMOI_ARTICLE_HTML,
        {"title": "OM", "language": "Tamil", "source_url": "https://www.koimoi.com/box-office/om/"},
    )
    art_rec = scraper.normalize(detail)
    assert art_rec.title == "OM"
    assert art_rec.india_net_cr == pytest.approx(69.7)
    assert art_rec.overseas_cr == pytest.approx(27.25)
    assert art_rec.worldwide_gross_cr == pytest.approx(109.51)
    assert art_rec.day_count == 7
    assert len(art_rec.daily_breakdown) == 2

    week_article_html = """
    <html><body>
      <h1 class="entry-title">Ramayana Box Office Collection Day 23</h1>
      <div class="td-post-content">
        <ul>
          <li>Week 1 – 581.58 crore (8 days)</li>
          <li>Week 2 – 319.35 crore</li>
          <li>Week 3 – 122.88 crore</li>
          <li>Day 23 – 8.1 crore</li>
        </ul>
      </div>
    </body></html>
    """
    wk_detail = scraper.parse_movie_details(
        week_article_html,
        {"title": "Ramayana", "language": "Hindi", "source_url": "https://www.koimoi.com/box-office/ramayana/"},
    )
    wk_rec = scraper.normalize(wk_detail)
    assert wk_rec.india_net_cr == pytest.approx(1023.81)
    assert wk_rec.day_count == 23
    assert wk_rec.daily_breakdown[0].day == 23

    # Prediction articles must be skipped in listing discovery, and prose INR collections must parse
    listing_skip_html = """
    <html><body>
      <a href="/box-office/ramayana-box-office-day-24-advance-booking-prediction/">Ramayana Prediction</a>
      <a href="/box-office/bhogi-box-office-collection-day-1/">Bhogi Box Office Collection Day 1</a>
    </body></html>
    """
    filtered_links = scraper.parse_listings(
        listing_skip_html, language="Telugu", base_url="https://www.koimoi.com/box-office/"
    )
    assert len(filtered_links) == 1
    assert filtered_links[0]["title"] == "Bhogi"

    prose_html = """
    <html><body>
      <h1 class="entry-title">Bhogi Box Office Collection Day 1</h1>
      <article><p>The Telugu drama opened at ₹4.25 crore on its first day in India.</p></article>
    </body></html>
    """
    prose_detail = scraper.parse_movie_details(prose_html, filtered_links[0])
    prose_rec = scraper.normalize(prose_detail)
    assert prose_rec.india_net_cr == pytest.approx(4.25)


def test_scraper_isolates_malformed_movie_without_aborting_batch(monkeypatch: pytest.MonkeyPatch) -> None:
    scraper = SacnilkScraper()
    monkeypatch.setattr(scraper, "get_category_urls", lambda language=None: [("Malayalam", "https://example.com/list")])

    two_row_html = """
    <table class="ds-t ds-bt">
      <tr><th>#</th><th>Film</th><th>India net</th><th>India gross</th><th>Overseas</th><th>Worldwide</th></tr>
      <tr><td>1</td><td><a href="/movie/bad">Broken Movie</a> Malayalam · Mollywood</td><td>₹10 Cr</td><td>₹12 Cr</td><td>₹2 Cr</td><td>₹14 Cr</td></tr>
      <tr><td>2</td><td><a href="/movie/good">Good Movie</a> Malayalam · Mollywood</td><td>₹50 Cr</td><td>₹60 Cr</td><td>₹15 Cr</td><td>₹75 Cr</td></tr>
    </table>
    """

    def fake_fetch(url: str) -> str:
        if url.endswith("/list"):
            return two_row_html
        if url.endswith("/bad"):
            raise RuntimeError("Simulated malformed DOM crash")
        return SACNILK_DETAIL_HTML

    monkeypatch.setattr(scraper, "fetch_html", fake_fetch)
    records, metrics, errors = scraper.scrape(language="Malayalam")
    assert len(records) == 1
    assert metrics["movies_scraped"] == 1
    assert metrics["movie_errors"] == 1
    assert len(errors) == 1
    assert errors[0]["movie_title"] == "Broken Movie"


# =============================================================================
# 4. TrackerAggregator Reconciliation, Weighting & Variance Tests
# =============================================================================


def test_aggregator_reconciles_weights_variance_and_daily_merge() -> None:
    sacnilk_rec = RawScrapedMovie(
        source="sacnilk",
        source_url="https://www.sacnilk.com/movie/aadu_3",
        title="Aadu 3: One Last Ride",
        language="Malayalam",
        release_date="2026-03-19",
        india_net_cr=100.0,
        worldwide_gross_cr=180.0,
        verdict="Blockbuster",
        day_count=2,
        daily_breakdown=[
            DailyCollectionEntry(day=1, date="2026-03-19", india_net_cr=10.0, change_pct=None),
            DailyCollectionEntry(day=2, date="2026-03-20", india_net_cr=12.0, change_pct=None),
        ],
    )
    koimoi_rec = RawScrapedMovie(
        source="koimoi",
        source_url="https://www.koimoi.com/box-office/aadu-3",
        title="Aadu 3",
        language="Malayalam",
        release_year=2026,
        india_net_cr=150.0,  # 33.3% relative variance vs 100.0 -> >25% anomaly!
        worldwide_gross_cr=200.0,
        budget_cr=40.0,  # Missing on Sacnilk -> should be backfilled!
        verdict="Hit",
        day_count=3,
        daily_breakdown=[
            DailyCollectionEntry(day=1, date=None, india_net_cr=11.0, change_pct=None),
            DailyCollectionEntry(day=3, date=None, india_net_cr=15.0, change_pct=None),
        ],
    )

    agg = TrackerAggregator(source_weights={"sacnilk": 1.0, "koimoi": 0.75}, variance_threshold=0.25)
    reconciled, summary = agg.reconcile([koimoi_rec, sacnilk_rec])

    assert len(reconciled) == 1
    rec = reconciled[0]
    assert rec.movie_slug == "aadu-3"
    assert rec.primary_source == "sacnilk"
    assert rec.india_net_cr == 100.0  # Sacnilk priority weight wins conflict
    assert rec.budget_cr == 40.0  # Backfilled from Koimoi
    assert rec.variance_flag is True
    assert summary["variance_anomalies"] == 1
    assert summary["multi_source_matches"] == 1
    assert rec.day_count == 3
    assert [d.day for d in rec.daily_breakdown] == [1, 2, 3]
    assert rec.daily_breakdown[0].india_net_cr == 10.0  # Sacnilk Day 1 kept
    assert rec.daily_breakdown[1].change_pct == 20.0  # Auto-calculated from Day 1 -> Day 2
    assert rec.daily_breakdown[2].date == "2026-03-21"  # Date backfilled from release_date
    assert rec.daily_breakdown[2].change_pct == 25.0  # Auto-calculated from Day 2 -> Day 3

    # Verify strict JSON contract keys
    contract = rec.to_contract_dict()
    expected_keys = {
        "movie_slug",
        "title",
        "language",
        "release_date",
        "tmdb_id",
        "poster_url",
        "backdrop_url",
        "budget_cr",
        "india_net_cr",
        "india_gross_cr",
        "overseas_cr",
        "worldwide_gross_cr",
        "verdict",
        "day_count",
        "daily_breakdown",
        "primary_source",
        "source_urls",
        "variance_flag",
        "manual_override",
        "last_scraped_at",
    }
    assert set(contract.keys()) == expected_keys


def test_aggregator_no_variance_flag_within_25_percent() -> None:
    a = RawScrapedMovie(
        source="sacnilk",
        source_url="https://sacnilk.com/1",
        title="Scene",
        language="Tamil",
        india_net_cr=100.0,
    )
    b = RawScrapedMovie(
        source="koimoi",
        source_url="https://koimoi.com/1",
        title="Scene",
        language="Tamil",
        india_net_cr=120.0,  # 20 / 120 = 16.67% <= 25%
    )
    agg = TrackerAggregator(variance_threshold=0.25)
    reconciled, _ = agg.reconcile([a, b])
    assert len(reconciled) == 1
    assert reconciled[0].variance_flag is False


# =============================================================================
# 5. TMDB Client Caching & Fuzzy Disambiguation Tests
# =============================================================================


def test_tmdb_client_matches_and_uses_json_cache(tmp_path: Path) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path.endswith("/search/movie"):
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "id": 9991,
                            "title": "Ramayana",
                            "original_title": "Ramayana",
                            "release_date": "1992-05-01",
                            "original_language": "en",
                            "popularity": 12.0,
                        },
                        {
                            "id": 8882026,
                            "title": "Ramayana",
                            "original_title": "Ramayana",
                            "release_date": "2026-11-05",
                            "original_language": "hi",
                            "poster_path": "/ramayana_poster.jpg",
                            "backdrop_path": "/ramayana_bg.jpg",
                            "popularity": 85.0,
                        },
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                "id": 8882026,
                "title": "Ramayana",
                "original_language": "hi",
                "release_date": "2026-11-05",
                "poster_path": "/ramayana_poster.jpg",
                "backdrop_path": "/ramayana_bg.jpg",
                "credits": {"cast": [{"name": "Ranbir Kapoor"}, {"name": "Sai Pallavi"}]},
                "videos": {
                    "results": [
                        {"site": "YouTube", "type": "Teaser", "official": True, "key": "teaser99999"},
                        {"site": "YouTube", "type": "Trailer", "official": False, "key": "unofficial1"},
                        {"site": "YouTube", "type": "Trailer", "official": True, "key": "1zip1rNaNYs"},
                    ]
                },
            },
        )

    transport = httpx.MockTransport(handler)
    cache_file = tmp_path / "tmdb_cache.json"
    http_client = httpx.Client(base_url="https://api.themoviedb.org/3", transport=transport)

    with TMDBClient(api_key="test-tmdb-key", cache_path=cache_file, http_client=http_client) as client:
        meta1, hit1, api1 = client.lookup("Ramayana", release_year=2026, language="Hindi")
        assert meta1 is not None
        assert meta1.tmdb_id == 8882026
        assert meta1.poster_url == "https://image.tmdb.org/t/p/w500/ramayana_poster.jpg"
        assert meta1.trailer_youtube_id == "1zip1rNaNYs"
        assert "Ranbir Kapoor" in (meta1.cast_summary or "")
        assert hit1 is False
        assert api1 is True
        assert cache_file.exists()

        # Second call must hit cache without calling HTTP transport again
        calls_before = len(calls)
        meta2, hit2, api2 = client.lookup("Ramayana", release_year=2026, language="Hindi")
        assert meta2 is not None
        assert meta2.tmdb_id == 8882026
        assert hit2 is True
        assert api2 is False
        assert len(calls) == calls_before


def test_multi_tier_poster_resolution_sacnilk_and_wikipedia_fallback(tmp_path: Path) -> None:
    assert UtilsTMDBClient is TMDBClient
    variants = build_fuzzy_title_variants("Dhurandhar (2026) (Hindi) Day 5")
    assert variants[0] == "Dhurandhar"

    wiki_calls: list[str] = []

    def wiki_handler(request: httpx.Request) -> httpx.Response:
        wiki_calls.append(str(request.url))
        return httpx.Response(
            200,
            json={
                "query": {
                    "pages": {
                        "11": {
                            "pageid": 11,
                            "title": "Dhurandhar (soundtrack)",
                            "thumbnail": {"source": "https://upload.wikimedia.org/wikipedia/en/bad.jpg"},
                        },
                        "12": {
                            "pageid": 12,
                            "title": "Dhurandhar (2026 film)",
                            "thumbnail": {
                                "source": "https://upload.wikimedia.org/wikipedia/en/c/ce/Dhurandhar_poster.jpg"
                            },
                        },
                    }
                }
            },
        )

    wiki_client = httpx.Client(transport=httpx.MockTransport(wiki_handler))
    yt_calls: list[str] = []

    def yt_handler(request: httpx.Request) -> httpx.Response:
        yt_calls.append(str(request.url))
        html = (
            '{"videoRenderer":{"videoId":"badreact123","title":{"runs":[{"text":"Hail Mary Trailer Reaction & Review"}]}}}'
            '{"videoRenderer":{"videoId":"MeYJ38OCXjs","title":{"runs":[{"text":"Hail Mary Official Trailer | Malayalam 2026"}]}}}'
        )
        return httpx.Response(200, text=html)

    yt_client = httpx.Client(transport=httpx.MockTransport(yt_handler))
    cache_file = tmp_path / "multi_tier_cache.json"

    rec_sacnilk = MovieBoxOfficeRecord(
        movie_slug="hail-mary",
        title="Hail Mary",
        language="Malayalam",
        release_date="2026-11-26",
        poster_url="https://cdn.sacnilk.com/image/movie/2026/14655.jpg",
        india_net_cr=2.63,
        primary_source="sacnilk",
    )
    rec_wiki = MovieBoxOfficeRecord(
        movie_slug="dhurandhar",
        title="Dhurandhar (Hindi)",
        language="Hindi",
        release_date="2026-08-15",
        poster_url=None,
        india_net_cr=450.0,
        primary_source="koimoi",
    )

    with TMDBClient(
        api_key="",
        cache_path=cache_file,
        wiki_http_client=wiki_client,
        youtube_http_client=yt_client,
    ) as client:
        _, stats = client.enrich_records([rec_sacnilk, rec_wiki])
        assert rec_sacnilk.poster_url == "https://cdn.sacnilk.com/image/movie/2026/14655.jpg"
        assert rec_sacnilk.backdrop_url == "https://cdn.sacnilk.com/image/movie/2026/14655.jpg"
        assert rec_sacnilk.trailer_youtube_id == "MeYJ38OCXjs"
        assert rec_wiki.poster_url == "https://upload.wikimedia.org/wikipedia/en/c/ce/Dhurandhar_poster.jpg"
        assert rec_wiki.backdrop_url == "https://upload.wikimedia.org/wikipedia/en/c/ce/Dhurandhar_poster.jpg"
        assert stats["sacnilk_poster_used"] == 1
        assert stats["wikipedia_matched"] == 1
        assert stats["trailers_youtube"] >= 1

        # Second call uses Wikipedia and YouTube JSON caches
        calls_before = len(wiki_calls)
        yt_before = len(yt_calls)
        rec_wiki_again = MovieBoxOfficeRecord(
            movie_slug="dhurandhar",
            title="Dhurandhar (Hindi)",
            language="Hindi",
            release_date="2026-08-15",
            primary_source="koimoi",
        )
        _, stats2 = client.enrich_records([rec_wiki_again])
        assert rec_wiki_again.poster_url == "https://upload.wikimedia.org/wikipedia/en/c/ce/Dhurandhar_poster.jpg"
        assert stats2["wikipedia_cache_hits"] == 1
        assert len(wiki_calls) == calls_before
        assert len(yt_calls) == yt_before


# =============================================================================
# 6. Supabase Sync Manual Override Lock & Settings Validation Tests
# =============================================================================


class _FakeQuery:
    def __init__(self, db_store: dict[str, list[dict[str, Any]]], table_name: str) -> None:
        self.db_store = db_store
        self.table_name = table_name
        self._op: str | None = None
        self._payload: list[dict[str, Any]] = []
        self._filter_col: str | None = None
        self._filter_vals: set[str] = set()

    def select(self, _cols: str) -> "_FakeQuery":
        self._op = "select"
        return self

    def in_(self, col: str, vals: list[str]) -> "_FakeQuery":
        self._filter_col = col
        self._filter_vals = set(vals)
        return self

    def upsert(self, payload: list[dict[str, Any]], on_conflict: str = "") -> "_FakeQuery":
        self._op = "upsert"
        self._payload = payload
        return self

    def execute(self) -> Any:
        class _Resp:
            def __init__(self, data: list[dict[str, Any]]) -> None:
                self.data = data

        rows = self.db_store.setdefault(self.table_name, [])
        if self._op == "select":
            matched = [
                r for r in rows if not self._filter_col or r.get(self._filter_col) in self._filter_vals
            ]
            return _Resp(matched)

        if self._op == "upsert":
            key_field = "movie_slug" if self.table_name == "movies" else None
            out: list[dict[str, Any]] = []
            for item in self._payload:
                if key_field:
                    existing = next((r for r in rows if r.get(key_field) == item.get(key_field)), None)
                    if existing:
                        existing.update(item)
                        out.append(existing)
                    else:
                        new_row = {"id": f"uuid-{len(rows) + 1}", **item}
                        rows.append(new_row)
                        out.append(new_row)
                else:
                    existing = next(
                        (
                            r
                            for r in rows
                            if r.get("movie_id") == item.get("movie_id")
                            and r.get("day_number") == item.get("day_number")
                        ),
                        None,
                    )
                    if existing:
                        existing.update(item)
                        out.append(existing)
                    else:
                        rows.append(dict(item))
                        out.append(item)
            return _Resp(out)
        return _Resp([])


class _FakeSupabaseClient:
    def __init__(self, initial_movies: list[dict[str, Any]]) -> None:
        self.store: dict[str, list[dict[str, Any]]] = {
            "movies": initial_movies,
            "daily_collections": [],
        }

    def table(self, name: str) -> _FakeQuery:
        return _FakeQuery(self.store, name)


def test_supabase_sync_respects_manual_override_lock() -> None:
    locked_existing = {
        "id": "uuid-locked-1",
        "movie_slug": "locked-hit",
        "title": "Locked Hit",
        "india_net_cr": 999.99,
        "india_gross_cr": 1150.0,
        "overseas_cr": 200.0,
        "worldwide_gross_cr": 1350.0,
        "budget_cr": 100.0,
        "day_count": 10,
        "daily_breakdown": [{"day": 1, "date": "2026-01-01", "india_net_cr": 50.0, "change_pct": None}],
        "verdict": "All Time Blockbuster",
        "manual_override": True,
        "variance_flag": False,
        "tmdb_id": None,
        "poster_url": None,
    }
    fake_client = _FakeSupabaseClient([locked_existing])
    sync = SupabaseSync(client=fake_client)

    incoming_locked = MovieBoxOfficeRecord(
        movie_slug="locked-hit",
        title="Locked Hit Updated Title",
        language="Malayalam",
        tmdb_id=12345,
        poster_url="https://image.tmdb.org/t/p/w780/new.jpg",
        india_net_cr=10.0,  # Should NOT overwrite 999.99
        worldwide_gross_cr=12.0,  # Should NOT overwrite 1350.0
        verdict="Flop",  # Should NOT overwrite All Time Blockbuster
        day_count=1,
        daily_breakdown=[DailyCollectionEntry(day=1, date="2026-01-01", india_net_cr=10.0, change_pct=None)],
        primary_source="sacnilk",
        source_urls=["https://www.sacnilk.com/movie/locked"],
    )
    incoming_normal = MovieBoxOfficeRecord(
        movie_slug="fresh-movie",
        title="Fresh Movie",
        language="Tamil",
        india_net_cr=45.0,
        worldwide_gross_cr=70.0,
        verdict="Hit",
        day_count=1,
        daily_breakdown=[DailyCollectionEntry(day=1, date="2026-02-01", india_net_cr=45.0, change_pct=None)],
        primary_source="sacnilk",
        source_urls=["https://www.sacnilk.com/movie/fresh"],
    )

    stats = sync.sync_records([incoming_locked, incoming_normal])
    assert stats.upserted == 2
    assert stats.manual_override_locked == 1
    assert stats.daily_rows_synced == 1  # Only fresh-movie's daily row synced

    stored_locked = next(r for r in fake_client.store["movies"] if r["movie_slug"] == "locked-hit")
    assert stored_locked["india_net_cr"] == 999.99
    assert stored_locked["worldwide_gross_cr"] == 1350.0
    assert stored_locked["verdict"] == "All Time Blockbuster"
    assert stored_locked["manual_override"] is True
    assert stored_locked["primary_source"] == "cinetracker_bo"
    # Non-financial metadata MUST still update!
    assert stored_locked["tmdb_id"] == 12345
    assert stored_locked["poster_url"] == "https://image.tmdb.org/t/p/w780/new.jpg"
    assert stored_locked["title"] == "Locked Hit Updated Title"

    stored_normal = next(r for r in fake_client.store["movies"] if r["movie_slug"] == "fresh-movie")
    assert stored_normal["primary_source"] == "cinetracker_bo"


def test_settings_validation_rejects_missing_credentials() -> None:
    bad = Settings(supabase_url=None, supabase_key=None)
    with pytest.raises(ConfigurationError):
        bad.validate_environment(require_supabase=True)

    placeholder = Settings(
        supabase_url="https://your-project-id.supabase.co",
        supabase_key="your-supabase-service-role-or-anon-key",
    )
    with pytest.raises(ConfigurationError):
        placeholder.validate_environment(require_supabase=True)


def test_base_scraper_falls_back_to_playwright_on_403_or_cloudflare(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = SacnilkScraper(
        settings=Settings(
            min_delay_sec=0.0,
            max_delay_sec=0.0,
            retry_max_attempts=1,
            retry_base_delay_sec=0.2,
        )
    )

    class _ChallengeResp:
        status_code = 403
        text = "<html><title>Just a moment...</title>cf-browser-verification</html>"

    class _FakeSession:
        def get(self, *args: Any, **kwargs: Any) -> _ChallengeResp:
            return _ChallengeResp()

        def close(self) -> None:
            return None

    playwright_called: list[str] = []

    def fake_playwright(url: str) -> str:
        playwright_called.append(url)
        return "<html><body>Bypassed OK</body></html>"

    monkeypatch.setattr(scraper, "_get_session", lambda: _FakeSession())
    monkeypatch.setattr(scraper, "_fetch_with_playwright", fake_playwright)

    html = scraper.fetch_html("https://www.sacnilk.com/test-protected")
    assert "Bypassed OK" in html
    assert playwright_called == ["https://www.sacnilk.com/test-protected"]

