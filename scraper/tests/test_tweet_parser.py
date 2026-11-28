"""Unit tests for X (Twitter) tweet NLP parser, 2-tier scraper payloads, and aggregator integration."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from config.settings import Settings
from scrapers.tracker_aggregator import TrackerAggregator
from scrapers.x_tracker_scraper import XTrackerScraper
from utils.models import RawScrapedMovie
from utils.tweet_parser import TweetParser


def _recent_twitter_ts(hours_ago: int = 2) -> str:
    dt = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    return dt.strftime("%a %b %d %H:%M:%S +0000 %Y")


def _stale_twitter_ts(hours_ago: int = 72) -> str:
    dt = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    return dt.strftime("%a %b %d %H:%M:%S +0000 %Y")


# =============================================================================
# 1. 12 Realistic Malayalam, Tamil, Hindi & Trap Tweet Format Tests
# =============================================================================


def test_malayalam_kerala_and_worldwide_tweet() -> None:
    parser = TweetParser(known_titles=["Aadu 3", "Bethlehem Kudumba Unit"])
    text = "#Aadu3 Day 2 Kerala Gross ₹4.15 Cr! Total 2 Days WW Gross crosses ₹14.80 Cr 🔥"
    res = parser.parse_tweet(text, default_language="Malayalam")
    assert len(res) == 1
    r = res[0]
    assert r.title == "Aadu 3"
    assert r.language == "Malayalam"
    assert r.day_number == 2
    assert r.kerala_gross_cr == pytest.approx(4.15)
    assert r.worldwide_gross_cr == pytest.approx(14.80)


def test_malayalam_opening_day_lakhs_tweet() -> None:
    parser = TweetParser()
    text = "#MollywoodTimes Opening Day Kerala Gross ₹85.5 Lakhs. Positive reports all over! #Mollywood"
    res = parser.parse_tweet(text, default_language="Malayalam")
    assert len(res) == 1
    assert res[0].title == "Mollywood Times"
    assert res[0].day_number == 1
    assert res[0].kerala_gross_cr == pytest.approx(0.855)


def test_malayalam_blockbuster_all_metrics_tweet() -> None:
    parser = TweetParser(known_titles=["Bethlehem Kudumba Unit"])
    text = (
        "#BethlehemKudumbaUnit 62 Days Worldwide Gross: ₹331.10 Cr! "
        "India Nett: ₹165.07 Cr | Overseas: ₹138.45 Cr. ALL TIME BLOCKBUSTER!"
    )
    res = parser.parse_tweet(text, default_language="Malayalam")
    assert len(res) == 1
    r = res[0]
    assert r.title == "Bethlehem Kudumba Unit"
    assert r.day_number == 62
    assert r.worldwide_gross_cr == pytest.approx(331.10)
    assert r.india_net_cr == pytest.approx(165.07)
    assert r.overseas_cr == pytest.approx(138.45)
    assert r.verdict == "All Time Blockbuster"


def test_hindi_taran_adarsh_weekday_breakdown_tweet() -> None:
    parser = TweetParser(known_titles=["Dhurandhar 2: The Revenge"])
    text = (
        "#Dhurandhar2 storms the BO... Fri 102.55 cr, Sat 80.72 cr, Sun 113.00 cr. "
        "Total: ₹ 296.27 cr. #India biz. #Hindi"
    )
    res = parser.parse_tweet(
        text,
        default_language="Hindi",
        tweeted_at="2026-03-22T10:00:00+00:00",
    )
    assert len(res) == 1
    r = res[0]
    assert r.title == "Dhurandhar 2: The Revenge"
    assert r.language == "Hindi"
    assert r.india_net_cr == pytest.approx(296.27)
    assert len(r.daily_breakdown) == 3
    assert r.daily_breakdown[0].day == 1
    assert r.daily_breakdown[0].india_net_cr == pytest.approx(102.55)
    assert r.daily_breakdown[2].india_net_cr == pytest.approx(113.00)


def test_hindi_opening_weekend_and_worldwide_tweet() -> None:
    parser = TweetParser(known_titles=["Ramayana"])
    text = "#Ramayana Opening Weekend India Nett ₹238.85 Cr | Worldwide Gross ₹415.00 Cr. Huge! #Bollywood"
    res = parser.parse_tweet(text, default_language="Hindi")
    assert len(res) == 1
    r = res[0]
    assert r.title == "Ramayana"
    assert r.day_number == 3
    assert r.india_net_cr == pytest.approx(238.85)
    assert r.worldwide_gross_cr == pytest.approx(415.00)


def test_tamil_manobala_worldwide_and_india_net_tweet() -> None:
    parser = TweetParser(known_titles=["Jailer 2"])
    text = "#Jailer2 WW Box Office Day 15: India Net ₹420.50 Cr | Worldwide Gross ₹745.20 Cr. Super Hit! #Kollywood"
    res = parser.parse_tweet(text, default_language="Tamil")
    assert len(res) == 1
    r = res[0]
    assert r.title == "Jailer 2"
    assert r.language == "Tamil"
    assert r.day_number == 15
    assert r.india_net_cr == pytest.approx(420.50)
    assert r.worldwide_gross_cr == pytest.approx(745.20)
    assert r.verdict == "Super Hit"


def test_tamil_day_1_without_hashtag_tweet() -> None:
    parser = TweetParser()
    text = "Scene Day 1 Tamil Nadu Gross ₹14.20 Cr | WW Gross ₹29.40 Cr! Solid start. #Tamil"
    res = parser.parse_tweet(text, default_language="Tamil")
    assert len(res) == 1
    r = res[0]
    assert r.title == "Scene"
    assert r.day_number == 1
    assert r.worldwide_gross_cr == pytest.approx(29.40)


def test_bms_ticket_booking_trap_ignored() -> None:
    parser = TweetParser(known_titles=["Pushpa 2"])
    # Pure BMS ticket count trap must return []
    pure_bms = "#Pushpa2 storms BookMyShow! 150K tickets sold on BMS in last 24 hours! #BoxOffice"
    assert parser.parse_tweet(pure_bms, default_language="Pan-India") == []

    # Mixed BMS + real collection must strip 85K tickets and parse only ₹18.40 Cr
    mixed_bms = (
        "#Pushpa2 85K tickets sold on BMS today! Day 1 India Nett ₹72.00 Cr. #BoxOffice"
    )
    res = parser.parse_tweet(mixed_bms, default_language="Hindi")
    assert len(res) == 1
    assert res[0].india_net_cr == pytest.approx(72.00)


def test_trailer_views_and_fan_war_retweet_ignored() -> None:
    parser = TweetParser()
    views_tweet = "#Aadu3 Teaser smashes 10M views and 500K likes in 18 hours! Trending #1! 1 Crore views soon!"
    assert parser.parse_tweet(views_tweet, default_language="Malayalam") == []

    rt_tweet = "RT @FanClub: #Aadu3 Day 1 Kerala Gross ₹12.00 Cr! Mega Blockbuster!"
    assert parser.parse_tweet(rt_tweet, default_language="Malayalam") == []
    assert parser.parse_tweet("#Aadu3 Day 1 ₹5 Cr", is_retweet=True) == []


def test_multi_movie_summary_tweet_splits_cleanly() -> None:
    parser = TweetParser(known_titles=["Aadu 3", "Bethlehem Kudumba Unit", "Drishyam 3"])
    text = (
        "Kerala Box Office Top 3 - Nov 28:\n"
        "1. #Aadu3 - ₹2.45 Cr\n"
        "2. #BethlehemKudumbaUnit - ₹1.80 Cr\n"
        "3. #Drishyam3 - ₹95 Lakhs"
    )
    res = parser.parse_tweet(text, default_language="Malayalam")
    assert len(res) == 3
    assert [r.title for r in res] == ["Aadu 3", "Bethlehem Kudumba Unit", "Drishyam 3"]
    assert res[0].kerala_gross_cr == pytest.approx(2.45)
    assert res[1].kerala_gross_cr == pytest.approx(1.80)
    assert res[2].kerala_gross_cr == pytest.approx(0.95)


def test_pipe_separated_multi_movie_tweet() -> None:
    parser = TweetParser()
    text = "#Peddi Day 1 India Nett ₹34.50 Cr | #Mirzapur Day 1 India Nett ₹21.10 Cr #BoxOffice"
    res = parser.parse_tweet(text, default_language="Pan-India")
    assert len(res) == 2
    assert res[0].title == "Peddi"
    assert res[0].india_net_cr == pytest.approx(34.50)
    assert res[1].title == "Mirzapur"
    assert res[1].india_net_cr == pytest.approx(21.10)


def test_single_day_gt1_without_total_prevents_lifetime_overwrite() -> None:
    scraper = XTrackerScraper(
        settings=Settings(min_delay_sec=0.0, max_delay_sec=0.0),
        known_titles=["Ramayana"],
    )
    parsed = scraper.tweet_parser.parse_tweet(
        "#Ramayana Day 23 India Nett ₹8.45 Cr! #Bollywood",
        default_language="Hindi",
        tweet_id="123456",
        tweet_url="https://x.com/taran_adarsh/status/123456",
        handle="taran_adarsh",
        tweeted_at=datetime.now(timezone.utc).isoformat(),
    )
    assert len(parsed) == 1
    assert parsed[0].is_single_day_only is True
    raw_movie = scraper.normalize({"parsed": parsed[0]})
    # Lifetime india_net_cr stays 0.0 so single-day update merges into Day 23 without causing false variance!
    assert raw_movie.india_net_cr == 0.0
    assert len(raw_movie.daily_breakdown) == 1
    assert raw_movie.daily_breakdown[0].day == 23
    assert raw_movie.daily_breakdown[0].india_net_cr == pytest.approx(8.45)


# =============================================================================
# 2. XTrackerScraper 2-Tier Fetch, Recency Filter & Aggregator Tests
# =============================================================================


def test_x_scraper_parses_syndication_rss_and_graphql_with_48h_filter() -> None:
    scraper = XTrackerScraper(
        settings=Settings(min_delay_sec=0.0, max_delay_sec=0.0),
        known_titles=["Aadu 3", "Jailer 2"],
    )

    recent_ts = _recent_twitter_ts(3)
    stale_ts = _stale_twitter_ts(96)

    synd_html = f"""
    <html><body>
      <script id="__NEXT_DATA__" type="application/json">
        {json.dumps({
            "props": {
                "pageProps": {
                    "timeline": {
                        "entries": [
                            {
                                "content": {
                                    "tweet": {
                                        "id_str": "111",
                                        "full_text": "#Aadu3 Day 1 Kerala Gross ₹5.10 Cr! WW Gross ₹11.20 Cr!",
                                        "created_at": recent_ts,
                                        "user": {"screen_name": "Forumkeralam1"}
                                    }
                                }
                            },
                            {
                                "content": {
                                    "tweet": {
                                        "id_str": "222",
                                        "full_text": "#Aadu3 Old update India Net ₹1.00 Cr",
                                        "created_at": stale_ts,
                                        "user": {"screen_name": "Forumkeralam1"}
                                    }
                                }
                            }
                        ]
                    }
                }
            }
        })}
      </script>
    </body></html>
    """

    listings = scraper.parse_listings(
        synd_html,
        language="Malayalam",
        base_url="https://syndication.twitter.com/srv/timeline-profile/screen-name/Forumkeralam1",
    )
    assert len(listings) == 1
    assert listings[0]["tweet_id"] == "111"

    graphql_payload = {
        "data": {
            "user": {
                "result": {
                    "timeline_v2": {
                        "timeline": {
                            "instructions": [
                                {
                                    "entries": [
                                        {
                                            "content": {
                                                "itemContent": {
                                                    "tweet_results": {
                                                        "result": {
                                                            "rest_id": "999001",
                                                            "core": {
                                                                "user_results": {
                                                                    "result": {
                                                                        "legacy": {"screen_name": "ManobalaV"}
                                                                    }
                                                                }
                                                            },
                                                            "legacy": {
                                                                "full_text": "#Jailer2 Day 1 India Net ₹62.00 Cr! WW Gross ₹105.00 Cr",
                                                                "created_at": recent_ts,
                                                            },
                                                        }
                                                    }
                                                }
                                            }
                                        }
                                    ]
                                }
                            ]
                        }
                    }
                }
            }
        }
    }
    gq_tweets = scraper.parse_user_tweets_graphql(graphql_payload, handle="ManobalaV")
    assert len(gq_tweets) == 1
    assert gq_tweets[0]["tweet_id"] == "999001"
    assert gq_tweets[0]["handle"] == "ManobalaV"


def test_x_scraper_tier1_falls_back_to_tier2_and_integrates_with_aggregator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = XTrackerScraper(
        settings=Settings(min_delay_sec=0.0, max_delay_sec=0.0, x_nitter_instances_raw=""),
        known_titles=["Aadu 3"],
    )
    recent_ts = _recent_twitter_ts(1)

    # Simulate Tier-1 HTTP 429 rate limit
    monkeypatch.setattr(scraper, "_safe_curl_get", lambda _url: (429, "Rate limit exceeded"))

    tier2_calls: list[str] = []

    def fake_tier2(handle: str) -> list[dict[str, Any]]:
        tier2_calls.append(handle)
        if handle == "Forumkeralam1":
            return [
                {
                    "tweet_id": "777",
                    "handle": "Forumkeralam1",
                    "text": "#Aadu3 Day 1 India Nett ₹14.00 Cr | WW Gross ₹22.50 Cr",
                    "created_at": recent_ts,
                    "is_retweet": False,
                    "tweet_url": "https://x.com/Forumkeralam1/status/777",
                }
            ]
        return []

    monkeypatch.setattr(scraper, "_fetch_tier2_playwright_graphql", fake_tier2)
    x_records, metrics, errors = scraper.scrape(language="Malayalam")
    assert errors == []
    assert len(tier2_calls) >= 1
    assert len(x_records) == 1
    assert x_records[0].source == "x"
    assert x_records[0].india_net_cr == pytest.approx(14.00)

    # Reconcile X breaking estimate against Sacnilk (priority 1.0 > 0.65) with >25% divergence
    sacnilk_rec = RawScrapedMovie(
        source="sacnilk",
        source_url="https://www.sacnilk.com/movie/Aadu_3_2026",
        title="Aadu 3",
        language="Malayalam",
        india_net_cr=9.00,  # 35.7% variance vs X's 14.00 -> triggers variance_flag!
        worldwide_gross_cr=18.00,
    )
    agg = TrackerAggregator(source_weights={"sacnilk": 1.0, "koimoi": 0.75, "x": 0.65})
    reconciled, summary = agg.reconcile([*x_records, sacnilk_rec])
    assert len(reconciled) == 1
    assert reconciled[0].primary_source == "sacnilk"
    assert reconciled[0].india_net_cr == pytest.approx(9.00)
    assert reconciled[0].variance_flag is True
    assert summary["multi_source_matches"] == 1
    assert summary["variance_anomalies"] == 1
