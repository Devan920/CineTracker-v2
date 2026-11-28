"""Production FastAPI server exposing scraper triggers, live telemetry, and hardened cached APIs."""

from __future__ import annotations

import importlib.util
import json
import os
import secrets
import sys
import threading
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator, Literal

from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv
from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from supabase import Client, create_client

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRAPER_DIR = REPO_ROOT / "scraper"
API_DIR = REPO_ROOT / "api"

# Ensure /scraper modules resolve cleanly whether launched from repo root, /api, or /scraper
if str(SCRAPER_DIR) not in sys.path:
    sys.path.insert(0, str(SCRAPER_DIR))

# Load environment variables without overwriting explicit process env
load_dotenv(SCRAPER_DIR / ".env", override=False)
load_dotenv(API_DIR / ".env", override=False)

from config.settings import get_settings, refresh_settings_from_env  # noqa: E402
from enrichment.tmdb_client import TMDBClient  # noqa: E402
from utils.whitelabel import (  # noqa: E402
    PUBLIC_MOVIE_COLUMNS,
    sanitize_public_movie,
    sanitize_run_report,
    sanitize_source_name,
    sanitize_whitelabel_text,
)


def _load_scraper_main() -> Any:
    """Import scraper/main.py without colliding with api/main.py when uvicorn runs as main:app."""
    mod_name = "_cinetracker_scraper_main"
    if mod_name in sys.modules:
        return sys.modules[mod_name]
    spec = importlib.util.spec_from_file_location(mod_name, SCRAPER_DIR / "main.py")
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load scraper main module at {SCRAPER_DIR / 'main.py'}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    spec.loader.exec_module(module)
    return module


_scraper_main = _load_scraper_main()
build_arg_parser = _scraper_main.build_arg_parser
run_pipeline = _scraper_main.run_pipeline

_SERVER_START_TIME = time.monotonic()
_bearer_scheme = HTTPBearer(auto_error=False)
_scrape_execution_lock = threading.Lock()
_state_lock = threading.Lock()
_movies_cache_lock = threading.Lock()
_scheduler_lock = threading.Lock()

# Canonical source aliases accepted from UI/API while mapping cleanly to internal scrapers
_INTERNAL_SOURCE_MAP: dict[str, str] = {
    "all": "all",
    "cinetracker_bo": "sacnilk",
    "sacnilk": "sacnilk",
    "cinetracker_trade": "koimoi",
    "koimoi": "koimoi",
    "cinetracker_pulse": "x",
    "x": "x",
}

_SAFE_SELECT_FULL = ",".join(PUBLIC_MOVIE_COLUMNS)
_SAFE_SELECT_MINIMAL = (
    "id,movie_slug,title,language,original_language,release_date,tmdb_id,"
    "poster_url,backdrop_url,cast_summary,budget_cr,india_net_cr,india_gross_cr,"
    "overseas_cr,worldwide_gross_cr,verdict,day_count,daily_breakdown,"
    "primary_source,variance_flag,manual_override,last_scraped_at,created_at,updated_at"
)


class _SlidingWindowRateLimiter:
    """Thread-safe in-memory per-IP sliding-window rate limiter."""

    def __init__(self, *, max_requests: int, window_seconds: int = 60) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str) -> tuple[bool, int, int]:
        """Record a hit if permitted; return (allowed, remaining, retry_after_sec)."""
        now = time.monotonic()
        cutoff = now - self.window_seconds
        with self._lock:
            bucket = self._hits[key]
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= self.max_requests:
                retry_after = max(1, int(bucket[0] + self.window_seconds - now) + 1)
                return False, 0, retry_after
            bucket.append(now)
            remaining = max(0, self.max_requests - len(bucket))
            return True, remaining, 0

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


_public_rate_limiter = _SlidingWindowRateLimiter(max_requests=120, window_seconds=60)
_admin_rate_limiter = _SlidingWindowRateLimiter(max_requests=10, window_seconds=60)


def _extract_client_ip(request: Request) -> str:
    forwarded_for = (request.headers.get("x-forwarded-for") or "").strip()
    if forwarded_for:
        first_hop = forwarded_for.split(",")[0].strip()
        if first_hop:
            return first_hop
    real_ip = (request.headers.get("x-real-ip") or "").strip()
    if real_ip:
        return real_ip
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def _enforce_rate_limit(
    limiter: _SlidingWindowRateLimiter,
    request: Request,
    response: Response,
    bucket_label: str,
) -> None:
    ip = _extract_client_ip(request)
    allowed, remaining, retry_after = limiter.check(f"{bucket_label}:{ip}")
    response.headers["X-RateLimit-Limit"] = str(limiter.max_requests)
    response.headers["X-RateLimit-Remaining"] = str(remaining)
    response.headers["X-RateLimit-Window"] = f"{limiter.window_seconds}s"
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded ({limiter.max_requests} req/{limiter.window_seconds}s). Retry in {retry_after}s.",
            headers={
                "Retry-After": str(retry_after),
                "X-RateLimit-Limit": str(limiter.max_requests),
                "X-RateLimit-Remaining": "0",
            },
        )


def rate_limit_public(request: Request, response: Response) -> None:
    _enforce_rate_limit(_public_rate_limiter, request, response, "public")


def rate_limit_admin(request: Request, response: Response) -> None:
    _enforce_rate_limit(_admin_rate_limiter, request, response, "admin")


class ScrapeTriggerRequest(BaseModel):
    """Request payload for POST /api/scrape/trigger."""

    source: Literal[
        "all",
        "cinetracker_bo",
        "cinetracker_trade",
        "cinetracker_pulse",
        "sacnilk",
        "koimoi",
        "x",
    ] = "all"
    language: Literal[
        "all",
        "malayalam",
        "tamil",
        "hindi",
        "telugu",
        "kannada",
        "pan-india",
    ] = "all"
    limit: int | None = Field(default=None, ge=1, le=500)
    dry_run: bool = False


class MovieAdminPatchRequest(BaseModel):
    """Partial movie update payload for PATCH /api/movies/{movie_slug}."""

    india_net_cr: float | None = Field(default=None, ge=0.0)
    india_gross_cr: float | None = Field(default=None, ge=0.0)
    overseas_cr: float | None = Field(default=None, ge=0.0)
    worldwide_gross_cr: float | None = Field(default=None, ge=0.0)
    budget_cr: float | None = Field(default=None, ge=0.0)
    verdict: str | None = Field(default=None, max_length=64)
    variance_flag: bool | None = None
    manual_override: bool | None = None
    daily_breakdown: list[dict[str, Any]] | None = None


class ScrapeStatusResponse(BaseModel):
    """Live telemetry returned by GET /api/scrape/status."""

    status: Literal["idle", "running", "completed", "failed"]
    started_at: str | None = None
    finished_at: str | None = None
    duration_sec: float | None = None
    source: str | None = None
    language: str | None = None
    records_synced: int = 0
    movies_reconciled: int = 0
    error_message: str | None = None
    last_run_report: dict[str, Any] | None = None
    recent_logs: list[str] = Field(default_factory=list)


_job_state: dict[str, Any] = {
    "status": "idle",
    "started_at": None,
    "finished_at": None,
    "duration_sec": None,
    "source": None,
    "language": None,
    "records_synced": 0,
    "movies_reconciled": 0,
    "error_message": None,
}

_scheduler_state: dict[str, Any] = {
    "last_heartbeat_at": None,
    "heartbeat_count": 0,
}
_scheduler: BackgroundScheduler | None = None

# In-memory TTL cache for GET /api/movies and GET /api/movies/{movie_slug}
_movies_cache: dict[str, tuple[float, Any]] = {}
_MOVIES_CACHE_TTL_SEC = 60.0


def _record_scheduler_heartbeat() -> None:
    with _scheduler_lock:
        _scheduler_state["last_heartbeat_at"] = datetime.now(timezone.utc).isoformat()
        _scheduler_state["heartbeat_count"] = int(_scheduler_state.get("heartbeat_count") or 0) + 1


def _run_scheduled_scrape_tick() -> None:
    """Optional APScheduler background scrape job when ENABLE_INTERNAL_SCHEDULER=true."""
    if not _scrape_execution_lock.acquire(blocking=False):
        return
    try:
        payload = ScrapeTriggerRequest(source="all", language="all")
        with _state_lock:
            _job_state.update(
                {
                    "status": "running",
                    "started_at": datetime.now(timezone.utc).isoformat(),
                    "finished_at": None,
                    "duration_sec": None,
                    "source": "all",
                    "language": "all",
                    "records_synced": 0,
                    "movies_reconciled": 0,
                    "error_message": None,
                }
            )
        _execute_scrape_job(payload)
    except Exception:
        if _scrape_execution_lock.locked():
            _scrape_execution_lock.release()


def _ensure_scheduler_started() -> BackgroundScheduler:
    """Start APScheduler BackgroundScheduler idempotently for heartbeat & optional cron."""
    global _scheduler
    with _scheduler_lock:
        if _scheduler is not None and _scheduler.running:
            return _scheduler

        scheduler = BackgroundScheduler(timezone="UTC")
        scheduler.add_job(
            _record_scheduler_heartbeat,
            trigger="interval",
            seconds=30,
            id="cinetracker_heartbeat",
            replace_existing=True,
            max_instances=1,
        )

        if os.getenv("ENABLE_INTERNAL_SCHEDULER", "false").strip().lower() in {
            "1",
            "true",
            "yes",
        }:
            interval_min = max(15, int(os.getenv("SCRAPE_INTERVAL_MINUTES", "60") or "60"))
            scheduler.add_job(
                _run_scheduled_scrape_tick,
                trigger="interval",
                minutes=interval_min,
                id="cinetracker_scheduled_scrape",
                replace_existing=True,
                max_instances=1,
            )

        scheduler.start()
        _scheduler = scheduler

    _record_scheduler_heartbeat()
    return _scheduler


def _shutdown_scheduler() -> None:
    global _scheduler
    with _scheduler_lock:
        if _scheduler is not None:
            try:
                _scheduler.shutdown(wait=False)
            except Exception:
                pass
            _scheduler = None


def _scheduler_health_snapshot() -> dict[str, Any]:
    scheduler = _ensure_scheduler_started()
    with _scheduler_lock:
        last_hb = _scheduler_state.get("last_heartbeat_at")
        hb_count = int(_scheduler_state.get("heartbeat_count") or 0)

    age_sec: float | None = None
    if last_hb:
        try:
            hb_dt = datetime.fromisoformat(str(last_hb))
            age_sec = round(max(0.0, (datetime.now(timezone.utc) - hb_dt).total_seconds()), 2)
        except Exception:
            age_sec = None

    healthy = bool(scheduler.running and last_hb and (age_sec is None or age_sec <= 120.0))
    return {
        "running": bool(scheduler.running),
        "healthy": healthy,
        "last_heartbeat_at": last_hb,
        "heartbeat_age_sec": age_sec,
        "heartbeat_count": hb_count,
        "jobs": len(scheduler.get_jobs()),
    }


def _get_cors_origins() -> list[str]:
    origins = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:4173",
    ]
    extra = os.getenv("CORS_ORIGINS", "")
    for item in extra.split(","):
        cleaned = item.strip().rstrip("/")
        if cleaned and cleaned != "*" and cleaned not in origins:
            origins.append(cleaned)
    return origins


def _get_supabase_client() -> Client:
    settings = get_settings()
    if settings._is_placeholder(settings.supabase_url) or settings._is_placeholder(
        settings.supabase_key
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Supabase credentials are not configured on the API server.",
        )
    return create_client(settings.supabase_url or "", settings.supabase_key or "")


def _read_last_run_report() -> dict[str, Any] | None:
    report_path = get_settings().report_file_path
    if not report_path.exists():
        return None
    try:
        data = json.loads(report_path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _read_recent_logs(max_lines: int = 40) -> list[str]:
    log_path = get_settings().log_file_path
    if not log_path.exists():
        return []
    try:
        with log_path.open("r", encoding="utf-8", errors="replace") as fp:
            return [
                sanitize_whitelabel_text(line.rstrip("\r\n"))
                for line in deque(fp, maxlen=max_lines)
            ]
    except Exception:
        return []


def verify_admin_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> str:
    """Validate Bearer token against ADMIN_API_SECRET or Supabase Auth JWT."""
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization Bearer token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials.strip()
    admin_secret = (os.getenv("ADMIN_API_SECRET") or "").strip()
    if admin_secret and secrets.compare_digest(token, admin_secret):
        return "admin_secret"

    # Verify Supabase session access_token via Supabase Auth
    settings = get_settings()
    if not settings._is_placeholder(settings.supabase_url) and not settings._is_placeholder(
        settings.supabase_key
    ):
        try:
            sb = create_client(settings.supabase_url or "", settings.supabase_key or "")
            user_resp = sb.auth.get_user(token)
            user_obj = getattr(user_resp, "user", None)
            if user_obj and getattr(user_obj, "id", None):
                return str(getattr(user_obj, "email", None) or user_obj.id)
        except Exception:
            pass

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired admin Bearer token.",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _invalidate_movies_cache() -> int:
    with _movies_cache_lock:
        cleared = len(_movies_cache)
        _movies_cache.clear()
        return cleared


def _is_missing_optional_column_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return ("42703" in msg or "pgrst204" in msg or "does not exist" in msg or "schema cache" in msg) and any(
        col in msg for col in ("trailer_youtube_id", "director", "synopsis")
    )


def _lookup_cached_trailer_id(row: dict[str, Any]) -> str | None:
    """Resolve cached YouTube trailer ID from local tmdb_cache.json with zero network I/O."""
    existing = row.get("trailer_youtube_id")
    if existing:
        return str(existing)
    cache_path = get_settings().tmdb_cache_path
    if not cache_path.exists():
        return None
    try:
        cache_data = json.loads(cache_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    title = str(row.get("title") or "").strip()
    if not title:
        return None
    rel_date = str(row.get("release_date") or "")
    rel_year = int(rel_date[:4]) if len(rel_date) >= 4 and rel_date[:4].isdigit() else None
    lang = str(row.get("language") or "")
    key = f"yt|{TMDBClient._build_cache_key(title, rel_year, lang)}"
    entry = cache_data.get(key)
    if isinstance(entry, dict) and entry.get("trailer_youtube_id"):
        return str(entry["trailer_youtube_id"])
    return None


def _enrich_trailer_from_cache(row: dict[str, Any]) -> dict[str, Any]:
    if not row.get("trailer_youtube_id"):
        cached_vid = _lookup_cached_trailer_id(row)
        if cached_vid:
            row["trailer_youtube_id"] = cached_vid
    return row


def _execute_scrape_job(payload: ScrapeTriggerRequest) -> None:
    """Background worker executing the /scraper pipeline under an exclusive lock."""
    started = datetime.now(timezone.utc)
    start_mono = time.monotonic()
    internal_source = _INTERNAL_SOURCE_MAP.get(payload.source, "all")

    try:
        settings = refresh_settings_from_env()
        argv: list[str] = [
            "--source",
            internal_source,
            "--lang",
            payload.language,
        ]
        if payload.limit is not None:
            argv.extend(["--limit", str(payload.limit)])
        if payload.dry_run:
            argv.append("--dry-run")

        parser = build_arg_parser()
        args = parser.parse_args(argv)
        exit_code = run_pipeline(args, settings=settings)

        report = _read_last_run_report() or {}
        recon_total = int((report.get("reconciliation") or {}).get("total_movies") or 0)
        db_section = report.get("database") or {}
        synced = int(db_section.get("upserted") or 0)
        if payload.dry_run:
            synced = int(db_section.get("skipped_dry_run") or recon_total)

        errors = report.get("errors") or []
        final_status = "failed" if exit_code != 0 else "completed"
        err_msg = None
        if final_status == "failed" and errors:
            err_msg = sanitize_whitelabel_text(str(errors[0].get("message") or "Scraper run failed."))

        with _state_lock:
            _job_state.update(
                {
                    "status": final_status,
                    "started_at": started.isoformat(),
                    "finished_at": datetime.now(timezone.utc).isoformat(),
                    "duration_sec": round(time.monotonic() - start_mono, 2),
                    "records_synced": synced,
                    "movies_reconciled": recon_total,
                    "error_message": err_msg,
                }
            )
        _invalidate_movies_cache()
    except Exception as exc:
        with _state_lock:
            _job_state.update(
                {
                    "status": "failed",
                    "started_at": started.isoformat(),
                    "finished_at": datetime.now(timezone.utc).isoformat(),
                    "duration_sec": round(time.monotonic() - start_mono, 2),
                    "error_message": sanitize_whitelabel_text(str(exc)),
                }
            )
    finally:
        if _scrape_execution_lock.locked():
            _scrape_execution_lock.release()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    _ensure_scheduler_started()
    try:
        yield
    finally:
        _shutdown_scheduler()


app = FastAPI(
    title="CineTracker Box Office API",
    version="3.0.0",
    description="Hardened FastAPI orchestration & cached query backend for CineTracker Box Office Engine.",
    lifespan=lifespan,
)

app.add_middleware(GZipMiddleware, minimum_size=500)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_get_cors_origins(),
    allow_origin_regex=r"https://.*\.vercel\.app$",
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept"],
)


@app.middleware("http")
async def add_security_headers(request: Request, call_next: Any) -> Response:
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault(
        "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
    )
    response.headers.setdefault("X-XSS-Protection", "0")
    if request.url.path.startswith("/api/scrape") or request.url.path == "/health":
        response.headers.setdefault("Cache-Control", "no-store")
    return response


@app.get("/health")
def health_check() -> JSONResponse:
    """Health check verifying live Supabase connectivity and APScheduler heartbeat."""
    with _state_lock:
        current_state = _job_state["status"]
        state_last_run = _job_state.get("finished_at") or _job_state.get("started_at")

    report = _read_last_run_report() or {}
    last_run_at = state_last_run or report.get("finished_at") or report.get("started_at")
    scraper_status = "running" if current_state == "running" else "idle"

    scheduler_metrics = _scheduler_health_snapshot()

    db_connected = False
    db_latency_ms: float | None = None
    db_error: str | None = None
    t0 = time.monotonic()
    try:
        sb = _get_supabase_client()
        sb.table("movies").select("id").limit(1).execute()
        db_connected = True
        db_latency_ms = round((time.monotonic() - t0) * 1000.0, 2)
    except HTTPException as exc:
        db_error = str(exc.detail)
    except Exception as exc:
        db_error = sanitize_whitelabel_text(str(exc))

    with _movies_cache_lock:
        cache_entries = len(_movies_cache)

    healthy = db_connected and scheduler_metrics["healthy"]
    http_status = status.HTTP_200_OK if healthy else status.HTTP_503_SERVICE_UNAVAILABLE

    payload: dict[str, Any] = {
        "status": "ok" if healthy else "degraded",
        "uptime_sec": round(time.monotonic() - _SERVER_START_TIME, 2),
        "scraper_status": scraper_status,
        "last_run_at": last_run_at,
        "database": {
            "connected": db_connected,
            "latency_ms": db_latency_ms,
            **({"error": db_error} if db_error else {}),
        },
        "scheduler": scheduler_metrics,
        "cache": {
            "entries": cache_entries,
            "ttl_sec": int(_MOVIES_CACHE_TTL_SEC),
        },
    }
    return JSONResponse(status_code=http_status, content=payload)


@app.post(
    "/api/scrape/trigger",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(rate_limit_admin)],
)
def trigger_scrape(
    payload: ScrapeTriggerRequest,
    background_tasks: BackgroundTasks,
    admin_identity: str = Depends(verify_admin_token),
) -> dict[str, Any]:
    """Trigger an asynchronous box office scrape & sync job (single-flight locked)."""
    if not _scrape_execution_lock.acquire(blocking=False):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A scrape job is already running. Wait for completion before triggering another.",
        )

    display_source = (
        "all" if payload.source == "all" else sanitize_source_name(payload.source)
    )
    now_iso = datetime.now(timezone.utc).isoformat()
    try:
        with _state_lock:
            _job_state.update(
                {
                    "status": "running",
                    "started_at": now_iso,
                    "finished_at": None,
                    "duration_sec": None,
                    "source": display_source,
                    "language": payload.language,
                    "records_synced": 0,
                    "movies_reconciled": 0,
                    "error_message": None,
                }
            )

        background_tasks.add_task(_execute_scrape_job, payload)
    except Exception:
        if _scrape_execution_lock.locked():
            _scrape_execution_lock.release()
        raise
    return {
        "accepted": True,
        "triggered_by": admin_identity,
        "status": "running",
        "started_at": now_iso,
        "source": display_source,
        "language": payload.language,
        "limit": payload.limit,
    }


@app.get("/api/scrape/status", response_model=ScrapeStatusResponse)
def get_scrape_status(
    _admin_identity: str = Depends(verify_admin_token),
) -> ScrapeStatusResponse:
    """Return white-labeled scraper telemetry, report summary, and sanitized log lines."""
    report = sanitize_run_report(_read_last_run_report())
    logs = _read_recent_logs(max_lines=40)

    with _state_lock:
        snapshot = dict(_job_state)

    if snapshot["status"] == "idle" and report:
        db_sec = report.get("database") or {}
        recon_sec = report.get("reconciliation") or {}
        snapshot["finished_at"] = report.get("finished_at")
        snapshot["started_at"] = report.get("started_at")
        snapshot["duration_sec"] = report.get("duration_sec")
        snapshot["records_synced"] = int(
            db_sec.get("upserted") or db_sec.get("skipped_dry_run") or 0
        )
        snapshot["movies_reconciled"] = int(recon_sec.get("total_movies") or 0)

    src_val = snapshot.get("source")
    clean_source = (
        "all"
        if src_val in (None, "all")
        else sanitize_source_name(str(src_val))
    )

    return ScrapeStatusResponse(
        status=snapshot["status"],
        started_at=snapshot["started_at"],
        finished_at=snapshot["finished_at"],
        duration_sec=snapshot["duration_sec"],
        source=clean_source if src_val else None,
        language=snapshot["language"],
        records_synced=snapshot["records_synced"],
        movies_reconciled=snapshot["movies_reconciled"],
        error_message=(
            sanitize_whitelabel_text(snapshot["error_message"])
            if snapshot["error_message"]
            else None
        ),
        last_run_report=report,
        recent_logs=logs,
    )


@app.post("/api/cache/invalidate", dependencies=[Depends(rate_limit_admin)])
def invalidate_cache(
    admin_identity: str = Depends(verify_admin_token),
) -> dict[str, Any]:
    """Invalidate the 60s in-memory /api/movies cache immediately after admin edits."""
    cleared = _invalidate_movies_cache()
    return {
        "invalidated": True,
        "cleared_entries": cleared,
        "triggered_by": admin_identity,
    }


@app.patch("/api/movies/{movie_slug}", dependencies=[Depends(rate_limit_admin)])
def admin_patch_movie(
    movie_slug: str,
    payload: MovieAdminPatchRequest,
    _admin_identity: str = Depends(verify_admin_token),
) -> dict[str, Any]:
    """Authenticated admin edit endpoint that automatically invalidates /api/movies cache."""
    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No editable fields provided in patch request.",
        )

    sb = _get_supabase_client()
    try:
        response = (
            sb.table("movies")
            .update(updates)
            .eq("movie_slug", movie_slug)
            .execute()
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed updating movie '{movie_slug}': {exc}",
        ) from exc

    rows = getattr(response, "data", None) or []
    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Movie '{movie_slug}' not found.",
        )

    _invalidate_movies_cache()
    return {"updated": True, "movie": sanitize_public_movie(rows[0])}


@app.get("/api/movies", dependencies=[Depends(rate_limit_public)])
def list_movies(
    response: Response,
    language: str | None = Query(default=None, description="Filter by language (e.g., Malayalam)"),
    verdict: str | None = Query(default=None, description="Filter by box office verdict"),
    search: str | None = Query(default=None, description="Filter by title or cast keyword"),
    limit: int = Query(default=100, ge=1, le=500),
) -> dict[str, Any]:
    """Rate-limited, TTL-cached, white-labeled endpoint querying public Supabase columns."""
    clean_lang = (language or "").strip()
    clean_verdict = (verdict or "").strip()
    clean_search = (search or "").strip()
    cache_key = f"list|{clean_lang.lower()}|{clean_verdict.lower()}|{clean_search.lower()}|{limit}"
    now = time.monotonic()

    with _movies_cache_lock:
        cached = _movies_cache.get(cache_key)
        if cached and (now - cached[0]) < _MOVIES_CACHE_TTL_SEC:
            response.headers["X-Cache"] = "HIT"
            response.headers["Cache-Control"] = "public, max-age=30, stale-while-revalidate=60"
            return {"count": len(cached[1]), "cached": True, "movies": cached[1]}

    sb = _get_supabase_client()

    def _run_select(select_cols: str) -> Any:
        q = sb.table("movies").select(select_cols).order("india_net_cr", desc=True).limit(limit)
        if clean_lang and clean_lang.lower() != "all":
            q = q.ilike("language", clean_lang)
        if clean_verdict and clean_verdict.lower() != "all":
            q = q.ilike("verdict", f"%{clean_verdict}%")
        if clean_search:
            q = q.ilike("title", f"%{clean_search}%")
        return q.execute()

    try:
        sb_resp = _run_select(_SAFE_SELECT_FULL)
    except HTTPException:
        raise
    except Exception as exc:
        if _is_missing_optional_column_error(exc):
            try:
                sb_resp = _run_select(_SAFE_SELECT_MINIMAL)
            except Exception as fallback_exc:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"Failed querying movies from Supabase: {fallback_exc}",
                ) from fallback_exc
        else:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Failed querying movies from Supabase: {exc}",
            ) from exc

    raw_rows = getattr(sb_resp, "data", None) or []
    sanitized_rows = [
        _enrich_trailer_from_cache(sanitize_public_movie(row))
        for row in raw_rows
        if isinstance(row, dict)
    ]

    with _movies_cache_lock:
        _movies_cache[cache_key] = (now, sanitized_rows)

    response.headers["X-Cache"] = "MISS"
    response.headers["Cache-Control"] = "public, max-age=30, stale-while-revalidate=60"
    return {"count": len(sanitized_rows), "cached": False, "movies": sanitized_rows}


@app.get("/api/movies/{movie_slug}", dependencies=[Depends(rate_limit_public)])
def get_movie_detail(movie_slug: str, response: Response) -> dict[str, Any]:
    """Rate-limited, TTL-cached single-movie public endpoint with zero-leak sanitization."""
    cache_key = f"detail|{movie_slug.strip().lower()}"
    now = time.monotonic()

    with _movies_cache_lock:
        cached = _movies_cache.get(cache_key)
        if cached and (now - cached[0]) < _MOVIES_CACHE_TTL_SEC:
            response.headers["X-Cache"] = "HIT"
            return {"cached": True, "movie": cached[1]}

    sb = _get_supabase_client()

    def _run_single(select_cols: str) -> Any:
        return (
            sb.table("movies")
            .select(select_cols)
            .eq("movie_slug", movie_slug)
            .limit(1)
            .execute()
        )

    try:
        sb_resp = _run_single(_SAFE_SELECT_FULL)
    except HTTPException:
        raise
    except Exception as exc:
        if _is_missing_optional_column_error(exc):
            try:
                sb_resp = _run_single(_SAFE_SELECT_MINIMAL)
            except Exception as fallback_exc:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"Failed querying movie from Supabase: {fallback_exc}",
                ) from fallback_exc
        else:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Failed querying movie from Supabase: {exc}",
            ) from exc

    rows = getattr(sb_resp, "data", None) or []
    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Movie '{movie_slug}' not found.",
        )

    movie = _enrich_trailer_from_cache(sanitize_public_movie(rows[0]))
    with _movies_cache_lock:
        _movies_cache[cache_key] = (now, movie)

    response.headers["X-Cache"] = "MISS"
    return {"cached": False, "movie": movie}


@app.get("/api/movies/{movie_slug}/trailer", dependencies=[Depends(rate_limit_public)])
def resolve_movie_trailer(
    movie_slug: str,
    title: str | None = Query(default=None, max_length=200),
    language: str | None = Query(default=None, max_length=64),
    release_date: str | None = Query(default=None, max_length=32),
    tmdb_id: int | None = Query(default=None, ge=1),
) -> dict[str, Any]:
    """Resolve a movie's official YouTube trailer ID via local cache, TMDB /videos, or YouTube."""
    rel_year = (
        int(release_date[:4])
        if release_date and len(release_date) >= 4 and release_date[:4].isdigit()
        else None
    )
    resolved_title = (title or movie_slug.replace("-", " ")).strip()
    resolved_lang = (language or "").strip() or None

    # 1. Check existing cached trailer first
    cached_row = _lookup_cached_trailer_id(
        {
            "title": resolved_title,
            "release_date": release_date,
            "language": resolved_lang or "",
        }
    )
    if cached_row:
        return {
            "movie_slug": movie_slug,
            "trailer_youtube_id": cached_row,
            "embed_url": f"https://www.youtube-nocookie.com/embed/{cached_row}?rel=0&modestbranding=1",
            "cached": True,
        }

    # 2. Live resolve via TMDBClient (YouTube search / TMDB videos cache-persisted)
    settings = get_settings()
    settings.ensure_runtime_directories()
    video_id: str | None = None
    with TMDBClient(settings=settings) as client:
        if tmdb_id and settings.has_valid_tmdb_key():
            try:
                vid_data = client._tmdb_get(f"/movie/{tmdb_id}/videos", {"language": "en-US"})
                videos = vid_data.get("results") or []
                yt_videos = [
                    v
                    for v in videos
                    if str(v.get("site") or "").lower() == "youtube" and v.get("key")
                ]
                for preferred in ("Trailer", "Teaser"):
                    match = next(
                        (v for v in yt_videos if str(v.get("type") or "").lower() == preferred.lower()),
                        None,
                    )
                    if match:
                        video_id = str(match["key"])
                        break
                if not video_id and yt_videos:
                    video_id = str(yt_videos[0]["key"])
            except Exception:
                video_id = None

        if not video_id and resolved_title:
            video_id, _hit, _called = client.lookup_youtube_trailer(
                resolved_title,
                release_year=rel_year,
                language=resolved_lang,
            )

    return {
        "movie_slug": movie_slug,
        "trailer_youtube_id": video_id,
        "embed_url": (
            f"https://www.youtube-nocookie.com/embed/{video_id}?rel=0&modestbranding=1"
            if video_id
            else None
        ),
        "cached": False,
    }
