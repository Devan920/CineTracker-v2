import type { DailyBreakdownEntry, MovieRecord } from "./supabase";

export const LIVE_RUNNING_FILTER = "🔥 Live Running" as const;

export const MOVIE_LANGUAGES = [
  "Malayalam",
  "Tamil",
  "Hindi",
  "Telugu",
  "Kannada",
  "English",
  "Pan-India",
] as const;

export const LANGUAGE_FILTERS = [
  "All",
  LIVE_RUNNING_FILTER,
  "Malayalam",
  "Tamil",
  "Hindi",
  "Telugu",
  "Kannada",
  "Pan-India",
] as const;

export type LanguageFilter = (typeof LANGUAGE_FILTERS)[number];

export function isMovieLiveRunning(movie: MovieRecord): boolean {
  const nowMs = Date.now();
  if (movie.release_date) {
    const relMs = new Date(movie.release_date).getTime();
    if (!Number.isNaN(relMs)) {
      const daysSinceRelease = (nowMs - relMs) / 86_400_000;
      if (daysSinceRelease >= -7 && daysSinceRelease <= 35) {
        return true;
      }
      if (daysSinceRelease > 60) {
        return false;
      }
    }
  }
  const verdictLow = (movie.verdict ?? "").trim().toLowerCase();
  const isOngoingVerdict = !verdictLow || verdictLow.includes("theatres") || verdictLow.includes("live");
  const lastScrapedMs = movie.last_scraped_at ? new Date(movie.last_scraped_at).getTime() : 0;
  const recentlyScraped = !Number.isNaN(lastScrapedMs) && (nowMs - lastScrapedMs) / 86_400_000 <= 7;
  return Boolean(isOngoingVerdict && recentlyScraped && movie.day_count > 0 && movie.day_count <= 35);
}

export function getLatestDayStats(movie: MovieRecord): {
  day: number;
  date: string | null;
  india_net_cr: number;
  change_pct: number | null;
  shows: number | null;
  occupancy_pct: number | null;
} | null {
  if (!movie.daily_breakdown.length) return null;
  const last = movie.daily_breakdown[movie.daily_breakdown.length - 1];
  return {
    day: last.day,
    date: last.date ?? null,
    india_net_cr: last.india_net_cr,
    change_pct: last.change_pct ?? null,
    shows: last.shows ?? null,
    occupancy_pct: last.occupancy_pct ?? null,
  };
}

export function formatCrores(
  value: number | null | undefined,
  options: { compact?: boolean; includeSymbol?: boolean } = {}
): string {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return "—";
  }
  const { compact = false, includeSymbol = true } = options;
  const prefix = includeSymbol ? "₹" : "";
  if (compact && Math.abs(value) < 1 && value > 0) {
    const lakhs = value * 100;
    return `${prefix}${lakhs.toFixed(1)} L`;
  }
  const formatted = new Intl.NumberFormat("en-IN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value);
  return `${prefix}${formatted} Cr`;
}

export function formatRelativeTime(isoTimestamp: string | null | undefined): string {
  if (!isoTimestamp) return "Never";
  const dt = new Date(isoTimestamp);
  if (Number.isNaN(dt.getTime())) return "Unknown";

  const diffSec = Math.max(0, Math.floor((Date.now() - dt.getTime()) / 1000));
  if (diffSec < 60) return `${diffSec}s ago`;
  const diffMin = Math.floor(diffSec / 60);
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h ago`;
  const diffDays = Math.floor(diffHr / 24);
  return `${diffDays}d ago`;
}

export function formatExactTimestamp(isoTimestamp: string | null | undefined): string {
  if (!isoTimestamp) return "—";
  const dt = new Date(isoTimestamp);
  if (Number.isNaN(dt.getTime())) return "—";
  return dt.toLocaleString("en-IN", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function computeBudgetRecoveryPct(movie: MovieRecord): number | null {
  if (!movie.budget_cr || movie.budget_cr <= 0) return null;
  const gross = movie.worldwide_gross_cr ?? movie.india_gross_cr ?? movie.india_net_cr;
  if (!gross || gross <= 0) return 0;
  return (gross / movie.budget_cr) * 100;
}

export function computeRoiMultiple(movie: MovieRecord): number | null {
  if (!movie.budget_cr || movie.budget_cr <= 0) return null;
  const gross = movie.worldwide_gross_cr ?? movie.india_gross_cr ?? movie.india_net_cr;
  if (!gross || gross <= 0) return 0;
  return gross / movie.budget_cr;
}

export function getVerdictStyle(verdict: string | null | undefined): {
  label: string;
  className: string;
} {
  const normalized = (verdict ?? "").trim().toLowerCase();
  if (normalized.includes("all time blockbuster")) {
    return {
      label: verdict ?? "All Time Blockbuster",
      className:
        "bg-[#F59E0B]/20 text-[#FCD34D] border border-[#F59E0B]/50 shadow-[0_0_16px_rgba(245,158,11,0.25)]",
    };
  }
  if (normalized.includes("blockbuster")) {
    return {
      label: verdict ?? "Blockbuster",
      className: "bg-[#F59E0B]/15 text-[#F59E0B] border border-[#F59E0B]/40",
    };
  }
  if (normalized.includes("super hit")) {
    return {
      label: verdict ?? "Super Hit",
      className: "bg-[#10B981]/20 text-[#34D399] border border-[#10B981]/40",
    };
  }
  if (normalized.includes("hit") || normalized.includes("plus")) {
    return {
      label: verdict ?? "Hit",
      className: "bg-emerald-500/15 text-emerald-300 border border-emerald-500/35",
    };
  }
  if (normalized.includes("average") && !normalized.includes("below")) {
    return {
      label: verdict ?? "Average",
      className: "bg-sky-500/15 text-sky-300 border border-sky-500/35",
    };
  }
  if (normalized.includes("below average") || normalized.includes("flop") || normalized.includes("disaster")) {
    return {
      label: verdict ?? "Flop",
      className: "bg-rose-500/15 text-rose-300 border border-rose-500/35",
    };
  }
  return {
    label: verdict || "In Theatres",
    className: "bg-zinc-800/90 text-zinc-300 border border-zinc-700",
  };
}

export function slugifyTitle(title: string): string {
  return title
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/&/g, " and ")
    .replace(/[^a-z0-9\s-]/g, " ")
    .trim()
    .replace(/\s+/g, "-")
    .replace(/-+/g, "-") || "untitled-movie";
}

export function computeMovieMilestones(breakdown: DailyBreakdownEntry[]): {
  day1: number | null;
  weekend1: number | null;
  week1: number | null;
} {
  if (!breakdown.length) {
    return { day1: null, weekend1: null, week1: null };
  }
  const day1Entry = breakdown.find((d) => d.day === 1);
  const weekendEntries = breakdown.filter((d) => d.day >= 0 && d.day <= 3);
  const week1Entries = breakdown.filter((d) => d.day >= 0 && d.day <= 7);

  return {
    day1: day1Entry ? day1Entry.india_net_cr : null,
    weekend1: weekendEntries.length
      ? Number(weekendEntries.reduce((sum, item) => sum + item.india_net_cr, 0).toFixed(2))
      : null,
    week1: week1Entries.length
      ? Number(week1Entries.reduce((sum, item) => sum + item.india_net_cr, 0).toFixed(2))
      : null,
  };
}

export function getYoutubeSearchUrl(
  movie: Pick<MovieRecord, "title" | "release_date" | "language">
): string {
  const yr = movie.release_date?.slice(0, 4);
  const yearPart = yr && /^\d{4}$/.test(yr) ? ` ${yr}` : "";
  const langPart =
    movie.language &&
    !["pan-india", "english", "all"].includes(movie.language.toLowerCase())
      ? ` ${movie.language}`
      : "";
  const query = `${movie.title}${langPart}${yearPart} Official Trailer`.trim();
  return `https://www.youtube.com/results?search_query=${encodeURIComponent(query)}`;
}

export function formatSourceLabel(rawSource: string | null | undefined): string {
  const key = (rawSource ?? "").trim().toLowerCase();
  if (!key || key === "sacnilk" || key === "cinetracker_bo" || key.includes("sacnilk")) {
    return "CineTracker BO";
  }
  if (key === "koimoi" || key === "cinetracker_trade" || key.includes("koimoi")) {
    return "CineTracker Trade";
  }
  if (key === "x" || key === "twitter" || key === "cinetracker_pulse") {
    return "CineTracker Pulse";
  }
  if (key === "manual_admin" || key === "cinetracker_editorial") {
    return "Editorial Desk";
  }
  return key.replace(/_/g, " ");
}
