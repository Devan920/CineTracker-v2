"""Structured colorized console logging, rotating file logs, and JSON run reports."""

from __future__ import annotations

import json
import logging
import sys
import uuid
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from colorama import Fore, Style, init as colorama_init
from pydantic import BaseModel, Field

colorama_init(autoreset=True)


class _ColorFormatter(logging.Formatter):
    """Colorized terminal formatter safe on Windows consoles."""

    _LEVEL_COLORS = {
        logging.DEBUG: Fore.CYAN,
        logging.INFO: Fore.GREEN,
        logging.WARNING: Fore.YELLOW,
        logging.ERROR: Fore.RED,
        logging.CRITICAL: Fore.MAGENTA + Style.BRIGHT,
    }

    def format(self, record: logging.LogRecord) -> str:
        color = self._LEVEL_COLORS.get(record.levelno, "")
        reset = Style.RESET_ALL if color else ""
        timestamp = self.formatTime(record, "%H:%M:%S")
        level = f"{color}{record.levelname:<8}{reset}"
        name = f"{Fore.BLUE}{record.name}{reset}"
        msg = record.getMessage()
        formatted = f"[{timestamp}] {level} [{name}] {msg}"
        if record.exc_info:
            formatted += "\n" + self.formatException(record.exc_info)
        return formatted


class RunReport(BaseModel):
    """Structured telemetry written to logs/last_run_report.json after every run."""

    run_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    started_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    finished_at: str | None = None
    duration_sec: float = 0.0
    status: str = "running"
    cli_args: dict[str, Any] = Field(default_factory=dict)
    sources: dict[str, dict[str, int]] = Field(default_factory=dict)
    reconciliation: dict[str, Any] = Field(
        default_factory=lambda: {
            "total_movies": 0,
            "multi_source_matches": 0,
            "variance_anomalies": 0,
            "flagged_slugs": [],
        }
    )
    enrichment: dict[str, int] = Field(
        default_factory=lambda: {
            "tmdb_matched": 0,
            "tmdb_cache_hits": 0,
            "tmdb_api_calls": 0,
            "tmdb_skipped_or_missed": 0,
        }
    )
    database: dict[str, int] = Field(
        default_factory=lambda: {
            "upserted": 0,
            "manual_override_locked": 0,
            "daily_rows_synced": 0,
            "skipped_dry_run": 0,
            "errors": 0,
        }
    )
    errors: list[dict[str, Any]] = Field(default_factory=list)

    def add_error(
        self,
        *,
        stage: str,
        message: str,
        source: str | None = None,
        url: str | None = None,
        movie_title: str | None = None,
        exception_type: str | None = None,
    ) -> None:
        self.errors.append(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "stage": stage,
                "source": source,
                "movie_title": movie_title,
                "url": url,
                "exception_type": exception_type,
                "message": message,
            }
        )

    def finalize(self, *, status: str | None = None) -> None:
        finished = datetime.now(timezone.utc)
        self.finished_at = finished.isoformat()
        started = datetime.fromisoformat(self.started_at)
        self.duration_sec = round((finished - started).total_seconds(), 3)
        if status is not None:
            self.status = status
        elif self.errors and self.reconciliation.get("total_movies", 0) > 0:
            self.status = "partial_success"
        elif self.errors:
            self.status = "failed"
        else:
            self.status = "success"


def setup_logging(
    *,
    log_file: Path,
    level: str = "INFO",
) -> logging.Logger:
    """Configure root 'cinetracker' logger with colorized console + rotating file logs."""
    log_file.parent.mkdir(parents=True, exist_ok=True)
    numeric_level = getattr(logging, level.upper(), logging.INFO)

    root_logger = logging.getLogger("cinetracker")
    root_logger.setLevel(numeric_level)
    root_logger.propagate = False

    # Avoid duplicate handlers across repeated CLI/test invocations
    for handler in list(root_logger.handlers):
        handler.close()
        root_logger.removeHandler(handler)

    # Ensure UTF-8 output on Windows consoles when possible
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(numeric_level)
    console_handler.setFormatter(_ColorFormatter())

    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S%z",
        )
    )

    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)
    return root_logger


def get_logger(name: str) -> logging.Logger:
    """Return a namespaced child logger under 'cinetracker'."""
    if name.startswith("cinetracker"):
        return logging.getLogger(name)
    return logging.getLogger(f"cinetracker.{name}")


def write_run_report(report: RunReport, path: Path) -> Path:
    """Atomically write RunReport JSON summary to disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".json.tmp")
    tmp_path.write_text(
        json.dumps(report.model_dump(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    tmp_path.replace(path)
    return path
