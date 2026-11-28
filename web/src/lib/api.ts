export type ScraperSourceOption =
  | "all"
  | "cinetracker_bo"
  | "cinetracker_trade"
  | "cinetracker_pulse";
export type ScraperLanguageOption =
  | "all"
  | "malayalam"
  | "tamil"
  | "hindi"
  | "telugu"
  | "kannada"
  | "pan-india";

export interface ScrapeTriggerPayload {
  source: ScraperSourceOption;
  language: ScraperLanguageOption;
  limit?: number | null;
  dry_run?: boolean;
}

export interface LastRunReport {
  run_id?: string;
  status?: string;
  duration_sec?: number;
  reconciliation?: {
    total_movies?: number;
    multi_source_matches?: number;
    variance_anomalies?: number;
    flagged_slugs?: string[];
  };
  database?: {
    upserted?: number;
    manual_override_locked?: number;
    daily_rows_synced?: number;
    skipped_dry_run?: number;
  };
  errors?: Array<{
    stage?: string;
    source?: string | null;
    movie_title?: string | null;
    message?: string;
  }>;
}

export interface ScrapeStatusPayload {
  status: "idle" | "running" | "completed" | "failed";
  started_at: string | null;
  finished_at: string | null;
  duration_sec: number | null;
  source: string | null;
  language: string | null;
  records_synced: number;
  movies_reconciled: number;
  error_message: string | null;
  last_run_report: LastRunReport | null;
  recent_logs: string[];
}

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000")
  .trim()
  .replace(/\/+$/, "");

export function getApiBaseUrl(): string {
  return API_BASE_URL;
}

export async function triggerScrapeJob(
  accessToken: string,
  payload: ScrapeTriggerPayload
): Promise<void> {
  const res = await fetch(`${API_BASE_URL}/api/scrape/trigger`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${accessToken}`,
    },
    body: JSON.stringify(payload),
  });

  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const errJson = (await res.json()) as { detail?: string };
      if (errJson.detail) detail = errJson.detail;
    } catch {
      // ignore non-JSON error
    }
    throw new Error(detail);
  }
}

export async function fetchScrapeStatus(
  accessToken: string
): Promise<ScrapeStatusPayload> {
  const res = await fetch(`${API_BASE_URL}/api/scrape/status`, {
    headers: {
      Authorization: `Bearer ${accessToken}`,
    },
  });

  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const errJson = (await res.json()) as { detail?: string };
      if (errJson.detail) detail = errJson.detail;
    } catch {
      // ignore non-JSON error
    }
    throw new Error(detail);
  }

  return (await res.json()) as ScrapeStatusPayload;
}

export async function invalidateMoviesApiCache(accessToken: string): Promise<void> {
  try {
    await fetch(`${API_BASE_URL}/api/cache/invalidate`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${accessToken}`,
      },
    });
  } catch {
    // Non-blocking best-effort cache invalidation when FastAPI API is local/optional
  }
}

export async function fetchMovieTrailerId(params: {
  movie_slug: string;
  title: string;
  language?: string | null;
  release_date?: string | null;
  tmdb_id?: number | null;
}): Promise<string | null> {
  try {
    const qs = new URLSearchParams({
      title: params.title,
    });
    if (params.language) qs.set("language", params.language);
    if (params.release_date) qs.set("release_date", params.release_date);
    if (params.tmdb_id) qs.set("tmdb_id", String(params.tmdb_id));

    const res = await fetch(
      `${API_BASE_URL}/api/movies/${encodeURIComponent(params.movie_slug)}/trailer?${qs.toString()}`
    );
    if (res.ok) {
      const json = (await res.json()) as { trailer_youtube_id?: string | null };
      if (json.trailer_youtube_id) return json.trailer_youtube_id;
    }
  } catch {
    // Fallback to client-side TMDB video lookup when FastAPI server is unavailable
  }

  const tmdbKey = (import.meta.env.VITE_TMDB_API_KEY ?? "").trim();
  if (params.tmdb_id && tmdbKey && !tmdbKey.toLowerCase().includes("your-tmdb")) {
    try {
      const resp = await fetch(
        `https://api.themoviedb.org/3/movie/${params.tmdb_id}/videos?api_key=${encodeURIComponent(
          tmdbKey
        )}&language=en-US`
      );
      if (resp.ok) {
        const data = (await resp.json()) as {
          results?: Array<{ site?: string; type?: string; key?: string }>;
        };
        const yt = (data.results ?? []).filter(
          (v) => v.site?.toLowerCase() === "youtube" && Boolean(v.key)
        );
        const trailer =
          yt.find((v) => v.type?.toLowerCase() === "trailer") ??
          yt.find((v) => v.type?.toLowerCase() === "teaser") ??
          yt[0];
        if (trailer?.key) return trailer.key;
      }
    } catch {
      // Ignore TMDB fallback network errors cleanly
    }
  }

  return null;
}
