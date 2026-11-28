"""Fault-tolerant X (Twitter) Box Office Tracker scraper with 2-tier fetching."""

from __future__ import annotations

import json
import random
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any

from bs4 import BeautifulSoup
from playwright.sync_api import Response as PlaywrightResponse
from playwright.sync_api import sync_playwright

from config.settings import Settings, SourceConfig, XTrackersConfig, load_sources_config
from scrapers.base_scraper import BaseScraper
from utils.logger import get_logger
from utils.models import RawScrapedMovie
from utils.tweet_parser import ParsedTweetRecord, TweetParser

logger = get_logger("scrapers.x_tracker")

_TWITTER_DATE_FMT = "%a %b %d %H:%M:%S %z %Y"


class XTrackerScraper(BaseScraper):
    """2-tier X (Twitter) box office tracker scraper inheriting BaseScraper."""

    source_name = "x"

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        source_config: SourceConfig | None = None,
        x_config: XTrackersConfig | None = None,
        known_titles: list[str] | None = None,
    ) -> None:
        sources_cfg = load_sources_config(settings.sources_config_path) if settings else load_sources_config()
        self.x_config = x_config or sources_cfg.x_trackers
        effective_source_cfg = source_config or SourceConfig(
            enabled=self.x_config.enabled,
            base_url="https://x.com",
            priority_weight=self.x_config.priority_weight,
            categories={
                handle_cfg.language: [f"https://x.com/{handle}"]
                for handle, handle_cfg in self.x_config.handles.items()
            },
            selectors={},
        )
        super().__init__(settings=settings, source_config=effective_source_cfg)

        discovered_titles = list(known_titles) if known_titles is not None else self._load_known_titles()
        self.tweet_parser = TweetParser(
            known_titles=discovered_titles,
            keywords=self.x_config.keywords or None,
            match_threshold=self.settings.title_match_threshold,
        )

    def _load_known_titles(self) -> list[str]:
        """Load active movie titles from TMDB local cache and Supabase movies table (best-effort)."""
        titles: list[str] = []
        seen: set[str] = set()

        def _add(title: str | None) -> None:
            if not title:
                return
            t = title.strip()
            if t and t.lower() not in seen:
                seen.add(t.lower())
                titles.append(t)

        # 1. Local TMDB JSON cache
        cache_path = self.settings.tmdb_cache_path
        if cache_path.exists():
            try:
                raw_cache = json.loads(cache_path.read_text(encoding="utf-8"))
                if isinstance(raw_cache, dict):
                    for entry in raw_cache.values():
                        if isinstance(entry, dict):
                            _add(entry.get("matched_title"))
            except Exception as exc:
                logger.debug("[x] Failed reading TMDB cache titles: %s", exc)

        # 2. Active Supabase movies table (non-blocking if credentials absent or offline)
        if not self.settings._is_placeholder(self.settings.supabase_url) and not self.settings._is_placeholder(
            self.settings.supabase_key
        ):
            try:
                from supabase import create_client

                client = create_client(self.settings.supabase_url or "", self.settings.supabase_key or "")
                resp = client.table("movies").select("title").limit(500).execute()
                for row in getattr(resp, "data", None) or []:
                    if isinstance(row, dict):
                        _add(row.get("title"))
            except Exception as exc:
                logger.debug("[x] Optional Supabase active titles preload skipped: %s", exc)

        return titles

    @staticmethod
    def parse_tweet_timestamp(raw_ts: str | None) -> datetime | None:
        """Parse Twitter RFC-2822, RSS pubDate, or ISO-8601 timestamp into UTC datetime."""
        if not raw_ts:
            return None
        val = str(raw_ts).strip()
        if not val:
            return None
        try:
            dt = datetime.strptime(val, _TWITTER_DATE_FMT)
            return dt.astimezone(timezone.utc)
        except ValueError:
            pass
        try:
            dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except ValueError:
            pass
        try:
            dt = parsedate_to_datetime(val)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception:
            return None

    def _is_within_recency_window(self, raw_ts: str | None) -> bool:
        dt = self.parse_tweet_timestamp(raw_ts)
        if dt is None:
            return False
        cutoff = datetime.now(timezone.utc) - timedelta(hours=self.x_config.max_age_hours)
        return dt >= cutoff

    # ------------------------------------------------------------------
    # Tier 1: X Syndication JSON/HTML & Public Mirror RSS/HTML Parsers
    # ------------------------------------------------------------------
    @staticmethod
    def parse_syndication_payload(payload: str, *, handle: str) -> list[dict[str, Any]]:
        """Parse response from syndication.twitter.com timeline endpoint."""
        tweets: list[dict[str, Any]] = []
        stripped = payload.strip()
        if not stripped:
            return tweets

        # Handle direct JSON if returned
        if stripped.startswith("{"):
            try:
                data = json.loads(stripped)
                entries = (
                    data.get("props", {})
                    .get("pageProps", {})
                    .get("timeline", {})
                    .get("entries", [])
                )
                return XTrackerScraper._extract_from_syndication_entries(entries, handle=handle)
            except Exception:
                return []

        soup = BeautifulSoup(stripped, "lxml")
        next_data_el = soup.find("script", id="__NEXT_DATA__")
        if next_data_el and next_data_el.string:
            try:
                data = json.loads(next_data_el.string)
                entries = (
                    data.get("props", {})
                    .get("pageProps", {})
                    .get("timeline", {})
                    .get("entries", [])
                )
                tweets = XTrackerScraper._extract_from_syndication_entries(entries, handle=handle)
                if tweets:
                    return tweets
            except Exception as exc:
                logger.debug("[x] Failed parsing __NEXT_DATA__ for @%s: %s", handle, exc)

        # Classic syndication HTML timeline fallback
        for item in soup.select(".timeline-Tweet, [data-tweet-id]"):
            tweet_id = item.get("data-tweet-id")
            text_el = item.select_one(".timeline-Tweet-text, p")
            time_el = item.select_one("time[datetime], a.timeline-Tweet-timestamp")
            text = text_el.get_text(" ", strip=True) if text_el else ""
            if not text:
                continue
            created_at = (
                time_el.get("datetime") or time_el.get("title") or time_el.get_text(strip=True)
                if time_el
                else None
            )
            is_rt = bool(item.select_one(".timeline-Tweet-retweetCredit"))
            media_urls = [
                img.get("src")
                for img in item.select("img.NaturalImage-image, .timeline-Tweet-media img")
                if img.get("src")
            ]
            tweets.append(
                {
                    "tweet_id": tweet_id,
                    "handle": handle,
                    "text": text,
                    "created_at": created_at,
                    "is_retweet": is_rt,
                    "tweet_url": f"https://x.com/{handle}/status/{tweet_id}"
                    if tweet_id
                    else f"https://x.com/{handle}",
                    "media_urls": media_urls,
                }
            )
        return tweets

    @staticmethod
    def _extract_from_syndication_entries(
        entries: list[dict[str, Any]], *, handle: str
    ) -> list[dict[str, Any]]:
        tweets: list[dict[str, Any]] = []
        for entry in entries:
            tweet = entry.get("content", {}).get("tweet")
            if not isinstance(tweet, dict):
                continue
            tweet_id = str(tweet.get("id_str") or tweet.get("conversation_id_str") or "").strip() or None
            text = str(tweet.get("full_text") or tweet.get("text") or "").strip()
            if not text:
                continue
            is_rt = bool(tweet.get("retweeted_status") or text.startswith("RT @"))
            media_items = (tweet.get("extended_entities") or tweet.get("entities") or {}).get("media") or []
            media_urls = [
                str(m.get("media_url_https") or m.get("media_url"))
                for m in media_items
                if m.get("media_url_https") or m.get("media_url")
            ]
            screen_name = (tweet.get("user") or {}).get("screen_name") or handle
            tweets.append(
                {
                    "tweet_id": tweet_id,
                    "handle": screen_name,
                    "text": text,
                    "created_at": tweet.get("created_at"),
                    "is_retweet": is_rt,
                    "tweet_url": f"https://x.com/{screen_name}/status/{tweet_id}"
                    if tweet_id
                    else f"https://x.com/{screen_name}",
                    "media_urls": media_urls,
                }
            )
        return tweets

    @staticmethod
    def parse_nitter_rss(xml_text: str, *, handle: str) -> list[dict[str, Any]]:
        """Parse public Nitter/XCancel RSS XML into tweet dicts."""
        tweets: list[dict[str, Any]] = []
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            return tweets

        for item in root.findall("./channel/item"):
            title_txt = (item.findtext("title") or "").strip()
            desc_raw = item.findtext("description") or ""
            desc_txt = BeautifulSoup(desc_raw, "lxml").get_text(" ", strip=True) if desc_raw else ""
            text = desc_txt or title_txt
            if not text:
                continue
            link = (item.findtext("link") or "").strip()
            pub_date = (item.findtext("pubDate") or "").strip()
            is_rt = title_txt.startswith("RT by ") or text.startswith("RT @")
            m_id = re.search(r"/status/(\d+)", link)
            tweet_id = m_id.group(1) if m_id else None
            tweets.append(
                {
                    "tweet_id": tweet_id,
                    "handle": handle,
                    "text": text,
                    "created_at": pub_date,
                    "is_retweet": is_rt,
                    "tweet_url": f"https://x.com/{handle}/status/{tweet_id}"
                    if tweet_id
                    else (link or f"https://x.com/{handle}"),
                    "media_urls": [],
                }
            )
        return tweets

    @staticmethod
    def parse_nitter_html(html: str, *, handle: str) -> list[dict[str, Any]]:
        """Parse Nitter/XCancel HTML timeline page into tweet dicts."""
        soup = BeautifulSoup(html, "lxml")
        tweets: list[dict[str, Any]] = []
        for item in soup.select(".timeline-item"):
            is_rt = bool(item.select_one(".retweet-header"))
            content_el = item.select_one(".tweet-content")
            date_el = item.select_one(".tweet-date a")
            text = content_el.get_text(" ", strip=True) if content_el else ""
            if not text:
                continue
            href = date_el.get("href", "") if date_el else ""
            m_id = re.search(r"/status/(\d+)", href)
            tweet_id = m_id.group(1) if m_id else None
            created_at = date_el.get("title") or date_el.get_text(strip=True) if date_el else None
            tweets.append(
                {
                    "tweet_id": tweet_id,
                    "handle": handle,
                    "text": text,
                    "created_at": created_at,
                    "is_retweet": is_rt,
                    "tweet_url": f"https://x.com/{handle}/status/{tweet_id}"
                    if tweet_id
                    else f"https://x.com/{handle}",
                    "media_urls": [],
                }
            )
        return tweets

    def _safe_curl_get(self, url: str) -> tuple[int, str]:
        """Single lightweight curl_cffi request that never throws on 429/403."""
        self._sleep_jitter()
        session = self._get_session()
        headers = self._random_headers(referer="https://x.com")
        try:
            resp = session.get(
                url,
                headers=headers,
                impersonate="chrome",
                timeout=self.settings.request_timeout_sec,
                allow_redirects=True,
            )
            return resp.status_code, resp.text or ""
        except Exception as exc:
            logger.debug("[x] curl_cffi request error on %s: %s", url, exc)
            return 0, ""

    def _fetch_tier1_syndication_and_mirrors(self, handle: str) -> list[dict[str, Any]]:
        """Tier 1: Syndication timeline endpoint followed by X_NITTER_INSTANCES mirrors."""
        synd_url = self.x_config.syndication_url_template.format(handle=handle)
        status, body = self._safe_curl_get(synd_url)
        if status == 200 and body:
            tweets = self.parse_syndication_payload(body, handle=handle)
            if tweets:
                logger.info("[x] Tier-1 syndication fetched %d tweets for @%s", len(tweets), handle)
                return tweets
        else:
            logger.debug("[x] Syndication HTTP %s for @%s; trying fallback mirrors.", status, handle)

        for instance in self.settings.x_nitter_instances:
            rss_url = f"{instance}/{handle}/rss"
            r_status, r_body = self._safe_curl_get(rss_url)
            if r_status == 200 and "<item>" in r_body:
                tweets = self.parse_nitter_rss(r_body, handle=handle)
                if tweets:
                    logger.info("[x] Tier-1 mirror RSS (%s) fetched %d tweets for @%s", instance, len(tweets), handle)
                    return tweets

            html_url = f"{instance}/{handle}"
            h_status, h_body = self._safe_curl_get(html_url)
            if h_status == 200 and "timeline-item" in h_body:
                tweets = self.parse_nitter_html(h_body, handle=handle)
                if tweets:
                    logger.info("[x] Tier-1 mirror HTML (%s) fetched %d tweets for @%s", instance, len(tweets), handle)
                    return tweets

        return []

    # ------------------------------------------------------------------
    # Tier 2: Authenticated Headless Playwright + UserTweets GraphQL
    # ------------------------------------------------------------------
    @staticmethod
    def parse_user_tweets_graphql(payload: dict[str, Any], *, handle: str) -> list[dict[str, Any]]:
        """Recursively parse X internal UserTweets / UserTweetsAndReplies GraphQL JSON."""
        tweets: list[dict[str, Any]] = []
        seen_ids: set[str] = set()

        def _unwrap_tweet_result(node: Any) -> dict[str, Any] | None:
            if not isinstance(node, dict):
                return None
            if node.get("__typename") == "TweetWithVisibilityResults" and isinstance(node.get("tweet"), dict):
                node = node["tweet"]
            if "legacy" in node and isinstance(node["legacy"], dict):
                return node
            return None

        def _walk(obj: Any) -> None:
            if isinstance(obj, dict):
                if "tweet_results" in obj and isinstance(obj["tweet_results"], dict):
                    tw_obj = _unwrap_tweet_result(obj["tweet_results"].get("result"))
                    if tw_obj:
                        legacy = tw_obj["legacy"]
                        tweet_id = str(tw_obj.get("rest_id") or legacy.get("id_str") or "").strip() or None
                        if tweet_id and tweet_id in seen_ids:
                            return
                        # Prefer full note_tweet text for X Premium long-form box office posts
                        note_text = (
                            tw_obj.get("note_tweet", {})
                            .get("note_tweet_results", {})
                            .get("result", {})
                            .get("text")
                        )
                        text = str(note_text or legacy.get("full_text") or "").strip()
                        if text:
                            if tweet_id:
                                seen_ids.add(tweet_id)
                            user_legacy = (
                                tw_obj.get("core", {})
                                .get("user_results", {})
                                .get("result", {})
                                .get("legacy", {})
                            )
                            screen_name = str(user_legacy.get("screen_name") or handle)
                            is_rt = bool(legacy.get("retweeted_status_result") or text.startswith("RT @"))
                            media_items = (legacy.get("extended_entities") or legacy.get("entities") or {}).get("media") or []
                            media_urls = [
                                str(m.get("media_url_https"))
                                for m in media_items
                                if m.get("media_url_https")
                            ]
                            tweets.append(
                                {
                                    "tweet_id": tweet_id,
                                    "handle": screen_name,
                                    "text": text,
                                    "created_at": legacy.get("created_at"),
                                    "is_retweet": is_rt,
                                    "tweet_url": f"https://x.com/{screen_name}/status/{tweet_id}"
                                    if tweet_id
                                    else f"https://x.com/{screen_name}",
                                    "media_urls": media_urls,
                                }
                            )
                for val in obj.values():
                    _walk(val)
            elif isinstance(obj, list):
                for item in obj:
                    _walk(item)

        _walk(payload)
        return tweets

    def _fetch_tier2_playwright_graphql(self, handle: str) -> list[dict[str, Any]]:
        """Tier 2: Headless Playwright injecting auth_token/ct0 and intercepting UserTweets JSON."""
        logger.info("[x] Engaging Tier-2 Playwright GraphQL capture for @%s", handle)
        if self._playwright is None:
            self._playwright = sync_playwright().start()
        if self._browser is None:
            self._browser = self._playwright.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                ],
            )

        context = self._browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1366, "height": 900},
            locale="en-IN",
        )
        context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
        )

        # Inject X session cookies if configured in .env
        if self.settings.x_auth_token and self.settings.x_ct0:
            cookies = []
            for domain in (".x.com", ".twitter.com"):
                cookies.extend(
                    [
                        {
                            "name": "auth_token",
                            "value": self.settings.x_auth_token,
                            "domain": domain,
                            "path": "/",
                            "httpOnly": True,
                            "secure": True,
                        },
                        {
                            "name": "ct0",
                            "value": self.settings.x_ct0,
                            "domain": domain,
                            "path": "/",
                            "httpOnly": False,
                            "secure": True,
                        },
                    ]
                )
            context.add_cookies(cookies)

        captured_tweets: list[dict[str, Any]] = []
        page = context.new_page()

        def _on_response(response: PlaywrightResponse) -> None:
            url = response.url
            if "UserTweets" not in url and "UserByScreenName" not in url:
                return
            if response.status != 200 or "UserTweets" not in url:
                return
            try:
                data = response.json()
                captured_tweets.extend(self.parse_user_tweets_graphql(data, handle=handle))
            except Exception as exc:
                logger.debug("[x] Failed parsing UserTweets JSON for @%s: %s", handle, exc)

        page.on("response", _on_response)
        try:
            target_url = f"https://x.com/{handle}"
            page.goto(
                target_url,
                wait_until="domcontentloaded",
                timeout=self.settings.playwright_timeout_ms,
            )
            page.wait_for_timeout(random.randint(3000, 4500))
            try:
                page.wait_for_load_state("networkidle", timeout=8000)
            except Exception:
                pass

            # Light scroll to trigger second timeline page if needed
            if not captured_tweets:
                page.mouse.wheel(0, 1200)
                page.wait_for_timeout(2000)

            # Fallback DOM check ONLY if UserTweets GraphQL was not captured
            if not captured_tweets:
                html = page.content()
                soup = BeautifulSoup(html, "lxml")
                for article in soup.select("article[data-testid='tweet']"):
                    text_el = article.select_one("[data-testid='tweetText']")
                    time_el = article.select_one("time[datetime]")
                    link_el = article.select_one("a[href*='/status/']")
                    text = text_el.get_text(" ", strip=True) if text_el else ""
                    if not text:
                        continue
                    href = link_el.get("href", "") if link_el else ""
                    m_id = re.search(r"/status/(\d+)", href)
                    tweet_id = m_id.group(1) if m_id else None
                    is_rt = "reposted" in article.get_text(" ", strip=True)[:120].lower()
                    captured_tweets.append(
                        {
                            "tweet_id": tweet_id,
                            "handle": handle,
                            "text": text,
                            "created_at": time_el.get("datetime") if time_el else None,
                            "is_retweet": is_rt,
                            "tweet_url": f"https://x.com/{handle}/status/{tweet_id}"
                            if tweet_id
                            else target_url,
                            "media_urls": [],
                        }
                    )
        finally:
            context.close()

        return captured_tweets

    def _fetch_tweets_for_handle(self, handle: str) -> list[dict[str, Any]]:
        tweets = self._fetch_tier1_syndication_and_mirrors(handle)
        if not tweets:
            tweets = self._fetch_tier2_playwright_graphql(handle)
        return tweets

    # ------------------------------------------------------------------
    # BaseScraper Interface Implementation
    # ------------------------------------------------------------------
    def parse_listings(
        self,
        html: str,
        *,
        language: str | None = None,
        base_url: str | None = None,
    ) -> list[dict[str, Any]]:
        """Parse syndication, RSS, or GraphQL payload into raw tweet dicts filtered by 48h + keywords."""
        handle = "unknown"
        if base_url:
            m_handle = re.search(r"(?:screen-name/|x\.com/|twitter\.com/)([A-Za-z0-9_]+)", base_url)
            if m_handle:
                handle = m_handle.group(1)

        stripped = html.strip()
        raw_tweets: list[dict[str, Any]] = []
        if "<rss" in stripped[:300].lower() or "<item>" in stripped[:1500]:
            raw_tweets = self.parse_nitter_rss(stripped, handle=handle)
        elif stripped.startswith("{") and "UserTweets" in stripped or '"tweet_results"' in stripped:
            try:
                raw_tweets = self.parse_user_tweets_graphql(json.loads(stripped), handle=handle)
            except Exception:
                raw_tweets = self.parse_syndication_payload(stripped, handle=handle)
        elif "timeline-item" in stripped and "tweet-content" in stripped:
            raw_tweets = self.parse_nitter_html(stripped, handle=handle)
        else:
            raw_tweets = self.parse_syndication_payload(stripped, handle=handle)

        default_lang = language or "Malayalam"
        listings: list[dict[str, Any]] = []
        for tw in raw_tweets:
            if not self._is_within_recency_window(tw.get("created_at")):
                continue
            if not self.tweet_parser.is_relevant_tweet(
                tw.get("text", ""), is_retweet=bool(tw.get("is_retweet"))
            ):
                continue
            listings.append(
                {
                    **tw,
                    "default_language": default_lang,
                    "has_inline_full_record": True,
                }
            )
        return listings

    def parse_movie_details(
        self,
        html: str,
        listing_item: dict[str, Any],
    ) -> dict[str, Any]:
        """Parse tweet text into structured financial fields (used when detail fetch is invoked)."""
        return {**listing_item, "raw_html": html}

    def normalize(self, raw_record: dict[str, Any]) -> RawScrapedMovie:
        """Normalize a single ParsedTweetRecord payload into RawScrapedMovie."""
        parsed: ParsedTweetRecord
        if isinstance(raw_record.get("parsed"), ParsedTweetRecord):
            parsed = raw_record["parsed"]
        else:
            results = self.tweet_parser.parse_tweet(
                str(raw_record.get("text") or ""),
                default_language=str(raw_record.get("default_language") or "Malayalam"),
                tweet_id=raw_record.get("tweet_id"),
                tweet_url=raw_record.get("tweet_url"),
                handle=raw_record.get("handle"),
                tweeted_at=raw_record.get("tweeted_at") or raw_record.get("created_at"),
                is_retweet=bool(raw_record.get("is_retweet")),
            )
            if not results:
                raise ValueError("Tweet contained no extractable box office collection figures.")
            parsed = results[0]

        dt = self.parse_tweet_timestamp(parsed.tweeted_at)
        scraped_iso = dt.isoformat() if dt else datetime.now(timezone.utc).isoformat()
        extra_metrics: dict[str, Any] = {
            "handle": parsed.handle,
            "tweet_id": parsed.tweet_id,
        }
        if parsed.kerala_gross_cr is not None:
            extra_metrics["kerala_gross_cr"] = parsed.kerala_gross_cr

        day_count = max(
            [parsed.day_number or 0] + [entry.day for entry in parsed.daily_breakdown]
        )

        return RawScrapedMovie(
            source=self.source_name,
            source_url=parsed.tweet_url or f"https://x.com/{parsed.handle or ''}",
            title=parsed.title,
            language=parsed.language,
            budget_cr=parsed.budget_cr,
            india_net_cr=(
                0.0
                if parsed.is_single_day_only
                else float(parsed.india_net_cr or 0.0)
            ),
            india_gross_cr=parsed.india_gross_cr,
            overseas_cr=parsed.overseas_cr,
            worldwide_gross_cr=parsed.worldwide_gross_cr,
            verdict=parsed.verdict,
            day_count=day_count,
            daily_breakdown=parsed.daily_breakdown,
            scraped_at=scraped_iso,
            extra_metrics=extra_metrics,
        )

    def _select_handles_for_language(self, language: str | None) -> list[tuple[str, str]]:
        if not self.x_config.enabled:
            return []
        req = (language or "all").strip().lower()
        selected: list[tuple[str, str]] = []
        for handle, cfg in self.x_config.handles.items():
            if req == "all":
                selected.append((handle, cfg.language))
                continue
            tags_lower = {t.lower() for t in cfg.tags}
            if cfg.language.lower() == req or req in tags_lower:
                selected.append((handle, cfg.language))
        return selected

    def scrape(
        self,
        *,
        language: str | None = None,
        limit: int | None = None,
    ) -> tuple[list[RawScrapedMovie], dict[str, int], list[dict[str, Any]]]:
        """Fetch recent tweets across configured handles, filter by 48h + keywords, and normalize."""
        handles = self._select_handles_for_language(language)
        metrics = {
            "category_pages_fetched": 0,
            "listings_discovered": 0,
            "movies_scraped": 0,
            "movie_errors": 0,
        }
        error_events: list[dict[str, Any]] = []
        seen_tweet_keys: set[str] = set()
        results: list[RawScrapedMovie] = []
        req_lang_lower = (language or "all").strip().lower()

        for handle, default_lang in handles:
            try:
                tweets = self._fetch_tweets_for_handle(handle)
                metrics["category_pages_fetched"] += 1
            except Exception as exc:
                metrics["movie_errors"] += 1
                logger.warning("[x] Failed fetching handle @%s: %s", handle, exc)
                error_events.append(
                    {
                        "stage": "scrape_listing",
                        "source": self.source_name,
                        "url": f"https://x.com/{handle}",
                        "movie_title": None,
                        "exception_type": type(exc).__name__,
                        "message": str(exc),
                    }
                )
                continue

            for tw in tweets:
                try:
                    if not self._is_within_recency_window(tw.get("created_at")):
                        continue

                    tweet_id = tw.get("tweet_id")
                    text = str(tw.get("text") or "").strip()
                    dedup_key = str(tweet_id or hash(text))
                    if dedup_key in seen_tweet_keys:
                        continue
                    seen_tweet_keys.add(dedup_key)

                    dt = self.parse_tweet_timestamp(tw.get("created_at"))
                    tweeted_iso = dt.isoformat() if dt else None

                    parsed_list = self.tweet_parser.parse_tweet(
                        text,
                        default_language=default_lang,
                        tweet_id=tweet_id,
                        tweet_url=tw.get("tweet_url"),
                        handle=tw.get("handle") or handle,
                        tweeted_at=tweeted_iso,
                        is_retweet=bool(tw.get("is_retweet")),
                    )
                    if not parsed_list:
                        continue

                    metrics["listings_discovered"] += len(parsed_list)
                    for parsed in parsed_list:
                        if (
                            req_lang_lower not in {"all", "pan-india"}
                            and parsed.language.lower() != req_lang_lower
                            and parsed.language.lower() != "pan-india"
                        ):
                            continue
                        raw_movie = self.normalize({"parsed": parsed})
                        if (
                            raw_movie.india_net_cr <= 0.0
                            and raw_movie.worldwide_gross_cr is None
                            and raw_movie.india_gross_cr is None
                            and not raw_movie.daily_breakdown
                        ):
                            continue
                        results.append(raw_movie)
                        metrics["movies_scraped"] += 1
                        if limit and len(results) >= limit:
                            return results, metrics, error_events
                except Exception as exc:
                    metrics["movie_errors"] += 1
                    logger.warning("[x] Isolated tweet parse error on @%s: %s", handle, exc)
                    error_events.append(
                        {
                            "stage": "scrape_movie",
                            "source": self.source_name,
                            "url": tw.get("tweet_url"),
                            "movie_title": None,
                            "exception_type": type(exc).__name__,
                            "message": str(exc),
                        }
                    )

        return results, metrics, error_events
