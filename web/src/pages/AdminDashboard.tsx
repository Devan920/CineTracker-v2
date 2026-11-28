import type { Session } from "@supabase/supabase-js";
import {
  Activity,
  AlertTriangle,
  ArrowDownUp,
  CheckCircle2,
  Edit3,
  Lock,
  LogOut,
  Play,
  Plus,
  RefreshCw,
  Search,
  Shield,
  Terminal,
  Trash2,
  Unlock,
  X,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { BrandLogo } from "../components/BrandLogo";
import {
  fetchScrapeStatus,
  getApiBaseUrl,
  invalidateMoviesApiCache,
  triggerScrapeJob,
  type ScrapeStatusPayload,
  type ScraperLanguageOption,
  type ScraperSourceOption,
} from "../lib/api";
import {
  formatCrores,
  formatExactTimestamp,
  formatSourceLabel,
  MOVIE_LANGUAGES,
  slugifyTitle,
} from "../lib/formatters";
import {
  insertManualMovie,
  isSupabaseConfigured,
  supabase,
  updateMovieRecord,
  type DailyBreakdownEntry,
  type MovieRecord,
} from "../lib/supabase";
import {
  fetchTmdbMovieCast,
  getTmdbApiKey,
  mapIsoLanguage,
  searchTmdbMovies,
  type TmdbSearchCandidate,
} from "../lib/tmdb";

interface AdminDashboardProps {
  movies: MovieRecord[];
  onMoviesUpdated: (updated: MovieRecord) => void;
}

type SortField =
  | "title"
  | "india_net_cr"
  | "worldwide_gross_cr"
  | "day_count"
  | "variance_flag"
  | "last_scraped_at";

const VERDICT_OPTIONS = [
  "",
  "All Time Blockbuster",
  "Blockbuster",
  "Super Hit",
  "Hit",
  "Semi-Hit",
  "Average",
  "Below Average",
  "Flop",
  "Disaster",
];

export function AdminDashboard({ movies, onMoviesUpdated }: AdminDashboardProps) {
  const [session, setSession] = useState<Session | null>(null);
  const [authLoading, setAuthLoading] = useState<boolean>(isSupabaseConfigured);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [authError, setAuthError] = useState<string | null>(null);
  const [signingIn, setSigningIn] = useState(false);

  // Table filtering & sorting
  const [filterMode, setFilterMode] = useState<"all" | "conflicts" | "locked">("all");
  const [search, setSearch] = useState("");
  const [sortField, setSortField] = useState<SortField>("variance_flag");
  const [sortAsc, setSortAsc] = useState(false);

  // Edit Drawer state
  const [editingMovie, setEditingMovie] = useState<MovieRecord | null>(null);
  const [editForm, setEditForm] = useState<{
    india_net_cr: string;
    india_gross_cr: string;
    overseas_cr: string;
    worldwide_gross_cr: string;
    budget_cr: string;
    verdict: string;
    variance_flag: boolean;
    manual_override: boolean;
    daily_breakdown: DailyBreakdownEntry[];
  } | null>(null);
  const [savingEdit, setSavingEdit] = useState(false);
  const [editError, setEditError] = useState<string | null>(null);
  const [lockError, setLockError] = useState<string | null>(null);

  // Add Manual Movie state
  const [showAddModal, setShowAddModal] = useState(false);
  const [tmdbQuery, setTmdbQuery] = useState("");
  const [tmdbResults, setTmdbResults] = useState<TmdbSearchCandidate[]>([]);
  const [searchingTmdb, setSearchingTmdb] = useState(false);
  const [tmdbSearchErr, setTmdbSearchErr] = useState<string | null>(null);
  const [manualForm, setManualForm] = useState({
    title: "",
    movie_slug: "",
    language: "Malayalam",
    release_date: "",
    tmdb_id: "",
    poster_url: "",
    backdrop_url: "",
    cast_summary: "",
    budget_cr: "",
    india_net_cr: "0",
    worldwide_gross_cr: "",
    verdict: "",
    manual_override: true,
  });
  const [savingNew, setSavingNew] = useState(false);
  const [newErr, setNewErr] = useState<string | null>(null);

  // Live Scraper Control Panel state
  const [scrapeSource, setScrapeSource] = useState<ScraperSourceOption>("all");
  const [scrapeLanguage, setScrapeLanguage] = useState<ScraperLanguageOption>("all");
  const [scraperStatus, setScraperStatus] = useState<ScrapeStatusPayload | null>(null);
  const [triggeringScrape, setTriggeringScrape] = useState(false);
  const [apiError, setApiError] = useState<string | null>(null);
  const [showLogs, setShowLogs] = useState(false);
  const prevScraperStateRef = useRef<string | null>(null);

  const loadScraperStatus = useCallback(async (token: string) => {
    try {
      const next = await fetchScrapeStatus(token);
      setScraperStatus(next);
      setApiError(null);
      prevScraperStateRef.current = next.status;
    } catch (err) {
      setApiError(
        err instanceof Error ? err.message : `Unable to reach ${getApiBaseUrl()}`
      );
    }
  }, []);

  useEffect(() => {
    if (!session?.access_token) return;
    void loadScraperStatus(session.access_token);
  }, [session?.access_token, loadScraperStatus]);

  useEffect(() => {
    if (!session?.access_token || scraperStatus?.status !== "running") return;
    const timer = window.setInterval(() => {
      void loadScraperStatus(session.access_token);
    }, 3000);
    return () => window.clearInterval(timer);
  }, [session?.access_token, scraperStatus?.status, loadScraperStatus]);

  const handleTriggerScrape = async () => {
    if (!session?.access_token) return;
    setTriggeringScrape(true);
    setApiError(null);
    try {
      await triggerScrapeJob(session.access_token, {
        source: scrapeSource,
        language: scrapeLanguage,
        limit: null,
      });
      await loadScraperStatus(session.access_token);
    } catch (err) {
      setApiError(err instanceof Error ? err.message : "Failed to trigger live scrape.");
    } finally {
      setTriggeringScrape(false);
    }
  };

  useEffect(() => {
    if (!supabase) {
      setAuthLoading(false);
      return;
    }

    let mounted = true;
    void supabase.auth.getSession().then(({ data }) => {
      if (mounted) {
        setSession(data.session ?? null);
        setAuthLoading(false);
      }
    });

    const { data: listener } = supabase.auth.onAuthStateChange((_event, nextSession) => {
      setSession(nextSession);
    });

    return () => {
      mounted = false;
      listener.subscription.unsubscribe();
    };
  }, []);

  const handleSignIn = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!supabase) return;
    setSigningIn(true);
    setAuthError(null);
    const { error } = await supabase.auth.signInWithPassword({
      email: email.trim(),
      password,
    });
    if (error) {
      setAuthError(error.message);
    }
    setSigningIn(false);
  };

  const handleSignOut = async () => {
    if (!supabase) return;
    await supabase.auth.signOut();
  };

  const openEditDrawer = (movie: MovieRecord) => {
    setEditingMovie(movie);
    setEditError(null);
    setEditForm({
      india_net_cr: String(movie.india_net_cr ?? 0),
      india_gross_cr: movie.india_gross_cr !== null ? String(movie.india_gross_cr) : "",
      overseas_cr: movie.overseas_cr !== null ? String(movie.overseas_cr) : "",
      worldwide_gross_cr:
        movie.worldwide_gross_cr !== null ? String(movie.worldwide_gross_cr) : "",
      budget_cr: movie.budget_cr !== null ? String(movie.budget_cr) : "",
      verdict: movie.verdict ?? "",
      variance_flag: movie.variance_flag,
      manual_override: movie.manual_override,
      daily_breakdown: movie.daily_breakdown.map((d) => ({ ...d })),
    });
  };

  const handleSaveEdit = async () => {
    if (!editingMovie || !editForm) return;
    setSavingEdit(true);
    setEditError(null);
    try {
      const parseNullable = (v: string): number | null => {
        const trimmed = v.trim();
        if (!trimmed) return null;
        const n = Number(trimmed);
        return Number.isFinite(n) && n >= 0 ? n : null;
      };

      const parsedNet = Number(editForm.india_net_cr);
      const safeNet = Number.isFinite(parsedNet) && parsedNet >= 0 ? parsedNet : 0;

      const cleanedDays = [...editForm.daily_breakdown]
        .filter(
          (d) =>
            Number.isFinite(d.day) &&
            d.day >= 0 &&
            Number.isFinite(d.india_net_cr) &&
            d.india_net_cr >= 0
        )
        .map((d) => ({
          ...d,
          day: Math.round(d.day),
          date: d.date?.trim() ? d.date.trim() : null,
        }))
        .sort((a, b) => a.day - b.day);

      const theatricalDays = cleanedDays.filter((d) => d.day >= 1).length;
      const updated = await updateMovieRecord(editingMovie.movie_slug, {
        india_net_cr: safeNet,
        india_gross_cr: parseNullable(editForm.india_gross_cr),
        overseas_cr: parseNullable(editForm.overseas_cr),
        worldwide_gross_cr: parseNullable(editForm.worldwide_gross_cr),
        budget_cr: parseNullable(editForm.budget_cr),
        verdict: editForm.verdict.trim() || null,
        variance_flag: editForm.variance_flag,
        manual_override: editForm.manual_override,
        daily_breakdown: cleanedDays,
        day_count: Math.max(editingMovie.day_count, theatricalDays),
      });
      onMoviesUpdated(updated);
      if (session?.access_token) {
        void invalidateMoviesApiCache(session.access_token);
      }
      setEditingMovie(null);
      setEditForm(null);
    } catch (err) {
      setEditError(err instanceof Error ? err.message : "Failed to save movie edits.");
    } finally {
      setSavingEdit(false);
    }
  };

  const handleQuickToggleLock = async (movie: MovieRecord) => {
    setLockError(null);
    try {
      const updated = await updateMovieRecord(movie.movie_slug, {
        manual_override: !movie.manual_override,
      });
      onMoviesUpdated(updated);
      if (session?.access_token) {
        void invalidateMoviesApiCache(session.access_token);
      }
    } catch (err) {
      setLockError(err instanceof Error ? err.message : "Failed to toggle manual override.");
    }
  };

  const handleTmdbSearch = async () => {
    setSearchingTmdb(true);
    setTmdbSearchErr(null);
    try {
      const hits = await searchTmdbMovies(tmdbQuery);
      setTmdbResults(hits);
    } catch (err) {
      setTmdbSearchErr(err instanceof Error ? err.message : "TMDB search failed.");
    } finally {
      setSearchingTmdb(false);
    }
  };

  const applyTmdbCandidate = async (cand: TmdbSearchCandidate) => {
    const cast = await fetchTmdbMovieCast(cand.tmdb_id);
    setManualForm((prev) => ({
      ...prev,
      title: cand.title,
      movie_slug: slugifyTitle(cand.title),
      language: mapIsoLanguage(cand.original_language),
      release_date: cand.release_date ?? "",
      tmdb_id: String(cand.tmdb_id),
      poster_url: cand.poster_url ?? "",
      backdrop_url: cand.backdrop_url ?? "",
      cast_summary: cast ?? "",
    }));
  };

  const handleCreateManualMovie = async (e: React.FormEvent) => {
    e.preventDefault();
    setSavingNew(true);
    setNewErr(null);
    try {
      const title = manualForm.title.trim();
      if (!title) throw new Error("Movie title is required.");
      const slug = manualForm.movie_slug.trim() || slugifyTitle(title);

      const parseOpt = (raw: string): number | null => {
        const t = raw.trim();
        if (!t) return null;
        const n = Number(t);
        return Number.isFinite(n) && n >= 0 ? n : null;
      };
      const netRaw = Number(manualForm.india_net_cr);
      const safeNet = Number.isFinite(netRaw) && netRaw >= 0 ? netRaw : 0;

      const inserted = await insertManualMovie({
        movie_slug: slug,
        title,
        language: manualForm.language,
        original_language: manualForm.language,
        release_date: manualForm.release_date.trim() || null,
        tmdb_id: parseOpt(manualForm.tmdb_id),
        poster_url: manualForm.poster_url.trim() || null,
        backdrop_url: manualForm.backdrop_url.trim() || null,
        cast_summary: manualForm.cast_summary.trim() || null,
        budget_cr: parseOpt(manualForm.budget_cr),
        india_net_cr: safeNet,
        india_gross_cr: null,
        overseas_cr: null,
        worldwide_gross_cr: parseOpt(manualForm.worldwide_gross_cr),
        verdict: manualForm.verdict.trim() || null,
        day_count: safeNet > 0 ? 1 : 0,
        daily_breakdown:
          safeNet > 0
            ? [
                {
                  day: 1,
                  date: manualForm.release_date.trim() || null,
                  india_net_cr: safeNet,
                  change_pct: null,
                },
              ]
            : [],
        primary_source: "cinetracker_editorial",
        variance_flag: false,
        manual_override: manualForm.manual_override,
        last_scraped_at: new Date().toISOString(),
      });
      onMoviesUpdated(inserted);
      if (session?.access_token) {
        void invalidateMoviesApiCache(session.access_token);
      }
      setShowAddModal(false);
    } catch (err) {
      setNewErr(err instanceof Error ? err.message : "Failed to create movie record.");
    } finally {
      setSavingNew(false);
    }
  };

  const filteredAndSorted = useMemo(() => {
    const q = search.trim().toLowerCase();
    const list = movies.filter((m) => {
      if (filterMode === "conflicts" && !m.variance_flag) return false;
      if (filterMode === "locked" && !m.manual_override) return false;
      if (q && !m.title.toLowerCase().includes(q) && !m.language.toLowerCase().includes(q)) {
        return false;
      }
      return true;
    });

    list.sort((a, b) => {
      let cmp = 0;
      if (sortField === "title") {
        cmp = a.title.localeCompare(b.title);
      } else if (sortField === "india_net_cr") {
        cmp = a.india_net_cr - b.india_net_cr;
      } else if (sortField === "worldwide_gross_cr") {
        cmp = (a.worldwide_gross_cr ?? 0) - (b.worldwide_gross_cr ?? 0);
      } else if (sortField === "day_count") {
        cmp = a.day_count - b.day_count;
      } else if (sortField === "variance_flag") {
        cmp = Number(a.variance_flag) - Number(b.variance_flag);
      } else if (sortField === "last_scraped_at") {
        cmp = new Date(a.last_scraped_at).getTime() - new Date(b.last_scraped_at).getTime();
      }
      return sortAsc ? cmp : -cmp;
    });

    return list;
  }, [movies, filterMode, search, sortField, sortAsc]);

  const conflictCount = movies.filter((m) => m.variance_flag).length;
  const lockedCount = movies.filter((m) => m.manual_override).length;

  const toggleSort = (field: SortField) => {
    if (sortField === field) {
      setSortAsc(!sortAsc);
    } else {
      setSortField(field);
      setSortAsc(false);
    }
  };

  if (!isSupabaseConfigured) {
    return (
      <div className="mx-auto max-w-xl rounded-2xl border border-white/[0.08] bg-[#12151E] p-6 text-center">
        <div className="flex justify-center">
          <BrandLogo variant="icon" size="lg" />
        </div>
        <h1 className="mt-3 font-display text-xl font-bold text-white">
          Configure Supabase To Access Admin Override
        </h1>
        <p className="mt-2 text-xs text-zinc-400">
          Set <code className="text-zinc-200">VITE_SUPABASE_URL</code> and{" "}
          <code className="text-zinc-200">VITE_SUPABASE_ANON_KEY</code> in{" "}
          <code className="text-zinc-200">.env</code> to authenticate with Supabase Auth.
        </p>
      </div>
    );
  }

  if (authLoading) {
    return (
      <div className="flex h-64 items-center justify-center text-sm text-zinc-400">
        Verifying Supabase Admin session...
      </div>
    );
  }

  if (!session) {
    return (
      <div className="mx-auto max-w-md rounded-2xl border border-white/[0.08] bg-[#12151E] p-6 shadow-2xl">
        <div className="space-y-2 border-b border-white/[0.08] pb-4">
          <BrandLogo variant="full" size="md" showLiveBadge={true} />
          <div className="pt-1">
            <h1 className="font-display text-lg font-bold text-white">Admin Override Portal</h1>
            <p className="text-xs text-zinc-400">Protected by Supabase Auth</p>
          </div>
        </div>

        <form onSubmit={(e) => void handleSignIn(e)} className="mt-5 space-y-4">
          {authError && (
            <div className="rounded-xl border border-rose-500/40 bg-rose-500/10 p-3 text-xs text-rose-300">
              {authError}
            </div>
          )}
          <div>
            <label className="block text-xs font-medium text-zinc-300">Admin Email</label>
            <input
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="admin@cinetracker.in"
              className="mt-1 w-full rounded-xl border border-white/[0.1] bg-[#090A0F] px-3 py-2 text-sm text-white focus:border-[#F59E0B] focus:outline-none"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-zinc-300">Password</label>
            <input
              type="password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••"
              className="mt-1 w-full rounded-xl border border-white/[0.1] bg-[#090A0F] px-3 py-2 text-sm text-white focus:border-[#F59E0B] focus:outline-none"
            />
          </div>
          <button
            type="submit"
            disabled={signingIn}
            className="w-full rounded-xl bg-[#F59E0B] py-2.5 text-sm font-bold text-black transition hover:bg-amber-400 disabled:opacity-60"
          >
            {signingIn ? "Signing In..." : "Sign In to Admin Dashboard"}
          </button>
        </form>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      {/* Header Controls */}
      <div className="flex flex-wrap items-center justify-between gap-4 rounded-2xl border border-zinc-800 bg-[#18181B] p-5">
        <div>
          <h1 className="flex items-center gap-2 font-display text-xl font-bold text-white">
            <Shield className="h-5 w-5 text-[#EAB308]" />
            Box Office Override &amp; Audit Console
          </h1>
          <p className="mt-0.5 text-xs text-zinc-400">
            Signed in as <span className="text-zinc-200">{session.user.email}</span> •{" "}
            <span className="text-amber-300">{conflictCount} conflicts</span> •{" "}
            <span className="text-sky-300">{lockedCount} manual locks</span>
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2.5">
          <button
            type="button"
            onClick={() => setShowAddModal(true)}
            className="inline-flex items-center gap-1.5 rounded-xl bg-[#10B981] px-3.5 py-2 text-xs font-bold text-black hover:bg-emerald-400"
          >
            <Plus className="h-4 w-4" />
            Add Manual Movie
          </button>
          <button
            type="button"
            onClick={() => void handleSignOut()}
            className="inline-flex items-center gap-1.5 rounded-xl border border-zinc-700 bg-[#09090B] px-3 py-2 text-xs font-medium text-zinc-300 hover:text-white"
          >
            <LogOut className="h-3.5 w-3.5" />
            Sign Out
          </button>
        </div>
      </div>

      {/* Live Scraper Control Panel */}
      <section className="rounded-2xl border border-zinc-800 bg-[#18181B] p-5">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <div className="flex flex-wrap items-center gap-2.5">
              <h2 className="flex items-center gap-2 font-display text-base font-bold text-white">
                <Activity className="h-4 w-4 text-[#10B981]" />
                Live Scraper Control Panel
              </h2>
              {scraperStatus ? (
                <span
                  className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 font-mono text-[11px] font-semibold uppercase ${
                    scraperStatus.status === "running"
                      ? "border-[#EAB308]/40 bg-[#EAB308]/15 text-[#FDE047]"
                      : scraperStatus.status === "completed"
                      ? "border-[#10B981]/40 bg-[#10B981]/15 text-[#34D399]"
                      : scraperStatus.status === "failed"
                      ? "border-rose-500/40 bg-rose-500/15 text-rose-300"
                      : "border-zinc-700 bg-zinc-900 text-zinc-300"
                  }`}
                >
                  <span
                    className={`h-1.5 w-1.5 rounded-full ${
                      scraperStatus.status === "running"
                        ? "animate-ping bg-[#EAB308]"
                        : scraperStatus.status === "completed"
                        ? "bg-[#10B981]"
                        : scraperStatus.status === "failed"
                        ? "bg-rose-400"
                        : "bg-zinc-400"
                    }`}
                  />
                  {scraperStatus.status}
                </span>
              ) : (
                <span className="rounded-full border border-zinc-800 bg-zinc-900 px-2.5 py-0.5 font-mono text-[11px] text-zinc-400">
                  API: {getApiBaseUrl()}
                </span>
              )}
            </div>
            <p className="mt-1 text-xs text-zinc-400">
              {scraperStatus
                ? `Synced: ${scraperStatus.records_synced} movies • Reconciled: ${scraperStatus.movies_reconciled}${
                    scraperStatus.duration_sec !== null
                      ? ` • Duration: ${scraperStatus.duration_sec.toFixed(1)}s`
                      : ""
                  }`
                : "Trigger on-demand CineTracker BO, Trade Syndicate, or Social Pulse feeds via FastAPI."}
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-2.5">
            <select
              aria-label="Scraper source"
              value={scrapeSource}
              onChange={(e) => setScrapeSource(e.target.value as ScraperSourceOption)}
              className="rounded-xl border border-zinc-700 bg-[#09090B] px-3 py-2 text-xs font-medium text-white focus:border-[#EAB308] focus:outline-none"
            >
              <option value="all">All Feeds</option>
              <option value="cinetracker_bo">CineTracker BO</option>
              <option value="cinetracker_trade">CineTracker Trade</option>
              <option value="cinetracker_pulse">CineTracker Pulse</option>
            </select>

            <select
              aria-label="Scraper language"
              value={scrapeLanguage}
              onChange={(e) => setScrapeLanguage(e.target.value as ScraperLanguageOption)}
              className="rounded-xl border border-zinc-700 bg-[#09090B] px-3 py-2 text-xs font-medium text-white focus:border-[#EAB308] focus:outline-none"
            >
              <option value="all">All Languages</option>
              <option value="malayalam">Malayalam</option>
              <option value="tamil">Tamil</option>
              <option value="hindi">Hindi</option>
              <option value="telugu">Telugu</option>
              <option value="kannada">Kannada</option>
              <option value="pan-india">Pan-India</option>
            </select>

            <button
              type="button"
              onClick={() => void handleTriggerScrape()}
              disabled={triggeringScrape || scraperStatus?.status === "running"}
              className="inline-flex items-center gap-1.5 rounded-xl bg-[#EAB308] px-4 py-2 text-xs font-bold text-black shadow-lg shadow-[#EAB308]/15 transition hover:bg-[#FACC15] disabled:cursor-not-allowed disabled:opacity-60"
            >
              {scraperStatus?.status === "running" || triggeringScrape ? (
                <>
                  <RefreshCw className="h-3.5 w-3.5 animate-spin" />
                  Running...
                </>
              ) : (
                <>
                  <Play className="h-3.5 w-3.5 fill-current" />
                  Trigger Live Scrape
                </>
              )}
            </button>

            <button
              type="button"
              onClick={() => setShowLogs((prev) => !prev)}
              className="inline-flex items-center gap-1.5 rounded-xl border border-zinc-700 bg-[#09090B] px-3 py-2 text-xs font-medium text-zinc-300 hover:border-zinc-600 hover:text-white"
            >
              <Terminal className="h-3.5 w-3.5 text-[#10B981]" />
              {showLogs ? "Hide Logs" : "Live Logs"}
            </button>
          </div>
        </div>

        {apiError && (
          <div className="mt-3 flex items-center gap-2 rounded-xl border border-rose-500/40 bg-rose-500/10 px-3.5 py-2.5 text-xs text-rose-300">
            <AlertTriangle className="h-4 w-4 shrink-0" />
            <span>API Connection Notice: {apiError}</span>
          </div>
        )}

        {scraperStatus?.error_message && (
          <div className="mt-3 flex items-center gap-2 rounded-xl border border-amber-500/40 bg-amber-500/10 px-3.5 py-2.5 text-xs text-amber-200">
            <AlertTriangle className="h-4 w-4 shrink-0 text-amber-400" />
            <span>Last Job Error: {scraperStatus.error_message}</span>
          </div>
        )}

        {(scraperStatus?.last_run_report?.errors?.length ?? 0) > 0 && (
          <div className="mt-3 rounded-xl border border-amber-500/30 bg-amber-500/10 p-3 text-xs text-amber-200">
            <p className="font-semibold">
              Warnings / Isolated Movie Errors ({scraperStatus?.last_run_report?.errors?.length}):
            </p>
            <ul className="mt-1 list-disc space-y-0.5 pl-4 text-[11px] text-amber-200/85">
              {(scraperStatus?.last_run_report?.errors ?? []).slice(0, 5).map((err, idx) => (
                <li key={idx}>
                  [{err.source ?? err.stage}] {err.movie_title ? `${err.movie_title}: ` : ""}
                  {err.message}
                </li>
              ))}
            </ul>
          </div>
        )}

        {showLogs && (
          <div className="mt-4 rounded-xl border border-zinc-800 bg-[#09090B] p-3">
            <div className="mb-2 flex items-center justify-between text-[11px] text-zinc-400">
              <span className="font-mono">scraper/logs/scraper.log (latest lines)</span>
              {session?.access_token && (
                <button
                  type="button"
                  onClick={() => void loadScraperStatus(session.access_token)}
                  className="inline-flex items-center gap-1 text-zinc-300 hover:text-white"
                >
                  <RefreshCw className="h-3 w-3" /> Refresh
                </button>
              )}
            </div>
            <pre className="max-h-52 overflow-auto font-mono text-[11px] leading-relaxed text-zinc-300">
              {scraperStatus?.recent_logs?.length
                ? scraperStatus.recent_logs.join("\n")
                : "No log output captured yet."}
            </pre>
          </div>
        )}
      </section>

      {lockError && (
        <div className="flex items-center justify-between gap-2 rounded-xl border border-rose-500/40 bg-rose-500/10 px-4 py-2.5 text-xs text-rose-300">
          <span>{lockError}</span>
          <button
            type="button"
            onClick={() => setLockError(null)}
            className="text-rose-200 hover:text-white"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      )}

      {/* Filters Bar */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setFilterMode("all")}
            className={`rounded-xl px-3 py-1.5 text-xs font-semibold ${
              filterMode === "all"
                ? "bg-[#EAB308] text-black"
                : "border border-zinc-800 bg-[#18181B] text-zinc-300"
            }`}
          >
            All ({movies.length})
          </button>
          <button
            type="button"
            onClick={() => setFilterMode("conflicts")}
            className={`inline-flex items-center gap-1.5 rounded-xl px-3 py-1.5 text-xs font-semibold ${
              filterMode === "conflicts"
                ? "bg-amber-500 text-black"
                : "border border-zinc-800 bg-[#18181B] text-amber-300"
            }`}
          >
            <AlertTriangle className="h-3.5 w-3.5" />
            Conflicts ({conflictCount})
          </button>
          <button
            type="button"
            onClick={() => setFilterMode("locked")}
            className={`inline-flex items-center gap-1.5 rounded-xl px-3 py-1.5 text-xs font-semibold ${
              filterMode === "locked"
                ? "bg-sky-500 text-black"
                : "border border-zinc-800 bg-[#18181B] text-sky-300"
            }`}
          >
            <Lock className="h-3.5 w-3.5" />
            Locked ({lockedCount})
          </button>
        </div>

        <div className="relative w-full sm:w-64">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-zinc-500" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Filter table..."
            className="w-full rounded-xl border border-zinc-800 bg-[#18181B] py-1.5 pl-8 pr-3 text-xs text-white focus:border-[#EAB308] focus:outline-none"
          />
        </div>
      </div>

      {/* Sortable Data Table */}
      <div className="overflow-x-auto rounded-2xl border border-zinc-800 bg-[#18181B]">
        <table className="w-full text-left text-xs">
          <thead className="border-b border-zinc-800 bg-[#09090B] text-[11px] uppercase tracking-wider text-zinc-400">
            <tr>
              <th className="px-4 py-3">
                <button
                  type="button"
                  onClick={() => toggleSort("title")}
                  className="inline-flex items-center gap-1 hover:text-white"
                >
                  Movie <ArrowDownUp className="h-3 w-3" />
                </button>
              </th>
              <th className="px-3 py-3 text-right">
                <button
                  type="button"
                  onClick={() => toggleSort("india_net_cr")}
                  className="inline-flex items-center gap-1 hover:text-white"
                >
                  India Net <ArrowDownUp className="h-3 w-3" />
                </button>
              </th>
              <th className="px-3 py-3 text-right">
                <button
                  type="button"
                  onClick={() => toggleSort("worldwide_gross_cr")}
                  className="inline-flex items-center gap-1 hover:text-white"
                >
                  WW Gross <ArrowDownUp className="h-3 w-3" />
                </button>
              </th>
              <th className="px-3 py-3 text-right">
                <button
                  type="button"
                  onClick={() => toggleSort("day_count")}
                  className="inline-flex items-center gap-1 hover:text-white"
                >
                  Days <ArrowDownUp className="h-3 w-3" />
                </button>
              </th>
              <th className="px-3 py-3">Verdict</th>
              <th className="px-3 py-3">
                <button
                  type="button"
                  onClick={() => toggleSort("variance_flag")}
                  className="inline-flex items-center gap-1 hover:text-white"
                >
                  Audit <ArrowDownUp className="h-3 w-3" />
                </button>
              </th>
              <th className="px-3 py-3">Override Lock</th>
              <th className="px-3 py-3">
                <button
                  type="button"
                  onClick={() => toggleSort("last_scraped_at")}
                  className="inline-flex items-center gap-1 hover:text-white"
                >
                  Updated <ArrowDownUp className="h-3 w-3" />
                </button>
              </th>
              <th className="px-4 py-3 text-right">Edit</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-800/70">
            {filteredAndSorted.map((movie) => (
              <tr
                key={movie.movie_slug}
                className={
                  movie.variance_flag
                    ? "border-l-2 border-l-amber-500 bg-amber-500/10 hover:bg-amber-500/15"
                    : "hover:bg-zinc-900/50"
                }
              >
                <td className="px-4 py-3">
                  <p className="font-semibold text-white">{movie.title}</p>
                  <p className="text-[11px] text-zinc-400">
                    {movie.language} • <span>{formatSourceLabel(movie.primary_source)}</span>
                  </p>
                </td>
                <td className="px-3 py-3 text-right font-mono font-semibold text-[#10B981]">
                  {formatCrores(movie.india_net_cr)}
                </td>
                <td className="px-3 py-3 text-right font-mono font-semibold text-[#EAB308]">
                  {formatCrores(movie.worldwide_gross_cr)}
                </td>
                <td className="px-3 py-3 text-right font-mono text-zinc-200">
                  {movie.day_count}
                </td>
                <td className="px-3 py-3 text-zinc-300">{movie.verdict ?? "—"}</td>
                <td className="px-3 py-3">
                  {movie.variance_flag ? (
                    <span className="inline-flex items-center gap-1 rounded-md border border-amber-500/40 bg-amber-500/20 px-2 py-0.5 text-[11px] font-semibold text-amber-300">
                      <AlertTriangle className="h-3 w-3" />
                      Conflict
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1 text-[#34D399]">
                      <CheckCircle2 className="h-3.5 w-3.5" />
                      OK
                    </span>
                  )}
                </td>
                <td className="px-3 py-3">
                  <button
                    type="button"
                    onClick={() => void handleQuickToggleLock(movie)}
                    className={`inline-flex items-center gap-1 rounded-lg border px-2 py-1 text-[11px] font-semibold transition ${
                      movie.manual_override
                        ? "border-sky-500/40 bg-sky-500/15 text-sky-300"
                        : "border-zinc-700 bg-zinc-900 text-zinc-400 hover:text-zinc-200"
                    }`}
                  >
                    {movie.manual_override ? (
                      <>
                        <Lock className="h-3 w-3" /> Locked
                      </>
                    ) : (
                      <>
                        <Unlock className="h-3 w-3" /> Unlocked
                      </>
                    )}
                  </button>
                </td>
                <td className="px-3 py-3 text-zinc-400">
                  {formatExactTimestamp(movie.last_scraped_at)}
                </td>
                <td className="px-4 py-3 text-right">
                  <button
                    type="button"
                    onClick={() => openEditDrawer(movie)}
                    className="inline-flex items-center gap-1 rounded-lg border border-zinc-700 bg-[#09090B] px-2.5 py-1 text-xs font-medium text-zinc-200 hover:border-[#EAB308] hover:text-[#EAB308]"
                  >
                    <Edit3 className="h-3 w-3" />
                    Edit
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Edit & Lock Drawer */}
      {editingMovie && editForm && (
        <div className="fixed inset-0 z-50 flex justify-end bg-black/75 backdrop-blur-sm">
          <div className="flex h-full w-full max-w-xl flex-col overflow-y-auto border-l border-zinc-800 bg-[#09090B] p-6">
            <div className="flex items-center justify-between border-b border-zinc-800 pb-4">
              <div>
                <h2 className="font-display text-lg font-bold text-white">
                  Edit &amp; Lock: {editingMovie.title}
                </h2>
                <p className="font-mono text-[11px] text-zinc-400">{editingMovie.movie_slug}</p>
              </div>
              <button
                type="button"
                onClick={() => setEditingMovie(null)}
                className="rounded-lg border border-zinc-800 p-2 text-zinc-400 hover:text-white"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <div className="mt-5 space-y-4 text-xs">
              {editError && (
                <div className="rounded-xl border border-rose-500/40 bg-rose-500/10 p-3 text-rose-300">
                  {editError}
                </div>
              )}

              {/* Manual Override Lock Toggle */}
              <label className="flex cursor-pointer items-center justify-between rounded-xl border border-sky-500/35 bg-sky-500/10 p-3.5">
                <div>
                  <p className="font-semibold text-sky-200">Manual Override Financial Lock</p>
                  <p className="mt-0.5 text-[11px] text-sky-300/80">
                    When enabled, the hourly Python scraper preserves financial numbers &amp; verdict.
                  </p>
                </div>
                <input
                  type="checkbox"
                  checked={editForm.manual_override}
                  onChange={(e) =>
                    setEditForm({ ...editForm, manual_override: e.target.checked })
                  }
                  className="h-4 w-4 accent-sky-400"
                />
              </label>

              <label className="flex cursor-pointer items-center justify-between rounded-xl border border-zinc-800 bg-[#18181B] p-3">
                <span className="font-medium text-zinc-200">Mark Variance Resolved (Clear Conflict)</span>
                <input
                  type="checkbox"
                  checked={!editForm.variance_flag}
                  onChange={(e) =>
                    setEditForm({ ...editForm, variance_flag: !e.target.checked })
                  }
                  className="h-4 w-4 accent-[#10B981]"
                />
              </label>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-zinc-400">India Net (Cr)</label>
                  <input
                    type="number"
                    step="0.01"
                    value={editForm.india_net_cr}
                    onChange={(e) =>
                      setEditForm({ ...editForm, india_net_cr: e.target.value })
                    }
                    className="mt-1 w-full rounded-lg border border-zinc-700 bg-[#18181B] px-3 py-2 font-mono text-white"
                  />
                </div>
                <div>
                  <label className="block text-zinc-400">Worldwide Gross (Cr)</label>
                  <input
                    type="number"
                    step="0.01"
                    value={editForm.worldwide_gross_cr}
                    onChange={(e) =>
                      setEditForm({ ...editForm, worldwide_gross_cr: e.target.value })
                    }
                    className="mt-1 w-full rounded-lg border border-zinc-700 bg-[#18181B] px-3 py-2 font-mono text-white"
                  />
                </div>
                <div>
                  <label className="block text-zinc-400">India Gross (Cr)</label>
                  <input
                    type="number"
                    step="0.01"
                    value={editForm.india_gross_cr}
                    onChange={(e) =>
                      setEditForm({ ...editForm, india_gross_cr: e.target.value })
                    }
                    className="mt-1 w-full rounded-lg border border-zinc-700 bg-[#18181B] px-3 py-2 font-mono text-white"
                  />
                </div>
                <div>
                  <label className="block text-zinc-400">Overseas (Cr)</label>
                  <input
                    type="number"
                    step="0.01"
                    value={editForm.overseas_cr}
                    onChange={(e) =>
                      setEditForm({ ...editForm, overseas_cr: e.target.value })
                    }
                    className="mt-1 w-full rounded-lg border border-zinc-700 bg-[#18181B] px-3 py-2 font-mono text-white"
                  />
                </div>
                <div>
                  <label className="block text-zinc-400">Budget (Cr)</label>
                  <input
                    type="number"
                    step="0.01"
                    value={editForm.budget_cr}
                    onChange={(e) =>
                      setEditForm({ ...editForm, budget_cr: e.target.value })
                    }
                    className="mt-1 w-full rounded-lg border border-zinc-700 bg-[#18181B] px-3 py-2 font-mono text-white"
                  />
                </div>
                <div>
                  <label className="block text-zinc-400">Verdict</label>
                  <select
                    value={editForm.verdict}
                    onChange={(e) =>
                      setEditForm({ ...editForm, verdict: e.target.value })
                    }
                    className="mt-1 w-full rounded-lg border border-zinc-700 bg-[#18181B] px-3 py-2 text-white"
                  >
                    {VERDICT_OPTIONS.map((v) => (
                      <option key={v || "none"} value={v}>
                        {v || "— None —"}
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              {/* Daily Breakdown Row Editor */}
              <div className="pt-2">
                <div className="mb-2 flex items-center justify-between">
                  <h3 className="font-semibold text-white">Daily Breakdown Entries</h3>
                  <button
                    type="button"
                    onClick={() => {
                      const nextDay =
                        editForm.daily_breakdown.length > 0
                          ? Math.max(...editForm.daily_breakdown.map((d) => d.day)) + 1
                          : 1;
                      setEditForm({
                        ...editForm,
                        daily_breakdown: [
                          ...editForm.daily_breakdown,
                          { day: nextDay, date: null, india_net_cr: 0, change_pct: null },
                        ],
                      });
                    }}
                    className="inline-flex items-center gap-1 rounded-lg border border-zinc-700 bg-[#18181B] px-2.5 py-1 text-[11px] font-medium text-[#10B981]"
                  >
                    <Plus className="h-3 w-3" /> Add Day
                  </button>
                </div>
                <div className="max-h-56 space-y-2 overflow-y-auto pr-1">
                  {editForm.daily_breakdown.map((row, idx) => (
                    <div
                      key={`${row.day}-${idx}`}
                      className="grid grid-cols-[64px_1fr_92px_32px] items-center gap-2 rounded-lg border border-zinc-800 bg-[#18181B] p-2"
                    >
                      <input
                        type="number"
                        value={row.day}
                        onChange={(e) => {
                          const next = [...editForm.daily_breakdown];
                          next[idx] = { ...row, day: Number(e.target.value) };
                          setEditForm({ ...editForm, daily_breakdown: next });
                        }}
                        className="rounded border border-zinc-700 bg-[#09090B] px-2 py-1 font-mono text-white"
                      />
                      <input
                        type="text"
                        placeholder="YYYY-MM-DD"
                        value={row.date ?? ""}
                        onChange={(e) => {
                          const next = [...editForm.daily_breakdown];
                          next[idx] = { ...row, date: e.target.value || null };
                          setEditForm({ ...editForm, daily_breakdown: next });
                        }}
                        className="rounded border border-zinc-700 bg-[#09090B] px-2 py-1 font-mono text-zinc-200"
                      />
                      <input
                        type="number"
                        step="0.01"
                        value={row.india_net_cr}
                        onChange={(e) => {
                          const next = [...editForm.daily_breakdown];
                          next[idx] = { ...row, india_net_cr: Number(e.target.value) };
                          setEditForm({ ...editForm, daily_breakdown: next });
                        }}
                        className="rounded border border-zinc-700 bg-[#09090B] px-2 py-1 text-right font-mono text-[#10B981]"
                      />
                      <button
                        type="button"
                        onClick={() => {
                          const next = editForm.daily_breakdown.filter((_, i) => i !== idx);
                          setEditForm({ ...editForm, daily_breakdown: next });
                        }}
                        className="flex h-7 w-7 items-center justify-center rounded text-zinc-500 hover:text-rose-400"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            </div>

            <div className="mt-auto flex items-center justify-end gap-2 border-t border-zinc-800 pt-4">
              <button
                type="button"
                onClick={() => setEditingMovie(null)}
                className="rounded-xl border border-zinc-700 px-4 py-2 text-xs font-medium text-zinc-300"
              >
                Cancel
              </button>
              <button
                type="button"
                disabled={savingEdit}
                onClick={() => void handleSaveEdit()}
                className="rounded-xl bg-[#EAB308] px-4 py-2 text-xs font-bold text-black hover:bg-[#FACC15] disabled:opacity-60"
              >
                {savingEdit ? "Saving..." : "Save Override Changes"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Add Manual Movie Modal (TMDB Search) */}
      {showAddModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 p-4 backdrop-blur-sm">
          <div className="max-h-[90vh] w-full max-w-2xl overflow-y-auto rounded-2xl border border-zinc-800 bg-[#09090B] p-6 shadow-2xl">
            <div className="flex items-center justify-between border-b border-zinc-800 pb-3">
              <h2 className="font-display text-lg font-bold text-white">
                Add Movie Manually via TMDB
              </h2>
              <button
                type="button"
                onClick={() => setShowAddModal(false)}
                className="rounded-lg border border-zinc-800 p-1.5 text-zinc-400 hover:text-white"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            {/* TMDB Search Bar */}
            <div className="mt-4 rounded-xl border border-zinc-800 bg-[#18181B] p-3.5">
              <label className="block text-xs font-semibold text-zinc-200">
                1. Lookup Metadata on TMDB
              </label>
              <div className="mt-2 flex gap-2">
                <input
                  type="text"
                  value={tmdbQuery}
                  onChange={(e) => setTmdbQuery(e.target.value)}
                  placeholder={
                    getTmdbApiKey()
                      ? "Search TMDB movie title..."
                      : "Set VITE_TMDB_API_KEY in .env to enable live search"
                  }
                  className="flex-1 rounded-lg border border-zinc-700 bg-[#09090B] px-3 py-2 text-xs text-white focus:border-[#EAB308] focus:outline-none"
                />
                <button
                  type="button"
                  onClick={() => void handleTmdbSearch()}
                  disabled={searchingTmdb || !tmdbQuery.trim()}
                  className="rounded-lg bg-[#EAB308] px-3.5 py-2 text-xs font-bold text-black disabled:opacity-50"
                >
                  {searchingTmdb ? "Searching..." : "Search TMDB"}
                </button>
              </div>
              {tmdbSearchErr && <p className="mt-2 text-xs text-rose-400">{tmdbSearchErr}</p>}
              {tmdbResults.length > 0 && (
                <div className="mt-3 grid max-h-48 gap-2 overflow-y-auto sm:grid-cols-2">
                  {tmdbResults.map((cand) => (
                    <button
                      key={cand.tmdb_id}
                      type="button"
                      onClick={() => void applyTmdbCandidate(cand)}
                      className="flex items-center gap-2.5 rounded-lg border border-zinc-800 bg-[#09090B] p-2 text-left hover:border-[#EAB308]"
                    >
                      {cand.poster_url ? (
                        <img
                          src={cand.poster_url}
                          alt={cand.title}
                          className="h-12 w-8 rounded object-cover"
                        />
                      ) : (
                        <div className="h-12 w-8 rounded bg-zinc-800" />
                      )}
                      <div className="min-w-0">
                        <p className="truncate text-xs font-semibold text-white">{cand.title}</p>
                        <p className="text-[11px] text-zinc-400">
                          {cand.release_date ?? "TBA"} • {mapIsoLanguage(cand.original_language)}
                        </p>
                      </div>
                    </button>
                  ))}
                </div>
              )}
            </div>

            <form onSubmit={(e) => void handleCreateManualMovie(e)} className="mt-4 space-y-3 text-xs">
              {newErr && (
                <div className="rounded-lg border border-rose-500/40 bg-rose-500/10 p-2.5 text-rose-300">
                  {newErr}
                </div>
              )}
              <div className="grid gap-3 sm:grid-cols-2">
                <div>
                  <label className="block text-zinc-400">Title *</label>
                  <input
                    type="text"
                    required
                    value={manualForm.title}
                    onChange={(e) =>
                      setManualForm({
                        ...manualForm,
                        title: e.target.value,
                        movie_slug: slugifyTitle(e.target.value),
                      })
                    }
                    className="mt-1 w-full rounded-lg border border-zinc-700 bg-[#18181B] px-3 py-2 text-white"
                  />
                </div>
                <div>
                  <label className="block text-zinc-400">Canonical Slug</label>
                  <input
                    type="text"
                    value={manualForm.movie_slug}
                    onChange={(e) =>
                      setManualForm({ ...manualForm, movie_slug: e.target.value })
                    }
                    className="mt-1 w-full rounded-lg border border-zinc-700 bg-[#18181B] px-3 py-2 font-mono text-zinc-200"
                  />
                </div>
                <div>
                  <label className="block text-zinc-400">Language</label>
                  <select
                    value={manualForm.language}
                    onChange={(e) =>
                      setManualForm({ ...manualForm, language: e.target.value })
                    }
                    className="mt-1 w-full rounded-lg border border-zinc-700 bg-[#18181B] px-3 py-2 text-white"
                  >
                    {MOVIE_LANGUAGES.map((lang) => (
                      <option key={lang} value={lang}>
                        {lang}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="block text-zinc-400">Release Date</label>
                  <input
                    type="date"
                    value={manualForm.release_date}
                    onChange={(e) =>
                      setManualForm({ ...manualForm, release_date: e.target.value })
                    }
                    className="mt-1 w-full rounded-lg border border-zinc-700 bg-[#18181B] px-3 py-2 text-white"
                  />
                </div>
                <div>
                  <label className="block text-zinc-400">India Net (Cr)</label>
                  <input
                    type="number"
                    step="0.01"
                    value={manualForm.india_net_cr}
                    onChange={(e) =>
                      setManualForm({ ...manualForm, india_net_cr: e.target.value })
                    }
                    className="mt-1 w-full rounded-lg border border-zinc-700 bg-[#18181B] px-3 py-2 font-mono text-white"
                  />
                </div>
                <div>
                  <label className="block text-zinc-400">Worldwide Gross (Cr)</label>
                  <input
                    type="number"
                    step="0.01"
                    value={manualForm.worldwide_gross_cr}
                    onChange={(e) =>
                      setManualForm({ ...manualForm, worldwide_gross_cr: e.target.value })
                    }
                    className="mt-1 w-full rounded-lg border border-zinc-700 bg-[#18181B] px-3 py-2 font-mono text-white"
                  />
                </div>
                <div>
                  <label className="block text-zinc-400">Budget (Cr)</label>
                  <input
                    type="number"
                    step="0.01"
                    value={manualForm.budget_cr}
                    onChange={(e) =>
                      setManualForm({ ...manualForm, budget_cr: e.target.value })
                    }
                    className="mt-1 w-full rounded-lg border border-zinc-700 bg-[#18181B] px-3 py-2 font-mono text-white"
                  />
                </div>
                <div>
                  <label className="block text-zinc-400">Verdict</label>
                  <select
                    value={manualForm.verdict}
                    onChange={(e) =>
                      setManualForm({ ...manualForm, verdict: e.target.value })
                    }
                    className="mt-1 w-full rounded-lg border border-zinc-700 bg-[#18181B] px-3 py-2 text-white"
                  >
                    {VERDICT_OPTIONS.map((v) => (
                      <option key={v || "none"} value={v}>
                        {v || "— None —"}
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              <label className="flex items-center gap-2 pt-1 text-zinc-300">
                <input
                  type="checkbox"
                  checked={manualForm.manual_override}
                  onChange={(e) =>
                    setManualForm({ ...manualForm, manual_override: e.target.checked })
                  }
                  className="h-4 w-4 accent-sky-400"
                />
                Lock financials immediately (manual_override = true)
              </label>

              <div className="flex justify-end gap-2 border-t border-zinc-800 pt-4">
                <button
                  type="button"
                  onClick={() => setShowAddModal(false)}
                  className="rounded-xl border border-zinc-700 px-4 py-2 text-zinc-300"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={savingNew}
                  className="rounded-xl bg-[#10B981] px-4 py-2 font-bold text-black hover:bg-emerald-400 disabled:opacity-60"
                >
                  {savingNew ? "Creating..." : "Publish Movie to Supabase"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
