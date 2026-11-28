import { createClient, type RealtimeChannel, type SupabaseClient } from "@supabase/supabase-js";

export interface DailyBreakdownEntry {
  day: number;
  date: string | null;
  india_net_cr: number;
  change_pct: number | null;
  shows?: number | null;
  occupancy_pct?: number | null;
}

export interface MovieRecord {
  id?: string;
  movie_slug: string;
  title: string;
  language: string;
  original_language?: string | null;
  release_date: string | null;
  tmdb_id: number | null;
  poster_url: string | null;
  backdrop_url: string | null;
  trailer_youtube_id?: string | null;
  director?: string | null;
  synopsis?: string | null;
  cast_summary?: string | null;
  budget_cr: number | null;
  india_net_cr: number;
  india_gross_cr: number | null;
  overseas_cr: number | null;
  worldwide_gross_cr: number | null;
  verdict: string | null;
  day_count: number;
  daily_breakdown: DailyBreakdownEntry[];
  primary_source: string;
  variance_flag: boolean;
  manual_override: boolean;
  last_scraped_at: string;
  created_at?: string;
  updated_at?: string;
}

export type MovieInsert = Omit<MovieRecord, "id" | "created_at" | "updated_at">;
export type MovieUpdate = Partial<MovieInsert>;

export interface Database {
  public: {
    Tables: {
      movies: {
        Row: MovieRecord;
        Insert: MovieInsert;
        Update: MovieUpdate;
        Relationships: [];
      };
    };
    Views: Record<string, never>;
    Functions: Record<string, never>;
    Enums: Record<string, never>;
    CompositeTypes: Record<string, never>;
  };
}

const SUPABASE_URL = (import.meta.env.VITE_SUPABASE_URL ?? "").trim();
const SUPABASE_ANON_KEY = (import.meta.env.VITE_SUPABASE_ANON_KEY ?? "").trim();

function isPlaceholder(value: string): boolean {
  if (!value) return true;
  const lowered = value.toLowerCase();
  return (
    lowered.includes("your-project-id") ||
    lowered.includes("your-supabase") ||
    lowered.includes("<your")
  );
}

export const isSupabaseConfigured: boolean =
  !isPlaceholder(SUPABASE_URL) &&
  !isPlaceholder(SUPABASE_ANON_KEY) &&
  (SUPABASE_URL.startsWith("https://") || SUPABASE_URL.startsWith("http://"));

export const supabase: SupabaseClient<Database> | null = isSupabaseConfigured
  ? createClient<Database>(SUPABASE_URL, SUPABASE_ANON_KEY, {
      auth: {
        persistSession: true,
        autoRefreshToken: true,
        detectSessionInUrl: true,
      },
      realtime: {
        params: {
          eventsPerSecond: 10,
        },
      },
    })
  : null;

function toFiniteNumber(val: unknown, fallback = 0): number {
  if (val === null || val === undefined || val === "") return fallback;
  const n = Number(val);
  return Number.isFinite(n) ? n : fallback;
}

function toOptionalFiniteNumber(val: unknown): number | null {
  if (val === null || val === undefined || val === "") return null;
  const n = Number(val);
  return Number.isFinite(n) ? n : null;
}

const PUBLIC_MOVIE_SELECT =
  "id,movie_slug,title,language,original_language,release_date,tmdb_id,poster_url,backdrop_url,trailer_youtube_id,director,synopsis,cast_summary,budget_cr,india_net_cr,india_gross_cr,overseas_cr,worldwide_gross_cr,verdict,day_count,daily_breakdown,primary_source,variance_flag,manual_override,last_scraped_at,created_at,updated_at";

const PUBLIC_MOVIE_SELECT_BASE =
  "id,movie_slug,title,language,original_language,release_date,tmdb_id,poster_url,backdrop_url,cast_summary,budget_cr,india_net_cr,india_gross_cr,overseas_cr,worldwide_gross_cr,verdict,day_count,daily_breakdown,primary_source,variance_flag,manual_override,last_scraped_at,created_at,updated_at";

function sanitizePrimarySource(raw: unknown): string {
  const val = String(raw ?? "").trim().toLowerCase();
  if (!val || val === "sacnilk" || val.includes("sacnilk")) return "cinetracker_bo";
  if (val === "koimoi" || val.includes("koimoi")) return "cinetracker_trade";
  if (val === "x" || val === "twitter") return "cinetracker_pulse";
  if (val === "manual_admin") return "cinetracker_editorial";
  return val;
}

export function normalizeMovieRow(raw: Record<string, unknown>): MovieRecord {
  const rawBreakdown = Array.isArray(raw.daily_breakdown) ? raw.daily_breakdown : [];
  const daily_breakdown: DailyBreakdownEntry[] = rawBreakdown
    .map((item) => {
      const obj = (item ?? {}) as Record<string, unknown>;
      return {
        day: Math.max(0, Math.round(toFiniteNumber(obj.day, 0))),
        date: obj.date ? String(obj.date) : null,
        india_net_cr: Math.max(0, toFiniteNumber(obj.india_net_cr, 0)),
        change_pct: toOptionalFiniteNumber(obj.change_pct),
        shows: toOptionalFiniteNumber(obj.shows),
        occupancy_pct: toOptionalFiniteNumber(obj.occupancy_pct),
      };
    })
    .filter((entry) => Number.isFinite(entry.day) && Number.isFinite(entry.india_net_cr))
    .sort((a, b) => a.day - b.day);

  return {
    id: raw.id ? String(raw.id) : undefined,
    movie_slug: String(raw.movie_slug ?? ""),
    title: String(raw.title ?? "Untitled"),
    language: String(raw.language ?? "Hindi"),
    original_language: raw.original_language ? String(raw.original_language) : null,
    release_date: raw.release_date ? String(raw.release_date) : null,
    tmdb_id: toOptionalFiniteNumber(raw.tmdb_id),
    poster_url: raw.poster_url ? String(raw.poster_url) : null,
    backdrop_url: raw.backdrop_url ? String(raw.backdrop_url) : null,
    trailer_youtube_id: raw.trailer_youtube_id ? String(raw.trailer_youtube_id) : null,
    director: raw.director ? String(raw.director) : null,
    synopsis: raw.synopsis ? String(raw.synopsis) : null,
    cast_summary: raw.cast_summary ? String(raw.cast_summary) : null,
    budget_cr: toOptionalFiniteNumber(raw.budget_cr),
    india_net_cr: Math.max(0, toFiniteNumber(raw.india_net_cr, 0)),
    india_gross_cr: toOptionalFiniteNumber(raw.india_gross_cr),
    overseas_cr: toOptionalFiniteNumber(raw.overseas_cr),
    worldwide_gross_cr: toOptionalFiniteNumber(raw.worldwide_gross_cr),
    verdict: raw.verdict ? String(raw.verdict) : null,
    day_count: Math.max(0, Math.round(toFiniteNumber(raw.day_count, daily_breakdown.length))),
    daily_breakdown,
    primary_source: sanitizePrimarySource(raw.primary_source),
    variance_flag: Boolean(raw.variance_flag),
    manual_override: Boolean(raw.manual_override),
    last_scraped_at: String(raw.last_scraped_at ?? new Date().toISOString()),
    created_at: raw.created_at ? String(raw.created_at) : undefined,
    updated_at: raw.updated_at ? String(raw.updated_at) : undefined,
  };
}

const USE_EXTENDED_COLUMNS =
  (import.meta.env.VITE_SUPABASE_EXTENDED_COLUMNS ?? "").trim().toLowerCase() === "true";

export async function fetchMovies(): Promise<MovieRecord[]> {
  if (!supabase) {
    return [];
  }
  const selectCols = USE_EXTENDED_COLUMNS ? PUBLIC_MOVIE_SELECT : PUBLIC_MOVIE_SELECT_BASE;
  let { data, error } = await supabase
    .from("movies")
    .select(selectCols)
    .order("india_net_cr", { ascending: false });

  if (error && USE_EXTENDED_COLUMNS && /trailer_youtube_id|director|synopsis|column|schema cache/i.test(error.message)) {
    const fallback = await supabase
      .from("movies")
      .select(PUBLIC_MOVIE_SELECT_BASE)
      .order("india_net_cr", { ascending: false });
    data = fallback.data;
    error = fallback.error;
  }

  if (error) {
    throw new Error(error.message);
  }
  return (data ?? []).map((row) => normalizeMovieRow(row as unknown as Record<string, unknown>));
}

export async function updateMovieRecord(
  movieSlug: string,
  updates: MovieUpdate
): Promise<MovieRecord> {
  if (!supabase) {
    throw new Error("Supabase client is not configured.");
  }

  const selectCols = USE_EXTENDED_COLUMNS ? PUBLIC_MOVIE_SELECT : PUBLIC_MOVIE_SELECT_BASE;
  let { data, error } = await supabase
    .from("movies")
    .update(updates as never)
    .eq("movie_slug", movieSlug)
    .select(selectCols)
    .single();

  if (error && USE_EXTENDED_COLUMNS && /trailer_youtube_id|director|synopsis|column|schema cache/i.test(error.message)) {
    const fallback = await supabase
      .from("movies")
      .update(updates as never)
      .eq("movie_slug", movieSlug)
      .select(PUBLIC_MOVIE_SELECT_BASE)
      .single();
    data = fallback.data;
    error = fallback.error;
  }

  if (error) {
    throw new Error(error.message);
  }
  return normalizeMovieRow(data as unknown as Record<string, unknown>);
}

export async function insertManualMovie(payload: MovieInsert): Promise<MovieRecord> {
  if (!supabase) {
    throw new Error("Supabase client is not configured.");
  }

  const selectCols = USE_EXTENDED_COLUMNS ? PUBLIC_MOVIE_SELECT : PUBLIC_MOVIE_SELECT_BASE;
  let { data, error } = await supabase
    .from("movies")
    .upsert(payload as never, { onConflict: "movie_slug" })
    .select(selectCols)
    .single();

  if (error && USE_EXTENDED_COLUMNS && /trailer_youtube_id|director|synopsis|column|schema cache/i.test(error.message)) {
    const fallback = await supabase
      .from("movies")
      .upsert(payload as never, { onConflict: "movie_slug" })
      .select(PUBLIC_MOVIE_SELECT_BASE)
      .single();
    data = fallback.data;
    error = fallback.error;
  }

  if (error) {
    throw new Error(error.message);
  }
  return normalizeMovieRow(data as unknown as Record<string, unknown>);
}

export type RealtimeStatus = "SUBSCRIBED" | "CONNECTING" | "DISCONNECTED" | "UNCONFIGURED";

export function subscribeToMovies(
  onChange: (event: {
    eventType: "INSERT" | "UPDATE" | "DELETE";
    newRecord?: MovieRecord;
    oldSlug?: string;
  }) => void,
  onStatusChange: (status: RealtimeStatus) => void
): () => void {
  if (!supabase) {
    onStatusChange("UNCONFIGURED");
    return () => {};
  }

  onStatusChange("CONNECTING");
  const channel: RealtimeChannel = supabase
    .channel("movies-live-feed")
    .on(
      "postgres_changes",
      { event: "*", schema: "public", table: "movies" },
      (payload) => {
        if (payload.eventType === "DELETE") {
          const oldRow = (payload.old ?? {}) as Record<string, unknown>;
          onChange({
            eventType: "DELETE",
            oldSlug: oldRow.movie_slug ? String(oldRow.movie_slug) : undefined,
          });
          return;
        }
        const nextRow = normalizeMovieRow((payload.new ?? {}) as Record<string, unknown>);
        onChange({
          eventType: payload.eventType === "INSERT" ? "INSERT" : "UPDATE",
          newRecord: nextRow,
        });
      }
    )
    .subscribe((status) => {
      if (status === "SUBSCRIBED") {
        onStatusChange("SUBSCRIBED");
      } else if (status === "CLOSED" || status === "CHANNEL_ERROR" || status === "TIMED_OUT") {
        onStatusChange("DISCONNECTED");
      }
    });

  return () => {
    void supabase?.removeChannel(channel);
  };
}
