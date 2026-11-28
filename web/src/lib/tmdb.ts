export interface TmdbSearchCandidate {
  tmdb_id: number;
  title: string;
  original_title: string;
  release_date: string | null;
  original_language: string;
  poster_url: string | null;
  backdrop_url: string | null;
  overview: string;
}

const TMDB_BASE = "https://api.themoviedb.org/3";
const TMDB_POSTER = "https://image.tmdb.org/t/p/w500";
const TMDB_BACKDROP = "https://image.tmdb.org/t/p/w1280";

const ISO_TO_DISPLAY: Record<string, string> = {
  ml: "Malayalam",
  ta: "Tamil",
  hi: "Hindi",
  te: "Telugu",
  kn: "Kannada",
  en: "English",
};

export function getTmdbApiKey(): string {
  const key = (import.meta.env.VITE_TMDB_API_KEY ?? "").trim();
  if (!key || key.toLowerCase().includes("your-tmdb")) {
    return "";
  }
  return key;
}

export function mapIsoLanguage(iso: string | null | undefined): string {
  if (!iso) return "Hindi";
  return ISO_TO_DISPLAY[iso.toLowerCase()] ?? iso.toUpperCase();
}

export async function searchTmdbMovies(query: string): Promise<TmdbSearchCandidate[]> {
  const apiKey = getTmdbApiKey();
  if (!apiKey) {
    throw new Error("VITE_TMDB_API_KEY is missing in your frontend environment.");
  }
  const trimmed = query.trim();
  if (!trimmed) return [];

  const url = `${TMDB_BASE}/search/movie?api_key=${encodeURIComponent(apiKey)}&query=${encodeURIComponent(
    trimmed
  )}&include_adult=false`;
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`TMDB search failed with HTTP ${response.status}`);
  }
  const json = (await response.json()) as { results?: Array<Record<string, unknown>> };
  return (json.results ?? []).slice(0, 8).map((item) => ({
    tmdb_id: Number(item.id),
    title: String(item.title ?? ""),
    original_title: String(item.original_title ?? item.title ?? ""),
    release_date: item.release_date ? String(item.release_date) : null,
    original_language: String(item.original_language ?? "hi"),
    poster_url: item.poster_path ? `${TMDB_POSTER}${String(item.poster_path)}` : null,
    backdrop_url: item.backdrop_path ? `${TMDB_BACKDROP}${String(item.backdrop_path)}` : null,
    overview: String(item.overview ?? ""),
  }));
}

export async function fetchTmdbMovieCast(tmdbId: number): Promise<string | null> {
  const apiKey = getTmdbApiKey();
  if (!apiKey) return null;

  const url = `${TMDB_BASE}/movie/${tmdbId}/credits?api_key=${encodeURIComponent(apiKey)}`;
  const response = await fetch(url);
  if (!response.ok) return null;
  const json = (await response.json()) as { cast?: Array<{ name?: string }> };
  const names = (json.cast ?? [])
    .slice(0, 5)
    .map((m) => (m.name ?? "").trim())
    .filter(Boolean);
  return names.length ? names.join(", ") : null;
}
