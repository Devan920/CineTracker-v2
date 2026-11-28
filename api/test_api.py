"""Tests for hardened FastAPI endpoints, rate limits, security headers, health, cache & white-labeling."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

import api.main as api_main


class _FakeExec:
    def __init__(self, data: list[dict[str, Any]]) -> None:
        self.data = data


class _FakeQuery:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows
        self._updated: dict[str, Any] | None = None

    def select(self, _cols: str) -> "_FakeQuery":
        return self

    def order(self, _col: str, desc: bool = False) -> "_FakeQuery":
        return self

    def limit(self, _n: int) -> "_FakeQuery":
        return self

    def ilike(self, _col: str, _pattern: str) -> "_FakeQuery":
        return self

    def eq(self, _col: str, _val: str) -> "_FakeQuery":
        return self

    def update(self, payload: dict[str, Any]) -> "_FakeQuery":
        self._updated = dict(payload)
        return self

    def execute(self) -> _FakeExec:
        if self._updated is not None:
            merged = {**self._rows[0], **self._updated}
            return _FakeExec([merged])
        return _FakeExec(self._rows)


class _FakeClient:
    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.calls = 0
        self.rows = rows or [
            {
                "id": "uuid-1",
                "movie_slug": "aadu-3",
                "title": "Aadu 3",
                "language": "Malayalam",
                "india_net_cr": 52.4,
                "primary_source": "sacnilk",
                "source_urls": ["https://www.sacnilk.com/movie/Aadu_3_2026"],
            }
        ]

    def table(self, _name: str) -> _FakeQuery:
        self.calls += 1
        return _FakeQuery(self.rows)


@pytest.fixture(autouse=True)
def _reset_api_state() -> None:
    api_main._public_rate_limiter.reset()
    api_main._admin_rate_limiter.reset()
    api_main._invalidate_movies_cache()


def test_health_endpoint_healthy_and_degraded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api_main, "_get_supabase_client", lambda: _FakeClient())
    with TestClient(api_main.app) as client:
        resp = client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["database"]["connected"] is True
        assert body["scheduler"]["running"] is True
        assert body["scheduler"]["healthy"] is True
        assert resp.headers.get("X-Content-Type-Options") == "nosniff"
        assert resp.headers.get("X-Frame-Options") == "DENY"

    class _BrokenHealthClient:
        def table(self, _name: str) -> Any:
            raise RuntimeError("Supabase unreachable")

    monkeypatch.setattr(api_main, "_get_supabase_client", lambda: _BrokenHealthClient())
    with TestClient(api_main.app) as client:
        bad = client.get("/health")
        assert bad.status_code == 503
        bad_body = bad.json()
        assert bad_body["status"] == "degraded"
        assert bad_body["database"]["connected"] is False


def test_scrape_endpoints_require_bearer_auth_and_sanitize_logs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ADMIN_API_SECRET", "super-secret-token")
    monkeypatch.setattr(
        api_main,
        "_read_recent_logs",
        lambda max_lines=40: [
            api_main.sanitize_whitelabel_text(
                "2026-11-28 | INFO | scrapers.sacnilk | Fetching https://www.sacnilk.com/movie/foo"
            )
        ],
    )
    monkeypatch.setattr(
        api_main,
        "_read_last_run_report",
        lambda: {
            "status": "success",
            "sources": {"sacnilk": {"movies": 10}, "koimoi": {"movies": 5}},
            "errors": [
                {
                    "stage": "fetch",
                    "source": "sacnilk",
                    "url": "https://www.sacnilk.com/test",
                    "message": "Timeout fetching https://www.koimoi.com/box-office",
                }
            ],
        },
    )

    with TestClient(api_main.app) as client:
        assert client.post("/api/scrape/trigger", json={}).status_code == 401
        assert client.get("/api/scrape/status").status_code == 401

        bad_hdr = {"Authorization": "Bearer wrong-token"}
        assert client.post("/api/scrape/trigger", json={}, headers=bad_hdr).status_code == 401

        good_hdr = {"Authorization": "Bearer super-secret-token"}
        status_resp = client.get("/api/scrape/status", headers=good_hdr)
        assert status_resp.status_code == 200
        data = status_resp.json()
        assert data["status"] in {"idle", "running", "completed", "failed"}
        serialized = status_resp.text.lower()
        assert "sacnilk" not in serialized
        assert "koimoi" not in serialized
        assert "cinetracker_bo" in data["last_run_report"]["sources"]


def test_trigger_scrape_rejects_concurrent_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADMIN_API_SECRET", "super-secret-token")
    headers = {"Authorization": "Bearer super-secret-token"}

    with TestClient(api_main.app) as client:
        assert api_main._scrape_execution_lock.acquire(blocking=False)
        try:
            resp = client.post(
                "/api/scrape/trigger",
                json={"source": "cinetracker_bo", "language": "malayalam"},
                headers=headers,
            )
            assert resp.status_code == 409
        finally:
            api_main._scrape_execution_lock.release()


def test_movies_endpoint_caches_sanitizes_and_invalidates_on_edit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ADMIN_API_SECRET", "super-secret-token")
    fake_sb = _FakeClient()
    monkeypatch.setattr(api_main, "_get_supabase_client", lambda: fake_sb)

    with TestClient(api_main.app) as client:
        first = client.get("/api/movies?language=Malayalam", headers={"Accept-Encoding": "gzip"})
        assert first.status_code == 200
        assert first.headers.get("X-Cache") == "MISS"
        payload = first.json()
        assert payload["cached"] is False
        assert payload["count"] == 1
        assert payload["movies"][0]["primary_source"] == "cinetracker_bo"
        assert "source_urls" not in payload["movies"][0]

        second = client.get("/api/movies?language=Malayalam")
        assert second.status_code == 200
        assert second.headers.get("X-Cache") == "HIT"
        assert second.json()["cached"] is True
        assert fake_sb.calls == 1

        patch_resp = client.patch(
            "/api/movies/aadu-3",
            json={"india_net_cr": 60.0, "manual_override": True},
            headers={"Authorization": "Bearer super-secret-token"},
        )
        assert patch_resp.status_code == 200
        assert patch_resp.json()["movie"]["primary_source"] == "cinetracker_bo"
        assert "source_urls" not in patch_resp.json()["movie"]

        third = client.get("/api/movies?language=Malayalam")
        assert third.status_code == 200
        assert third.headers.get("X-Cache") == "MISS"
        assert fake_sb.calls == 3


def test_rate_limiting_enforced_on_public_and_admin_endpoints(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ADMIN_API_SECRET", "super-secret-token")
    monkeypatch.setattr(api_main, "_get_supabase_client", lambda: _FakeClient())
    monkeypatch.setattr(
        api_main,
        "_public_rate_limiter",
        api_main._SlidingWindowRateLimiter(max_requests=3, window_seconds=60),
    )
    monkeypatch.setattr(
        api_main,
        "_admin_rate_limiter",
        api_main._SlidingWindowRateLimiter(max_requests=2, window_seconds=60),
    )

    with TestClient(api_main.app) as client:
        for _ in range(3):
            assert client.get("/api/movies").status_code == 200
        blocked_pub = client.get("/api/movies")
        assert blocked_pub.status_code == 429
        assert "Retry-After" in blocked_pub.headers

        hdrs = {"Authorization": "Bearer super-secret-token"}
        assert client.post("/api/cache/invalidate", headers=hdrs).status_code == 200
        assert client.post("/api/cache/invalidate", headers=hdrs).status_code == 200
        blocked_admin = client.post("/api/cache/invalidate", headers=hdrs)
        assert blocked_admin.status_code == 429


def test_movies_endpoint_returns_502_on_supabase_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    class _BrokenQuery:
        def select(self, _cols: str) -> "_BrokenQuery":
            return self

        def order(self, _col: str, desc: bool = False) -> "_BrokenQuery":
            return self

        def limit(self, _n: int) -> "_BrokenQuery":
            return self

        def execute(self) -> Any:
            raise RuntimeError("Upstream timeout")

    class _BrokenClient:
        def table(self, _name: str) -> _BrokenQuery:
            return _BrokenQuery()

    monkeypatch.setattr(api_main, "_get_supabase_client", lambda: _BrokenClient())

    with TestClient(api_main.app) as client:
        resp = client.get("/api/movies")
        assert resp.status_code == 502
        assert "Supabase" in resp.json()["detail"]


def test_trailer_resolution_endpoint_uses_cached_youtube_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(api_main, "_lookup_cached_trailer_id", lambda _row: "MeYJ38OCXjs")
    with TestClient(api_main.app) as client:
        resp = client.get("/api/movies/hail-mary/trailer?title=Hail+Mary&language=Malayalam")
        assert resp.status_code == 200
        body = resp.json()
        assert body["trailer_youtube_id"] == "MeYJ38OCXjs"
        assert "youtube-nocookie.com/embed/MeYJ38OCXjs" in body["embed_url"]
        assert body["cached"] is True


def test_api_imports_cleanly_when_launched_inside_api_directory() -> None:
    import subprocess
    import sys
    from pathlib import Path

    api_dir = Path(__file__).resolve().parent
    proc = subprocess.run(
        [sys.executable, "-c", "import main; assert main.app.title and callable(main.run_pipeline)"],
        cwd=str(api_dir),
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert proc.returncode == 0, proc.stderr
