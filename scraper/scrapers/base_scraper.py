"""Abstract base scraper with curl_cffi TLS impersonation, Playwright fallback, and retries."""

from __future__ import annotations

import random
import time
from abc import ABC, abstractmethod
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag
from curl_cffi import requests as cffi_requests
from lxml import html as lxml_html
from playwright.sync_api import Browser, Playwright, sync_playwright
from tenacity import (
    RetryCallState,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from config.settings import Settings, SourceConfig, get_settings, load_sources_config
from utils.logger import get_logger
from utils.models import RawScrapedMovie

logger = get_logger("scrapers.base")

_USER_AGENTS: tuple[str, ...] = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 Edg/132.0.0.0",
)

_CF_CHALLENGE_MARKERS: tuple[str, ...] = (
    "just a moment...",
    "cf-browser-verification",
    "__cf_chl_",
    "checking your browser before accessing",
    "enable javascript and cookies to continue",
    "attention required! | cloudflare",
    "ddos protection by cloudflare",
)


class FetchError(RuntimeError):
    """Raised when both curl_cffi and Playwright fail to retrieve usable HTML."""


class _ChallengeOrBlockedError(RuntimeError):
    """Signals HTTP 403/429/503 or JS anti-bot challenge requiring Playwright fallback."""


class _TransientHttpError(RuntimeError):
    """Signals transient HTTP/network failure eligible for retry."""


def _supported_chrome_impersonations() -> tuple[str, ...]:
    preferred = ["chrome131", "chrome136", "chrome124", "chrome120", "chrome"]
    try:
        available = {b.value for b in cffi_requests.BrowserType}
        filtered = [p for p in preferred if p in available]
        return tuple(filtered) if filtered else ("chrome",)
    except Exception:
        return ("chrome",)


_IMPERSONATE_PROFILES = _supported_chrome_impersonations()


class BaseScraper(ABC):
    """Strict interface and anti-bot resilient HTTP client for box office scrapers."""

    source_name: str = ""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        source_config: SourceConfig | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        if source_config is not None:
            self.source_config = source_config
        else:
            sources_cfg = load_sources_config(self.settings.sources_config_path)
            if self.source_name not in sources_cfg.sources:
                raise KeyError(
                    f"Source '{self.source_name}' missing from {self.settings.sources_config_path}"
                )
            self.source_config = sources_cfg.sources[self.source_name]

        self.base_url = self.source_config.base_url.rstrip("/")
        self.selectors = self.source_config.selectors
        self._session: cffi_requests.Session | None = None
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._request_count = 0

    def __enter__(self) -> "BaseScraper":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.close()

    def close(self) -> None:
        """Close persistent HTTP session and Playwright browser if initialized."""
        if self._session is not None:
            try:
                self._session.close()
            except Exception:
                pass
            self._session = None

        if self._browser is not None:
            try:
                self._browser.close()
            except Exception:
                pass
            self._browser = None

        if self._playwright is not None:
            try:
                self._playwright.stop()
            except Exception:
                pass
            self._playwright = None

    def _get_session(self) -> cffi_requests.Session:
        if self._session is None:
            self._session = cffi_requests.Session()
        return self._session

    @staticmethod
    def _random_headers(referer: str | None = None) -> dict[str, str]:
        ua = random.choice(_USER_AGENTS)
        headers = {
            "User-Agent": ua,
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/avif,image/webp,*/*;q=0.8"
            ),
            "Accept-Language": "en-IN,en-US;q=0.9,en;q=0.8",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "Upgrade-Insecure-Requests": "1",
        }
        if referer:
            headers["Referer"] = referer
        return headers

    def _sleep_jitter(self) -> None:
        """Apply randomized delay between requests (1.5s - 4.0s default) to prevent throttling."""
        if self._request_count == 0:
            self._request_count += 1
            return
        self._request_count += 1
        delay = random.uniform(self.settings.min_delay_sec, self.settings.max_delay_sec)
        if delay > 0:
            time.sleep(delay)

    @staticmethod
    def _is_challenge_response(status_code: int, body: str) -> bool:
        if status_code in {403, 429, 503}:
            return True
        snippet = body[:6000].lower()
        return any(marker in snippet for marker in _CF_CHALLENGE_MARKERS)

    def _fetch_with_curl_cffi(self, url: str) -> str:
        session = self._get_session()
        impersonate = random.choice(_IMPERSONATE_PROFILES)
        headers = self._random_headers(referer=self.base_url)

        response = session.get(
            url,
            headers=headers,
            impersonate=impersonate,
            timeout=self.settings.request_timeout_sec,
            allow_redirects=True,
        )

        text = response.text or ""
        if self._is_challenge_response(response.status_code, text):
            raise _ChallengeOrBlockedError(
                f"Blocked or JS challenge detected (HTTP {response.status_code}) on {url}"
            )

        if response.status_code >= 500 or response.status_code == 408:
            raise _TransientHttpError(f"HTTP {response.status_code} on {url}")

        if response.status_code >= 400:
            raise FetchError(f"HTTP {response.status_code} fetching {url}")

        if not text.strip():
            raise _TransientHttpError(f"Empty response body from {url}")

        return text

    def _fetch_with_playwright(self, url: str) -> str:
        """Headless Chromium fallback when curl_cffi encounters 403 or Cloudflare JS challenge."""
        logger.warning("Engaging headless Playwright fallback for %s", url)
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
            user_agent=random.choice(_USER_AGENTS),
            viewport={"width": 1366, "height": 768},
            locale="en-IN",
        )
        context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
        )
        page = context.new_page()
        try:
            response = page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=self.settings.playwright_timeout_ms,
            )
            # Allow JS challenge / dynamic table hydration to settle briefly
            page.wait_for_timeout(2500)
            try:
                page.wait_for_load_state("networkidle", timeout=8000)
            except Exception:
                pass

            content = page.content()
            status = response.status if response else 200
            if self._is_challenge_response(status, content):
                raise FetchError(
                    f"Playwright fallback could not clear challenge (HTTP {status}) on {url}"
                )
            return content
        finally:
            context.close()

    def _log_retry(self, retry_state: RetryCallState) -> None:
        exc = retry_state.outcome.exception() if retry_state.outcome else None
        logger.warning(
            "[%s] Fetch retry #%d after error: %s",
            self.source_name,
            retry_state.attempt_number,
            exc,
        )

    def fetch_html(self, url: str) -> str:
        """Fetch raw HTML using curl_cffi with exponential backoff and Playwright fallback."""
        self._sleep_jitter()

        @retry(
            stop=stop_after_attempt(self.settings.retry_max_attempts),
            wait=wait_exponential(
                multiplier=self.settings.retry_base_delay_sec,
                min=self.settings.retry_base_delay_sec,
                max=self.settings.retry_max_delay_sec,
            ),
            retry=retry_if_exception_type(_TransientHttpError),
            before_sleep=self._log_retry,
            reraise=True,
        )
        def _attempt_primary() -> str:
            try:
                return self._fetch_with_curl_cffi(url)
            except _ChallengeOrBlockedError:
                raise
            except _TransientHttpError:
                raise
            except FetchError:
                raise
            except Exception as exc:
                raise _TransientHttpError(f"curl_cffi network error on {url}: {exc}") from exc

        try:
            return _attempt_primary()
        except _ChallengeOrBlockedError as challenge_exc:
            logger.info("[%s] %s -> switching to Playwright", self.source_name, challenge_exc)
            return self._fetch_with_playwright(url)

    # ------------------------------------------------------------------
    # Config-driven CSS / XPath selector helpers
    # ------------------------------------------------------------------
    @staticmethod
    def make_soup(html: str) -> BeautifulSoup:
        return BeautifulSoup(html, "lxml")

    @staticmethod
    def make_tree(html: str) -> Any:
        return lxml_html.fromstring(html)

    @staticmethod
    def select_nodes(
        soup: BeautifulSoup | Tag,
        selector_cfg: dict[str, Any] | str | None,
        *,
        tree: Any = None,
    ) -> list[Tag]:
        """Select matching BeautifulSoup tags via CSS selector or XPath expression from sources.yaml."""
        if not selector_cfg:
            return []
        if isinstance(selector_cfg, str):
            return soup.select(selector_cfg)

        css_sel = selector_cfg.get("css")
        if css_sel:
            found = soup.select(css_sel)
            if found:
                return found

        xpath_sel = selector_cfg.get("xpath")
        if xpath_sel:
            target_tree = tree
            if target_tree is None:
                target_tree = lxml_html.fromstring(str(soup))
            try:
                matched_els = target_tree.xpath(xpath_sel)
                tags: list[Tag] = []
                for el in matched_els:
                    if hasattr(el, "tag"):
                        el_html = lxml_html.tostring(el, encoding="unicode")
                        parsed = BeautifulSoup(el_html, "lxml")
                        root = parsed.body.next_element if parsed.body else parsed.next_element
                        if isinstance(root, Tag):
                            tags.append(root)
                return tags
            except Exception as exc:
                logger.debug("XPath selector '%s' evaluation failed: %s", xpath_sel, exc)

        return []

    def resolve_url(self, href: str) -> str:
        return urljoin(f"{self.base_url}/", href)

    def get_category_urls(self, language: str | None = None) -> list[tuple[str, str]]:
        """Return [(category_language, url), ...] filtered by requested language."""
        categories = self.source_config.categories
        if not language or language.strip().lower() == "all":
            pairs: list[tuple[str, str]] = []
            for cat_lang, urls in categories.items():
                for u in urls:
                    pairs.append((cat_lang, u))
            return pairs

        req_lower = language.strip().lower()
        matched_pairs: list[tuple[str, str]] = []
        for cat_lang, urls in categories.items():
            if cat_lang.lower() == req_lower:
                for u in urls:
                    matched_pairs.append((cat_lang, u))
        return matched_pairs

    # ------------------------------------------------------------------
    # Strict Abstract Interface
    # ------------------------------------------------------------------
    @abstractmethod
    def parse_listings(
        self,
        html: str,
        *,
        language: str | None = None,
        base_url: str | None = None,
    ) -> list[dict[str, Any]]:
        """Parse category/hub page HTML into candidate movie listing dicts."""

    @abstractmethod
    def parse_movie_details(
        self,
        html: str,
        listing_item: dict[str, Any],
    ) -> dict[str, Any]:
        """Parse movie detail page HTML into raw extracted financial & metadata fields."""

    @abstractmethod
    def normalize(self, raw_record: dict[str, Any]) -> RawScrapedMovie:
        """Normalize raw extracted fields into a validated RawScrapedMovie."""

    def scrape(
        self,
        *,
        language: str | None = None,
        limit: int | None = None,
    ) -> tuple[list[RawScrapedMovie], dict[str, int], list[dict[str, Any]]]:
        """Execute full scrape flow with isolated per-movie error containment.

        Returns:
            (records, source_metrics, error_events)
        """
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
                        existing_item = candidates_by_key[dedup_key]
                        for k, v in item.items():
                            if existing_item.get(k) is None and v is not None:
                                existing_item[k] = v
                    if limit and len(candidates_by_key) >= limit and language and language.lower() != "all":
                        break
            except Exception as exc:
                metrics["movie_errors"] += 1
                logger.error(
                    "[%s] Failed category listing %s (%s): %s",
                    self.source_name,
                    cat_lang,
                    url,
                    exc,
                )
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

        candidates = list(candidates_by_key.values())
        if limit is not None and limit > 0:
            candidates = candidates[:limit]
        metrics["listings_discovered"] = len(candidates)

        results: list[RawScrapedMovie] = []
        for item in candidates:
            movie_title = item.get("title", "Unknown")
            detail_url = item.get("detail_url")
            try:
                if item.get("has_inline_full_record") and not detail_url:
                    raw_detail = dict(item)
                elif detail_url:
                    logger.debug("[%s] Scraping detail page for '%s': %s", self.source_name, movie_title, detail_url)
                    detail_html = self.fetch_html(detail_url)
                    raw_detail = self.parse_movie_details(detail_html, item)
                else:
                    raw_detail = dict(item)

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
