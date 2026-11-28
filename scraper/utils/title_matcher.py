"""String normalization, canonical slugging, and fuzzy matching for movie titles."""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from typing import Iterable

try:
    from rapidfuzz import fuzz as _rapidfuzz_fuzz
except ImportError:  # pragma: no cover - fallback when rapidfuzz is absent
    _rapidfuzz_fuzz = None


_PARENS_TAG_RE = re.compile(
    r"[\(\[]\s*(?:hindi|malayalam|tamil|telugu|kannada|english|marathi|punjabi|bengali|"
    r"pan[- ]india|dubbed|3d|imax|20\d{2}|19\d{2})\s*[\)\]]",
    re.IGNORECASE,
)
_TRAILING_YEAR_RE = re.compile(r"\s+(?:20\d{2}|19\d{2})$")
_SUBTITLE_SPLIT_RE = re.compile(r"\s*(?::|—|–|\s-\s)\s*")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9\s]")
_WHITESPACE_RE = re.compile(r"\s+")

# Match sequel markers like "Part 2", "Chapter 2", or standalone trailing numerals / Roman II..X
_PART_WORD_RE = re.compile(r"\b(?:part|chapter|vol\.?|volume)\s+(\d+|ii|iii|iv|v|vi|vii|viii|ix|x)\b", re.I)
_TRAILING_ROMAN_RE = re.compile(r"\b(ii|iii|iv|v|vi|vii|viii|ix|x)\b$", re.I)
_ROMAN_MAP = {
    "ii": "2",
    "iii": "3",
    "iv": "4",
    "v": "5",
    "vi": "6",
    "vii": "7",
    "viii": "8",
    "ix": "9",
    "x": "10",
}
_SEQUEL_NUM_RE = re.compile(r"\b(\d+)\b")


def _replace_roman_sequel(text: str) -> str:
    def _part_repl(m: re.Match[str]) -> str:
        tok = m.group(1).lower()
        return _ROMAN_MAP.get(tok, tok)

    updated = _PART_WORD_RE.sub(_part_repl, text)
    updated = _TRAILING_ROMAN_RE.sub(
        lambda m: _ROMAN_MAP.get(m.group(1).lower(), m.group(1).lower()),
        updated,
    )
    return updated


def normalize_title(title: str, *, strip_subtitle: bool = False) -> str:
    """Normalize a movie title for comparison and slugging.

    - Applies NFKD Unicode normalization and strips diacritics.
    - Strips language/format/year brackets such as '(Malayalam)' or '(2026)'.
    - Converts '&' to 'and' and normalizes Roman sequel numerals ('Part II' -> '2').
    - Optionally strips subtitles after ':' or ' - ' (e.g. 'Aadu 3: One Last Ride' -> 'Aadu 3').
    """
    if not title:
        return ""

    ascii_text = unicodedata.normalize("NFKD", str(title))
    ascii_text = "".join(ch for ch in ascii_text if not unicodedata.combining(ch))
    cleaned = ascii_text.strip()
    cleaned = _PARENS_TAG_RE.sub("", cleaned)
    cleaned = _TRAILING_YEAR_RE.sub("", cleaned)
    cleaned = cleaned.replace("&", " and ")

    if strip_subtitle:
        parts = _SUBTITLE_SPLIT_RE.split(cleaned, maxsplit=1)
        if parts and len(parts[0].strip()) >= 2:
            cleaned = parts[0].strip()

    cleaned = cleaned.lower()
    cleaned = _replace_roman_sequel(cleaned)
    cleaned = _NON_ALNUM_RE.sub(" ", cleaned)
    cleaned = _WHITESPACE_RE.sub(" ", cleaned).strip()
    return cleaned


def canonical_slug(title: str, *, language: str | None = None, strip_subtitle: bool = False) -> str:
    """Create a deterministic URL-safe slug from a movie title."""
    norm = normalize_title(title, strip_subtitle=strip_subtitle)
    slug = norm.replace(" ", "-")
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    if not slug:
        slug = "untitled-movie"
    if language:
        lang_slug = re.sub(r"[^a-z0-9]+", "-", language.lower()).strip("-")
        if lang_slug and not slug.endswith(f"-{lang_slug}"):
            slug = f"{slug}-{lang_slug}"
    return slug


def extract_sequel_numbers(title: str) -> list[str]:
    """Extract numeric sequel tokens so 'Drishyam 2' never fuzzy-matches 'Drishyam 3'."""
    norm = normalize_title(title, strip_subtitle=False)
    return _SEQUEL_NUM_RE.findall(norm)


def _fuzzy_score(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if a == b:
        return 100.0
    if _rapidfuzz_fuzz is not None:
        return float(
            max(
                _rapidfuzz_fuzz.ratio(a, b),
                _rapidfuzz_fuzz.token_sort_ratio(a, b),
                _rapidfuzz_fuzz.token_set_ratio(a, b) * 0.98,
            )
        )
    return round(SequenceMatcher(None, a, b).ratio() * 100.0, 2)


class TitleMatcher:
    """Fuzzy matcher and canonical slug registry across heterogeneous sources."""

    def __init__(self, threshold: float = 84.0) -> None:
        self.threshold = threshold
        # Maps canonical_slug -> representative base normalized title & metadata
        self._registry: dict[str, dict[str, str | None]] = {}

    @staticmethod
    def similarity(title_a: str, title_b: str) -> float:
        """Compute guarded similarity score in [0, 100] between two titles.

        Handles subtitle variants (e.g. 'Aadu 3: One Last Ride' vs 'Aadu 3') while
        strictly preventing different sequel numbers ('Aadu 2' vs 'Aadu 3') from matching.
        """
        full_a = normalize_title(title_a, strip_subtitle=False)
        full_b = normalize_title(title_b, strip_subtitle=False)
        if not full_a or not full_b:
            return 0.0
        if full_a == full_b:
            return 100.0

        base_a = normalize_title(title_a, strip_subtitle=True)
        base_b = normalize_title(title_b, strip_subtitle=True)

        # Sequel number guard on base titles (prevents 'Dhurandhar' matching 'Dhurandhar 2'
        # and 'Drishyam 2' matching 'Drishyam 3', while allowing 'Ramayana' vs 'Ramayana Part 1')
        seq_base_a = extract_sequel_numbers(base_a)
        seq_base_b = extract_sequel_numbers(base_b)
        if seq_base_a != seq_base_b:
            if seq_base_a and seq_base_b:
                return 0.0
            orphan_nums = [int(n) for n in (seq_base_a or seq_base_b) if n.isdigit()]
            if any(2 <= n <= 20 for n in orphan_nums):
                return 0.0

        seq_full_a = extract_sequel_numbers(full_a)
        seq_full_b = extract_sequel_numbers(full_b)
        if seq_full_a and seq_full_b and not (base_a == base_b) and seq_full_a != seq_full_b:
            return 0.0

        # Exact base-title match when one title simply carries a subtitle
        if base_a == base_b and len(base_a) >= 3:
            # Guard against two distinct sequels that only differ by subtitle (unlikely when both have subtitles)
            has_sub_a = base_a != full_a
            has_sub_b = base_b != full_b
            if not (has_sub_a and has_sub_b):
                return 96.0

        score_full = _fuzzy_score(full_a, full_b)
        score_cross = max(
            _fuzzy_score(full_a, base_b),
            _fuzzy_score(base_a, full_b),
        )
        # Only boost using base-vs-base when at least one lacks a subtitle
        if (base_a == full_a) or (base_b == full_b):
            score_base = _fuzzy_score(base_a, base_b) * 0.97
        else:
            score_base = 0.0

        return round(max(score_full, score_cross, score_base), 2)

    def is_match(
        self,
        title_a: str,
        title_b: str,
        *,
        language_a: str | None = None,
        language_b: str | None = None,
    ) -> bool:
        """Return True if two titles refer to the same movie within threshold."""
        if language_a and language_b:
            la = language_a.strip().lower()
            lb = language_b.strip().lower()
            # Distinct regional versions (e.g. Drishyam 3 Hindi vs Drishyam 3 Malayalam)
            if la != lb and "pan-india" not in {la, lb}:
                # Allow cross-source match only if titles are very close and one isn't explicitly dubbed mismatch
                pass
        return self.similarity(title_a, title_b) >= self.threshold

    def find_best_match(
        self,
        title: str,
        candidates: Iterable[str],
    ) -> tuple[str | None, float]:
        """Find best matching candidate title above threshold."""
        best_candidate: str | None = None
        best_score = 0.0
        for candidate in candidates:
            score = self.similarity(title, candidate)
            if score > best_score:
                best_score = score
                best_candidate = candidate
        if best_score >= self.threshold:
            return best_candidate, best_score
        return None, best_score

    @staticmethod
    def choose_canonical_slug(titles: Iterable[str], *, language: str | None = None) -> str:
        """Choose a deterministic canonical slug for a matched group of titles.

        If one title is the clean base form without a subtitle (e.g., 'Aadu 3' vs
        'Aadu 3: One Last Ride'), prefer the shorter clean base slug ('aadu-3') so
        the slug is identical regardless of source scrape order.
        """
        title_list = [t for t in titles if t and t.strip()]
        if not title_list:
            return "untitled-movie"

        base_candidates = sorted(
            title_list,
            key=lambda t: (len(normalize_title(t, strip_subtitle=False)), normalize_title(t)),
        )
        shortest = base_candidates[0]
        # Check if shortest title equals the stripped base of other titles in cluster
        norm_shortest = normalize_title(shortest, strip_subtitle=False)
        if all(
            normalize_title(other, strip_subtitle=True) == norm_shortest
            or normalize_title(other, strip_subtitle=False).startswith(norm_shortest)
            for other in title_list
        ):
            return canonical_slug(shortest, language=language, strip_subtitle=False)

        return canonical_slug(base_candidates[0], language=language, strip_subtitle=False)

    def resolve_slug(
        self,
        title: str,
        *,
        language: str | None = None,
        prefer_base_slug: bool = True,
    ) -> str:
        """Resolve a title against previously seen titles into one canonical movie_slug."""
        lang_key = (language or "").strip().lower() or None
        best_slug: str | None = None
        best_score = 0.0

        for slug, meta in self._registry.items():
            reg_lang = meta.get("language")
            # Keep distinct-language remakes separate (e.g., Drishyam 3 Hindi vs Malayalam)
            if lang_key and reg_lang and lang_key != reg_lang:
                if "pan-india" not in {lang_key, reg_lang}:
                    continue

            score = self.similarity(title, meta.get("title") or "")
            if score > best_score:
                best_score = score
                best_slug = slug

        if best_slug and best_score >= self.threshold:
            return best_slug

        new_slug = canonical_slug(
            title,
            language=None,
            strip_subtitle=prefer_base_slug and (":" in title or " - " in title),
        )
        # Disambiguate if another language already claimed this exact slug
        if new_slug in self._registry:
            existing_lang = self._registry[new_slug].get("language")
            if lang_key and existing_lang and lang_key != existing_lang and "pan-india" not in {lang_key, existing_lang}:
                new_slug = canonical_slug(title, language=language, strip_subtitle=False)

        self._registry[new_slug] = {"title": title, "language": lang_key}
        return new_slug
