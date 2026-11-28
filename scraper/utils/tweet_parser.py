"""Intelligent NLP/Regex parser turning unstructured Indian box office tweets into structured figures."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Iterable

from pydantic import BaseModel, Field

from utils.currency_parser import normalize_verdict, parse_inr_to_crores
from utils.models import DailyCollectionEntry
from utils.title_matcher import TitleMatcher, normalize_title

_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
_MENTION_RE = re.compile(r"@\w+")
_WHITESPACE_RE = re.compile(r"[ \t]+")

# Non-financial count traps (BMS/Paytm tickets, trailer views, likes, screens, shows)
_SPAM_COUNT_RE = re.compile(
    r"(?:"
    r"\b\d+(?:[.,]\d+)?\s*[kmb]?\+?\s*(?:tickets?|tix)(?:\s+(?:sold|booked|pre-sales?))?(?:\s+(?:on|via|in)\s+(?:bms|bookmyshow|paytm|district))?\b|"
    r"\b(?:bms|bookmyshow|paytm|district)\s*(?:sold|hourly|sales|trending|interests?)?[:\-\s]*\d+(?:[.,]\d+)?\s*[kmb]?\+?|"
    r"\b\d+(?:[.,]\d+)?\s*(?:m|million|k|b|crores?|cr|lakhs?|l)\+?\s*(?:views?|likes?|retweets?|reposts?|streams?|subscribers?|followers?|interests?)\b|"
    r"\b\d+(?:,\d{3})*\+?\s*(?:screens?|shows?|theatres?|theaters?|centers?|centres?)\b|"
    r"\b\d+(?:[.,]\d+)?%\s*(?:occupancy|growth|drop)\b|"
    r"#?\d+\s*(?:trending|spot)\b"
    r")",
    re.IGNORECASE,
)

# Currency figure extractor (₹ 12.45 Cr, 45.2 Lakhs, 1.20 Crore, ₹14.80 Cr, 72.00 cr)
_CURRENCY_RE = re.compile(
    r"(?:₹|rs\.?|inr)?\s*"
    r"\d+(?:,\d{2,3})*(?:\.\d+)?\s*"
    r"(?:crores?|crs?\.?|cr\.?|lakhs?|lacs?|l\.?)"
    r"|"
    r"(?:₹|rs\.?|inr)\s*\d+(?:,\d{2,3})*(?:\.\d+)?",
    re.IGNORECASE,
)

# Hashtags and CamelCase splitting
_HASHTAG_RE = re.compile(r"#([A-Za-z0-9_]+)")
_CAMEL_SPLIT_RE = re.compile(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Za-z])(?=\d)|(?<=\d)(?=[A-Za-z])")

_GENERIC_HASHTAGS = {
    "boxoffice",
    "bo",
    "mollywood",
    "kollywood",
    "bollywood",
    "tollywood",
    "sandalwood",
    "indianboxoffice",
    "keralaboxoffice",
    "tamilboxoffice",
    "hindiboxoffice",
    "teluguboxoffice",
    "kerala",
    "malayalam",
    "tamil",
    "hindi",
    "telugu",
    "kannada",
    "english",
    "india",
    "worldwide",
    "ww",
    "nett",
    "net",
    "gross",
    "day1",
    "day2",
    "day3",
    "openingday",
    "weekend",
    "breaking",
    "update",
    "sacnilk",
    "koimoi",
    "trackmollywood",
    "forumkeralam",
    "blockbuster",
    "superhit",
    "hit",
    "flop",
    "mega",
    "panindia",
    "records",
    "record",
}

_METRIC_LEADING_WORDS = (
    "day",
    "d1",
    "d2",
    "d3",
    "d4",
    "d5",
    "d6",
    "d7",
    "opening",
    "weekend",
    "week",
    "total",
    "grand total",
    "india",
    "kerala",
    "tn",
    "ap",
    "tg",
    "ka",
    "roi",
    "overseas",
    "worldwide",
    "ww",
    "gross",
    "nett",
    "net",
    "budget",
    "verdict",
    "mon",
    "tue",
    "wed",
    "thu",
    "fri",
    "sat",
    "sun",
)

_DAY_PATTERNS: list[tuple[re.Pattern[str], int | None]] = [
    (re.compile(r"\b(?:day[\s\-]*(\d+)|d(\d+))\b", re.I), None),
    (re.compile(r"\b(\d+)\s*days?\b", re.I), None),
    (re.compile(r"\b(?:opening\s*day|first\s*day|1st\s*day)\b", re.I), 1),
    (re.compile(r"\b4[\-\s]*day\s*weekend\b", re.I), 4),
    (re.compile(r"\b(?:opening\s*weekend|1st\s*weekend|weekend)\b", re.I), 3),
    (re.compile(r"\b(?:week\s*1|1st\s*week|first\s*week)\b", re.I), 7),
]

_WEEKDAY_SEQ_RE = re.compile(
    r"\b(fri|sat|sun|mon|tue|wed|thu)\s+(\d+(?:\.\d+)?\s*(?:crores?|cr\.?|lakhs?|l\.?))",
    re.IGNORECASE,
)

_LANG_HINTS = {
    "malayalam": "Malayalam",
    "mollywood": "Malayalam",
    "kerala": "Malayalam",
    "tamil": "Tamil",
    "kollywood": "Tamil",
    "hindi": "Hindi",
    "bollywood": "Hindi",
    "telugu": "Telugu",
    "tollywood": "Telugu",
    "kannada": "Kannada",
    "sandalwood": "Kannada",
    "pan-india": "Pan-India",
    "pan india": "Pan-India",
}


class ParsedTweetRecord(BaseModel):
    """Structured box office extraction from a single tweet (or movie line in a summary tweet)."""

    title: str
    language: str
    day_number: int | None = None
    india_net_cr: float | None = None
    india_gross_cr: float | None = None
    kerala_gross_cr: float | None = None
    overseas_cr: float | None = None
    worldwide_gross_cr: float | None = None
    budget_cr: float | None = None
    verdict: str | None = None
    is_single_day_only: bool = False
    daily_breakdown: list[DailyCollectionEntry] = Field(default_factory=list)
    tweet_id: str | None = None
    tweet_url: str | None = None
    handle: str | None = None
    tweeted_at: str | None = None
    raw_text: str


def _humanize_hashtag(tag: str) -> str:
    spaced = tag.replace("_", " ")
    spaced = _CAMEL_SPLIT_RE.sub(" ", spaced)
    return re.sub(r"\s+", " ", spaced).strip()


def _detect_language(text: str, default_language: str) -> str:
    lowered = text.lower()
    # Explicit dubbed tags like "(Hindi)" take priority when present
    for token, lang in _LANG_HINTS.items():
        if re.search(rf"\b{re.escape(token)}\b", lowered):
            # Don't override Malayalam when Kerala appears alongside another regional film unless default matches
            if token == "kerala" and default_language != "Malayalam":
                continue
            return lang
    return default_language


def _extract_day_number(text: str) -> int | None:
    for pattern, fixed in _DAY_PATTERNS:
        m = pattern.search(text)
        if m:
            if fixed is not None:
                return fixed
            for grp in m.groups():
                if grp and grp.isdigit():
                    return int(grp)
    return None


class TweetParser:
    """Parses unstructured box office tracker tweets with spam filtering and fuzzy title lookup."""

    DEFAULT_KEYWORDS = (
        "crore",
        "cr",
        "lakhs",
        "lakh",
        "gross",
        "nett",
        "net",
        "day 1",
        "day 2",
        "weekend",
        "worldwide",
        "ww",
        "kerala",
        "boxoffice",
        "bo",
    )

    def __init__(
        self,
        *,
        known_titles: Iterable[str] = (),
        keywords: Iterable[str] | None = None,
        match_threshold: float = 84.0,
    ) -> None:
        self.known_titles = [t.strip() for t in known_titles if t and t.strip()]
        self.keywords = tuple((k.lower() for k in (keywords or self.DEFAULT_KEYWORDS)))
        self.matcher = TitleMatcher(threshold=match_threshold)

    def is_relevant_tweet(self, text: str, *, is_retweet: bool = False) -> bool:
        """Return True if tweet is original (non-RT) and mentions box-office keywords."""
        if not text or is_retweet:
            return False
        stripped = text.strip()
        if stripped.startswith("RT @") or stripped.lower().startswith("rt @"):
            return False
        lowered = stripped.lower()
        return any(
            re.search(rf"\b{re.escape(kw)}\b", lowered) if kw.isalnum() else (kw in lowered)
            for kw in self.keywords
        )

    @staticmethod
    def sanitize_text(text: str) -> str:
        """Remove URLs, mentions, and non-financial BMS/views/screen count traps."""
        cleaned = _URL_RE.sub(" ", text)
        cleaned = _MENTION_RE.sub(" ", cleaned)
        cleaned = _SPAM_COUNT_RE.sub(" ", cleaned)
        cleaned = re.sub(r"[ \t]+", " ", cleaned)
        return cleaned.strip()

    def _match_known_title(self, candidate_text: str) -> str | None:
        if not self.known_titles or not candidate_text.strip():
            return None
        match, score = self.matcher.find_best_match(candidate_text, self.known_titles)
        if match and score >= self.matcher.threshold:
            return match
        return None

    def extract_title(self, raw_segment: str) -> str | None:
        """Extract canonical movie title from hashtag, known catalog, or leading title text."""
        # 1. Inspect hashtags first (very common in Indian box office tweets)
        for tag in _HASHTAG_RE.findall(raw_segment):
            if tag.lower() in _GENERIC_HASHTAGS:
                continue
            humanized = _humanize_hashtag(tag)
            if len(humanized) < 2:
                continue
            known = self._match_known_title(humanized)
            return known or humanized

        # 2. Check leading segment before Day / Gross / Box Office / Colon / Dash
        lead = re.sub(r"^\s*\d+[\.\)]\s*", "", raw_segment).strip()
        lead = re.sub(r"^[🔥💥🚀🎬⭐📊🏆📌\s]+", "", lead)
        lead_match = re.split(
            r"\s+(?:day\s*\d+|opening\s+day|weekend|box\s*office|kerala|india\s+net|"
            r"worldwide|\bww\b|crosses|collects|grosses|enters|hits|breaches)\b|\s*[:\-–—|]\s*",
            lead,
            maxsplit=1,
            flags=re.IGNORECASE,
        )
        if lead_match:
            cand = re.sub(r"\([^)]*\)", "", lead_match[0]).strip(" .!?:;,-–—\"'")
            first_word = (cand.split()[0].lower() if cand.split() else "")
            if (
                2 <= len(cand) <= 60
                and first_word not in _METRIC_LEADING_WORDS
                and not _CURRENCY_RE.search(cand)
            ):
                known = self._match_known_title(cand)
                return known or cand

        # 3. Direct substring match against known active titles
        norm_seg = normalize_title(raw_segment)
        for title in self.known_titles:
            nt = normalize_title(title)
            if nt and len(nt) >= 4 and re.search(rf"\b{re.escape(nt)}\b", norm_seg):
                return title

        return None

    @staticmethod
    def _is_metric_label_line(line: str) -> bool:
        cleaned = re.sub(r"^\s*[-•*👉▪]+\s*", "", line).strip().lower()
        return any(
            cleaned.startswith(f"{w} ")
            or cleaned.startswith(f"{w}:")
            or cleaned.startswith(f"{w}-")
            or cleaned.startswith(f"{w}–")
            for w in _METRIC_LEADING_WORDS
        )

    def _split_multi_movie_segments(self, cleaned_text: str) -> list[tuple[str, str | None]]:
        """Split multi-movie summary tweets into independent (segment, header_context) pairs."""
        # Normalize pipe-separated multi-movie tweets onto lines
        lines = [
            part.strip()
            for raw_line in cleaned_text.splitlines()
            for part in (raw_line.split("|") if "|" in raw_line and raw_line.count("#") >= 2 else [raw_line])
            if part.strip()
        ]
        if len(lines) <= 1:
            return [(cleaned_text, None)]

        movie_lines: list[str] = []
        header_context_parts: list[str] = []

        for line in lines:
            has_currency = bool(_CURRENCY_RE.search(line))
            has_hashtag_title = any(
                tag.lower() not in _GENERIC_HASHTAGS
                for tag in _HASHTAG_RE.findall(line)
            )
            is_numbered = bool(re.match(r"^\s*\d+[\.\)]\s+", line))
            if has_currency and (is_numbered or (has_hashtag_title and not self._is_metric_label_line(line))):
                movie_lines.append(line)
            elif not has_currency:
                header_context_parts.append(line)

        if len(movie_lines) >= 2:
            header_ctx = " ".join(header_context_parts).strip() or None
            return [(ml, header_ctx) for ml in movie_lines]

        return [(cleaned_text, None)]

    def _parse_single_segment(
        self,
        segment: str,
        *,
        header_context: str | None,
        default_language: str,
        tweet_id: str | None,
        tweet_url: str | None,
        handle: str | None,
        tweeted_at: str | None,
    ) -> ParsedTweetRecord | None:
        title = self.extract_title(segment)
        if not title:
            return None

        combined_ctx = f"{header_context or ''} {segment}".strip()
        language = _detect_language(combined_ctx, default_language)
        day_number = _extract_day_number(segment) or _extract_day_number(header_context or "")
        verdict = normalize_verdict(segment)

        india_net_cr: float | None = None
        india_gross_cr: float | None = None
        kerala_gross_cr: float | None = None
        overseas_cr: float | None = None
        worldwide_gross_cr: float | None = None
        budget_cr: float | None = None
        daily_breakdown: list[DailyCollectionEntry] = []

        # Parse Taran Adarsh style weekday splits: "Fri 12.50 cr, Sat 15.10 cr, Sun 18.20 cr"
        weekday_hits = _WEEKDAY_SEQ_RE.findall(segment)
        if len(weekday_hits) >= 2:
            for idx, (_wd, amt_str) in enumerate(weekday_hits, start=1):
                val = parse_inr_to_crores(amt_str)
                if val is not None:
                    daily_breakdown.append(
                        DailyCollectionEntry(
                            day=idx,
                            date=None,
                            india_net_cr=val,
                            change_pct=None,
                        )
                    )

        # Clause-level financial extraction
        clauses = re.split(r"(?:[\n!;|]+|\.(?=\s+[A-Za-z])|,\s+(?=[A-Za-z]))", segment)
        for clause in clauses:
            c = clause.strip()
            if not c:
                continue
            matches = list(_CURRENCY_RE.finditer(c))
            if not matches:
                continue

            for m in matches:
                amt = parse_inr_to_crores(m.group(0))
                if amt is None or amt <= 0:
                    continue

                # Inspect label closest to m.start() so 'WW Box Office Day 15: India Net ₹420 Cr'
                # classifies as india_net_cr rather than being hijacked by earlier 'WW'.
                start_ctx = max(0, m.start() - 48)
                end_ctx = min(len(c), m.end() + 24)
                prefix_ctx = c[start_ctx : m.start()].lower()
                suffix_ctx = c[m.end() : end_ctx].lower()

                label_positions: list[tuple[int, str]] = []
                label_specs = (
                    ("worldwide", ("worldwide gross", "ww gross", "global gross", "worldwide", "ww", "global")),
                    ("kerala", ("kerala gross", "kl gross", "kerala", "kl")),
                    ("overseas", ("overseas gross", "overseas", "international")),
                    ("budget", ("budget",)),
                    ("india_gross", ("india gross", "domestic gross", "all india gross")),
                    ("india_net", ("india nett", "india net", "india biz", "nett", "net", "total")),
                )
                for bucket, tokens in label_specs:
                    for tok in tokens:
                        pos = prefix_ctx.rfind(tok)
                        if pos != -1:
                            label_positions.append((pos + len(tok), bucket))
                if not label_positions:
                    if "gross" in prefix_ctx:
                        label_positions.append((prefix_ctx.rfind("gross") + 5, "gross"))
                if not label_positions:
                    for bucket, tokens in (*label_specs, ("gross", ("gross",))):
                        for tok in tokens:
                            if tok in suffix_ctx:
                                label_positions.append((0, bucket))
                                break

                chosen_bucket = (
                    max(label_positions, key=lambda x: x[0])[1]
                    if label_positions
                    else None
                )

                if chosen_bucket == "worldwide":
                    worldwide_gross_cr = amt
                elif chosen_bucket == "kerala":
                    kerala_gross_cr = amt
                elif chosen_bucket == "overseas":
                    overseas_cr = amt
                elif chosen_bucket == "budget":
                    budget_cr = amt
                elif chosen_bucket == "india_gross":
                    india_gross_cr = amt
                elif chosen_bucket == "india_net":
                    india_net_cr = amt
                elif chosen_bucket == "gross":
                    if header_context and "kerala" in header_context.lower():
                        kerala_gross_cr = amt
                    elif default_language == "Malayalam" and "india" not in prefix_ctx:
                        kerala_gross_cr = amt
                    else:
                        india_gross_cr = amt
                else:
                    if header_context and "kerala" in header_context.lower():
                        kerala_gross_cr = amt
                    elif india_net_cr is None:
                        india_net_cr = amt

        # Handle explicit single-day India Net tweet -> create DailyCollectionEntry
        if day_number is not None and not daily_breakdown:
            # Only populate daily_breakdown[day_number] if tweet represents single-day India Net
            is_cumulative_only = bool(
                re.search(r"\b(?:total\s+\d+\s+days?|cumulative|\d+\s+days?\s+total)\b", segment, re.I)
            )
            if (
                india_net_cr is not None
                and not is_cumulative_only
                and day_number <= 365
            ):
                entry_date = None
                if tweeted_at:
                    try:
                        dt = datetime.fromisoformat(tweeted_at.replace("Z", "+00:00"))
                        entry_date = dt.strftime("%Y-%m-%d")
                    except ValueError:
                        entry_date = None
                daily_breakdown.append(
                    DailyCollectionEntry(
                        day=day_number,
                        date=entry_date,
                        india_net_cr=india_net_cr,
                        change_pct=None,
                    )
                )

        # Backfill date/change_pct for multi-day weekday splits
        if len(daily_breakdown) >= 2:
            if tweeted_at:
                try:
                    end_dt = datetime.fromisoformat(tweeted_at.replace("Z", "+00:00"))
                    total_days = len(daily_breakdown)
                    for idx, entry in enumerate(daily_breakdown):
                        entry.date = (end_dt - timedelta(days=total_days - 1 - idx)).strftime("%Y-%m-%d")
                except ValueError:
                    pass
            for idx in range(1, len(daily_breakdown)):
                prev = daily_breakdown[idx - 1]
                curr = daily_breakdown[idx]
                if prev.india_net_cr > 0 and curr.change_pct is None:
                    curr.change_pct = round(
                        ((curr.india_net_cr - prev.india_net_cr) / prev.india_net_cr) * 100.0,
                        2,
                    )
            if day_number is None:
                day_number = daily_breakdown[-1].day
            if india_net_cr is None:
                india_net_cr = round(sum(d.india_net_cr for d in daily_breakdown), 4)

        has_any_financial = any(
            val is not None and val > 0
            for val in (
                india_net_cr,
                india_gross_cr,
                kerala_gross_cr,
                overseas_cr,
                worldwide_gross_cr,
                budget_cr,
            )
        )
        if not has_any_financial:
            return None

        is_single_day_only = bool(
            day_number is not None
            and day_number > 1
            and len(daily_breakdown) == 1
            and not re.search(r"\b(?:total|cumulative|\d+\s*days?)\b", segment, re.I)
        )

        return ParsedTweetRecord(
            title=title,
            language=language,
            day_number=day_number,
            india_net_cr=india_net_cr,
            india_gross_cr=india_gross_cr,
            kerala_gross_cr=kerala_gross_cr,
            overseas_cr=overseas_cr,
            worldwide_gross_cr=worldwide_gross_cr,
            budget_cr=budget_cr,
            verdict=verdict,
            is_single_day_only=is_single_day_only,
            daily_breakdown=daily_breakdown,
            tweet_id=tweet_id,
            tweet_url=tweet_url,
            handle=handle,
            tweeted_at=tweeted_at,
            raw_text=segment,
        )

    def parse_tweet(
        self,
        text: str,
        *,
        default_language: str = "Malayalam",
        tweet_id: str | None = None,
        tweet_url: str | None = None,
        handle: str | None = None,
        tweeted_at: str | None = None,
        is_retweet: bool = False,
    ) -> list[ParsedTweetRecord]:
        """Parse a box office tweet into zero or more structured ParsedTweetRecords."""
        if not self.is_relevant_tweet(text, is_retweet=is_retweet):
            return []

        cleaned = self.sanitize_text(text)
        if not _CURRENCY_RE.search(cleaned):
            return []

        segments = self._split_multi_movie_segments(cleaned)
        parsed_records: list[ParsedTweetRecord] = []
        for seg, header_ctx in segments:
            rec = self._parse_single_segment(
                seg,
                header_context=header_ctx,
                default_language=default_language,
                tweet_id=tweet_id,
                tweet_url=tweet_url,
                handle=handle,
                tweeted_at=tweeted_at,
            )
            if rec is not None:
                parsed_records.append(rec)

        return parsed_records
