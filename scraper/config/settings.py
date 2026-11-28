"""Centralized configuration and environment validation for the box office engine."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Load .env once if present so CLI and modules see consistent environment state.
load_dotenv(PROJECT_ROOT / ".env", override=False)


class ConfigurationError(ValueError):
    """Raised when required environment variables or config files are invalid."""


class SourceConfig(BaseModel):
    """Schema validation for an individual scraper definition in sources.yaml."""

    enabled: bool = True
    base_url: str
    priority_weight: float = 1.0
    categories: dict[str, list[str]] = Field(default_factory=dict)
    selectors: dict[str, Any] = Field(default_factory=dict)


class XHandleConfig(BaseModel):
    """Configuration for a single X (Twitter) box office tracker handle."""

    language: str
    tags: list[str] = Field(default_factory=list)


class XTrackersConfig(BaseModel):
    """Schema validation for the x_trackers section in sources.yaml."""

    enabled: bool = True
    priority_weight: float = 0.65
    max_age_hours: int = 48
    syndication_url_template: str = (
        "https://syndication.twitter.com/srv/timeline-profile/screen-name/{handle}"
    )
    keywords: list[str] = Field(default_factory=list)
    handles: dict[str, XHandleConfig] = Field(default_factory=dict)


class SourcesFileConfig(BaseModel):
    """Validated wrapper around config/sources.yaml."""

    version: int = 1
    supported_languages: list[str] = Field(default_factory=list)
    sources: dict[str, SourceConfig] = Field(default_factory=dict)
    x_trackers: XTrackersConfig = Field(default_factory=XTrackersConfig)


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables and defaults."""

    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    # Credentials
    supabase_url: str | None = Field(default=None, alias="SUPABASE_URL")
    supabase_key: str | None = Field(default=None, alias="SUPABASE_KEY")
    tmdb_api_key: str | None = Field(default=None, alias="TMDB_API_KEY")

    # Optional X (Twitter) Authenticated Cookies & Fallback Mirrors
    x_auth_token: str | None = Field(default=None, alias="X_AUTH_TOKEN")
    x_ct0: str | None = Field(default=None, alias="X_CT0")
    x_nitter_instances_raw: str | None = Field(default=None, alias="X_NITTER_INSTANCES")

    # Retry & Resilience thresholds
    retry_max_attempts: int = Field(default=3, alias="SCRAPE_MAX_RETRIES", ge=1, le=10)
    retry_base_delay_sec: float = Field(default=2.0, ge=0.2, le=30.0)
    retry_max_delay_sec: float = Field(default=30.0, ge=1.0, le=120.0)
    request_timeout_sec: int = Field(default=25, ge=5, le=120)
    playwright_timeout_ms: int = Field(default=30000, ge=5000, le=120000)

    # Rate-limiting jitter (1.5s - 4.0s required between page requests)
    min_delay_sec: float = Field(default=1.5, alias="SCRAPE_MIN_DELAY_SEC", ge=0.0, le=30.0)
    max_delay_sec: float = Field(default=4.0, alias="SCRAPE_MAX_DELAY_SEC", ge=0.0, le=60.0)

    # Reconciliation & Fuzzy Matching
    variance_threshold: float = Field(
        default=0.25,
        alias="SCRAPE_VARIANCE_THRESHOLD",
        gt=0.0,
        le=1.0,
    )
    title_match_threshold: float = Field(default=84.0, ge=50.0, le=100.0)
    source_weights: dict[str, float] = Field(
        default_factory=lambda: {
            "sacnilk": 1.0,
            "koimoi": 0.75,
            "x": 0.65,
        }
    )

    # Paths & Logging
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    base_dir: Path = PROJECT_ROOT
    sources_config_path: Path = PROJECT_ROOT / "config" / "sources.yaml"
    tmdb_cache_path: Path = PROJECT_ROOT / "cache" / "tmdb_cache.json"
    log_file_path: Path = PROJECT_ROOT / "logs" / "scraper.log"
    report_file_path: Path = PROJECT_ROOT / "logs" / "last_run_report.json"

    # Pipeline batch safety
    supabase_batch_size: int = Field(default=50, ge=1, le=500)
    tmdb_cache_ttl_hours: int = Field(default=72, ge=1, le=720)

    @field_validator(
        "supabase_url",
        "supabase_key",
        "tmdb_api_key",
        "x_auth_token",
        "x_ct0",
        "x_nitter_instances_raw",
        mode="before",
    )
    @classmethod
    def _strip_blank(cls, value: Any) -> str | None:
        if value is None:
            return None
        cleaned = str(value).strip()
        return cleaned or None

    @property
    def x_nitter_instances(self) -> list[str]:
        """Parse comma-separated X_NITTER_INSTANCES fallback mirrors."""
        if not self.x_nitter_instances_raw:
            return []
        return [
            item.strip().rstrip("/")
            for item in self.x_nitter_instances_raw.split(",")
            if item.strip()
        ]

    @field_validator("max_delay_sec")
    @classmethod
    def _validate_delay_range(cls, max_delay: float, info: Any) -> float:
        min_delay = info.data.get("min_delay_sec", 1.5)
        if max_delay < min_delay:
            raise ValueError(
                f"SCRAPE_MAX_DELAY_SEC ({max_delay}) cannot be less than "
                f"SCRAPE_MIN_DELAY_SEC ({min_delay})."
            )
        return max_delay

    @field_validator("log_level")
    @classmethod
    def _normalize_log_level(cls, value: str) -> str:
        normalized = value.strip().upper()
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if normalized not in allowed:
            raise ValueError(f"LOG_LEVEL must be one of {sorted(allowed)}, got '{value}'.")
        return normalized

    @staticmethod
    def _is_placeholder(value: str | None) -> bool:
        if not value:
            return True
        lowered = value.lower()
        return any(
            token in lowered
            for token in (
                "your-project-id",
                "your-supabase",
                "your-tmdb",
                "paste_your",
                "changeme",
                "<your",
            )
        )

    def validate_environment(
        self,
        *,
        require_supabase: bool = True,
        require_tmdb: bool = False,
    ) -> None:
        """Strictly validate required credentials and configuration files.

        Raises ConfigurationError with actionable diagnostics when required
        environment variables are missing or malformed.
        """
        errors: list[str] = []

        if require_supabase:
            if self._is_placeholder(self.supabase_url):
                errors.append("SUPABASE_URL is missing or still set to placeholder value.")
            else:
                parsed = urlparse(self.supabase_url or "")
                if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                    errors.append(
                        f"SUPABASE_URL '{self.supabase_url}' is not a valid HTTP(S) URL."
                    )

            if self._is_placeholder(self.supabase_key):
                errors.append("SUPABASE_KEY is missing or still set to placeholder value.")

        if require_tmdb and self._is_placeholder(self.tmdb_api_key):
            errors.append("TMDB_API_KEY is missing or still set to placeholder value.")

        if not self.sources_config_path.exists():
            errors.append(f"Missing sources configuration file: {self.sources_config_path}")

        if errors:
            raise ConfigurationError("Invalid engine configuration:\n - " + "\n - ".join(errors))

    def has_valid_tmdb_key(self) -> bool:
        """Return True if a non-placeholder TMDB API key is configured."""
        return not self._is_placeholder(self.tmdb_api_key)

    def ensure_runtime_directories(self) -> None:
        """Ensure cache and log directories exist before pipeline execution."""
        self.tmdb_cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.log_file_path.parent.mkdir(parents=True, exist_ok=True)
        self.report_file_path.parent.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached singleton Settings instance."""
    return Settings()


def load_sources_config(path: Path | None = None) -> SourcesFileConfig:
    """Load and validate config/sources.yaml."""
    target = path or get_settings().sources_config_path
    if not target.exists():
        raise ConfigurationError(f"Sources configuration file not found at {target}")

    try:
        raw = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
        return SourcesFileConfig.model_validate(raw)
    except Exception as exc:
        raise ConfigurationError(f"Failed to load sources config '{target}': {exc}") from exc


def refresh_settings_from_env() -> Settings:
    """Clear settings cache (useful in tests when env vars change)."""
    get_settings.cache_clear()
    # Re-read process environment without requiring .env overwrite
    os.environ.setdefault("PYTHONUTF8", "1")
    return get_settings()
