"""Regex-based financial, percentage, date, and verdict normalizers for Indian box office strings."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

_NULL_TOKENS = {
    "",
    "-",
    "--",
    "---",
    "—",
    "–",
    "tba",
    "tbd",
    "n/a",
    "na",
    "nil",
    "none",
    "null",
    "awaited",
    "updating",
    "yet to be updated",
    "not available",
    "?",
}

_FOREIGN_CURRENCY_RE = re.compile(
    r"(?:\$|usd|€|eur|£|gbp|million|billion|\bmn\b|\bbn\b)",
    re.IGNORECASE,
)

# Strip parenthetical annotations such as "(4-day)", "(8-day)", "(est.)", "(approx)"
_PAREN_ANNOTATION_RE = re.compile(r"\([^)]*\)")
_NUMERIC_UNIT_RE = re.compile(
    r"(?P<sign>-)?\s*"
    r"(?P<num>\d+(?:,\d{2,3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
    r"\s*(?P<unit>crores?|crs?\.?|cr\.?|lakhs?|lacs?|l\.?|thousands?|k)?",
    re.IGNORECASE,
)

_PCT_RE = re.compile(r"(?P<sign>[+-])?\s*(?P<num>\d+(?:\.\d+)?)\s*%")

_VERDICT_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\ball[\s\-]*time[\s\-]*blockbuster\b", re.I), "All Time Blockbuster"),
    (re.compile(r"\bmega[\s\-]*blockbuster\b", re.I), "Blockbuster"),
    (re.compile(r"\bblockbuster\b", re.I), "Blockbuster"),
    (re.compile(r"\bsuper[\s\-]*duper[\s\-]*hit\b", re.I), "Super Hit"),
    (re.compile(r"\bsuper[\s\-]*hit\b", re.I), "Super Hit"),
    (re.compile(r"\bsemi[\s\-]*hit\b", re.I), "Semi-Hit"),
    (re.compile(r"\bhit\b", re.I), "Hit"),
    (re.compile(r"\bplus\b", re.I), "Plus"),
    (re.compile(r"\bbelow[\s\-]*average\b", re.I), "Below Average"),
    (re.compile(r"\baverage\b", re.I), "Average"),
    (re.compile(r"\bdisaster\b", re.I), "Disaster"),
    (re.compile(r"\bflop\b", re.I), "Flop"),
]

_DATE_FORMATS = (
    "%Y-%m-%d",
    "%d %b %Y",
    "%d %B %Y",
    "%d-%m-%Y",
    "%d/%m/%Y",
    "%b %d, %Y",
    "%B %d, %Y",
    "%d %b",
    "%d %B",
)

_DATE_CLEAN_RE = re.compile(
    r"(?:\b(?:mon|tue|wed|thu|fri|sat|sun)(?:day)?\b[,\s]*)",
    re.IGNORECASE,
)
_DATE_EXTRACT_RE = re.compile(
    r"(\d{4}-\d{2}-\d{2}|"
    r"\d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*(?:\s+\d{4})?|"
    r"\d{1,2}[/-]\d{1,2}[/-]\d{4})",
    re.IGNORECASE,
)


def parse_inr_to_crores(
    raw_value: str | int | float | None,
    *,
    default_unit: Literal["cr", "lakh", "rupee"] = "cr",
    allow_negative: bool = False,
) -> float | None:
    """Convert messy Indian box office currency strings to standardized Crores (float).

    Examples:
        "₹ 12.45 Cr"    -> 12.45
        "₹1,149.30 Cr"  -> 1149.3
        "45.2 Lakhs"    -> 0.452
        "₹45 L"         -> 0.45
        "1.20 Crore"    -> 1.2
        "1803.1*"       -> 1803.1
        "242 (4-day)"   -> 242.0
        "TBA" / "-"     -> None
    """
    if raw_value is None:
        return None

    if isinstance(raw_value, (int, float)):
        if isinstance(raw_value, float) and (raw_value != raw_value):  # NaN check
            return None
        val = float(raw_value)
        if not allow_negative and val < 0:
            return None
        return round(val, 4)

    text = str(raw_value).strip()
    if not text:
        return None

    # Reject obvious non-INR currencies such as "$500M" when no INR indicator exists
    if _FOREIGN_CURRENCY_RE.search(text) and not re.search(r"(?:₹|inr|rs\.?|cr|lakh)", text, re.I):
        return None

    # Remove parenthetical annotations like "(4-day)", "(est.)", "(approx)"
    cleaned = _PAREN_ANNOTATION_RE.sub(" ", text)
    # Remove currency prefixes, asterisks, tilde, plus signs, approx words
    cleaned = re.sub(r"(?:₹|rs\.?|inr|re\.?|approx\.?|est\.?|~|\*|\+)", " ", cleaned, flags=re.I)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    if cleaned.lower() in _NULL_TOKENS:
        return None

    # If text contains explicit non-numeric words with no digits, return None
    if not re.search(r"\d", cleaned):
        return None

    match = _NUMERIC_UNIT_RE.search(cleaned)
    if not match:
        return None

    num_str = match.group("num").replace(",", "")
    try:
        numeric_val = float(num_str)
    except ValueError:
        return None

    if match.group("sign") == "-":
        numeric_val = -numeric_val

    if not allow_negative and numeric_val < 0:
        return None

    unit = (match.group("unit") or "").lower().rstrip(".")
    if unit in {"cr", "crs", "crore", "crores"}:
        crores = numeric_val
    elif unit in {"l", "lakh", "lakhs", "lac", "lacs"}:
        crores = numeric_val / 100.0
    elif unit in {"k", "thousand", "thousands"}:
        crores = numeric_val / 10_000.0
    else:
        # No explicit unit present
        if default_unit == "lakh":
            crores = numeric_val / 100.0
        elif default_unit == "rupee":
            crores = numeric_val / 10_000_000.0
        else:
            # Heuristic guard: raw rupee figures >= 100,000 (e.g. "50,00,000") are not Crores
            if abs(numeric_val) >= 100_000:
                crores = numeric_val / 10_000_000.0
            else:
                crores = numeric_val

    return round(crores, 4)


def parse_percentage(raw_value: str | float | int | None) -> float | None:
    """Parse percentage strings like 'down ▼ 12.4%', 'up ▲ 45.3%', '+10.2%' into floats."""
    if raw_value is None:
        return None
    if isinstance(raw_value, (int, float)):
        return round(float(raw_value), 2)

    text = str(raw_value).strip()
    if not text or text.lower() in _NULL_TOKENS:
        return None

    match = _PCT_RE.search(text)
    if not match:
        return None

    val = float(match.group("num"))
    sign = match.group("sign")
    lowered = text.lower()

    if sign == "-" or "down" in lowered or "▼" in text or "drop" in lowered:
        val = -abs(val)
    elif sign == "+" or "up" in lowered or "▲" in text:
        val = abs(val)

    return round(val, 2)


def parse_date_flexible(
    raw_value: str | None,
    *,
    default_year: int | None = None,
) -> str | None:
    """Normalize diverse date strings into ISO 'YYYY-MM-DD' format."""
    if not raw_value:
        return None

    text = _DATE_CLEAN_RE.sub(" ", str(raw_value)).strip()
    text = re.sub(r"\bsept\b", "Sep", text, flags=re.I)
    match = _DATE_EXTRACT_RE.search(text)
    if not match:
        return None

    candidate = re.sub(r"\s+", " ", match.group(1)).strip()
    year = default_year or datetime.now().year
    for fmt in _DATE_FORMATS:
        try:
            if "%Y" not in fmt:
                dt = datetime.strptime(f"{candidate} {year}", f"{fmt} %Y")
            else:
                dt = datetime.strptime(candidate, fmt)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def normalize_verdict(raw_value: str | None) -> str | None:
    """Normalize box office verdicts into consistent canonical labels."""
    if not raw_value:
        return None
    cleaned = re.sub(r"\s+", " ", str(raw_value)).strip()
    if not cleaned or cleaned.lower() in _NULL_TOKENS:
        return None

    for pattern, label in _VERDICT_PATTERNS:
        if pattern.search(cleaned):
            return label

    return cleaned.title() if len(cleaned) <= 40 else None
