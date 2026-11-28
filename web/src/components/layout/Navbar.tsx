import { Activity, GitCompare, RefreshCw, Search, Sparkles, X } from "lucide-react";
import { Link, useLocation } from "react-router-dom";
import { formatExactTimestamp, formatRelativeTime } from "../../lib/formatters";
import type { MovieRecord, RealtimeStatus } from "../../lib/supabase";
import { BrandLogo } from "../BrandLogo";
import { NotificationBell } from "./NotificationBell";

interface NavbarProps {
  movies: MovieRecord[];
  realtimeStatus: RealtimeStatus;
  latestScrapedAt: string | null;
  searchQuery: string;
  onSearchChange: (val: string) => void;
  onRefresh: () => void;
  refreshing: boolean;
  compareCount: number;
  activeTab: "trending" | "malayalam" | "compare" | "admin";
  onSelectMalayalam: () => void;
  onSelectTrending: () => void;
  onSelectMovie: (movie: MovieRecord) => void;
  onReplayIntro?: () => void;
}

export function Navbar({
  movies,
  realtimeStatus,
  latestScrapedAt,
  searchQuery,
  onSearchChange,
  onRefresh,
  refreshing,
  compareCount,
  activeTab,
  onSelectMalayalam,
  onSelectTrending,
  onSelectMovie,
  onReplayIntro,
}: NavbarProps) {
  const location = useLocation();
  const showSearch = location.pathname === "/";

  const statusConfig: Record<
    RealtimeStatus,
    { dot: string; label: string; badgeClass: string }
  > = {
    SUBSCRIBED: {
      dot: "bg-[#10B981] animate-pulse",
      label: "Live Sync",
      badgeClass: "border-[#10B981]/30 bg-[#10B981]/10 text-[#34D399]",
    },
    CONNECTING: {
      dot: "bg-[#F59E0B] animate-pulse",
      label: "Connecting",
      badgeClass: "border-[#F59E0B]/30 bg-[#F59E0B]/10 text-[#FCD34D]",
    },
    DISCONNECTED: {
      dot: "bg-rose-500",
      label: "Offline",
      badgeClass: "border-rose-500/30 bg-rose-500/10 text-rose-300",
    },
    UNCONFIGURED: {
      dot: "bg-zinc-500",
      label: "Setup Needed",
      badgeClass: "border-white/[0.08] bg-[#12151E] text-zinc-300",
    },
  };

  const statusMeta = statusConfig[realtimeStatus];

  return (
    <header className="sticky top-0 z-40 border-b border-white/[0.08] bg-[#090A0F]/85 backdrop-blur-xl">
      <div className="mx-auto flex max-w-7xl items-center justify-between gap-2 px-3 py-2.5 sm:gap-3 sm:px-6 sm:py-3">
        <div className="flex min-w-0 items-center gap-4 lg:gap-6">
          <Link
            to="/"
            onClick={() => {
              onSelectTrending();
              onReplayIntro?.();
            }}
            title="Replay CineTracker Intro"
            className="group flex min-w-0 items-center focus:outline-none"
          >
            <BrandLogo
              variant="full"
              size="sm"
              showLiveBadge={true}
              subtitle="Box Office Intelligence"
            />
          </Link>

          <nav className="hidden items-center gap-1 md:flex" aria-label="Primary Navigation">
            <Link
              to="/"
              onClick={onSelectTrending}
              className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium transition-colors ${
                activeTab === "trending"
                  ? "bg-white/[0.08] text-white"
                  : "text-zinc-400 hover:bg-white/[0.04] hover:text-zinc-100"
              }`}
            >
              <Activity className="h-3.5 w-3.5 text-[#F59E0B]" />
              Trending
            </Link>
            <Link
              to="/"
              onClick={onSelectMalayalam}
              className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium transition-colors ${
                activeTab === "malayalam"
                  ? "bg-white/[0.08] text-white"
                  : "text-zinc-400 hover:bg-white/[0.04] hover:text-zinc-100"
              }`}
            >
              <Sparkles className="h-3.5 w-3.5 text-[#10B981]" />
              Malayalam
            </Link>
            <Link
              to="/compare"
              className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium transition-colors ${
                activeTab === "compare"
                  ? "bg-white/[0.08] text-white"
                  : "text-zinc-400 hover:bg-white/[0.04] hover:text-zinc-100"
              }`}
            >
              <GitCompare className="h-3.5 w-3.5 text-sky-400" />
              Compare
              {compareCount > 0 && (
                <span className="ml-0.5 rounded-full bg-[#F59E0B] px-1.5 py-0.2 font-mono text-[11px] font-bold tabular-nums text-black">
                  {compareCount}
                </span>
              )}
            </Link>
          </nav>
        </div>

        <div className="flex shrink-0 items-center gap-1.5 sm:gap-2.5">
          {showSearch && (
            <div className="relative hidden w-48 lg:block xl:w-64">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-zinc-500" />
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => onSearchChange(e.target.value)}
                placeholder="Search title, language, cast..."
                className="w-full rounded-xl border border-white/[0.08] bg-[#12151E] py-1.5 pl-8 pr-7 text-xs text-zinc-100 placeholder:text-zinc-500 focus:border-[#F59E0B]/60 focus:outline-none"
              />
              {searchQuery && (
                <button
                  type="button"
                  onClick={() => onSearchChange("")}
                  aria-label="Clear search"
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-zinc-500 hover:text-zinc-200"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              )}
            </div>
          )}

          <div
            title={`Last scraped: ${formatExactTimestamp(latestScrapedAt)}`}
            className={`flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full border px-2 py-1 text-[11px] font-medium sm:gap-2 sm:px-2.5 sm:text-xs ${statusMeta.badgeClass}`}
          >
            <span className={`h-2 w-2 shrink-0 rounded-full ${statusMeta.dot}`} />
            <span className="hidden sm:inline">{statusMeta.label}</span>
            {latestScrapedAt && (
              <span className="font-mono text-[10px] tabular-nums opacity-85 sm:text-[11px]">
                {formatRelativeTime(latestScrapedAt)}
              </span>
            )}
          </div>

          <NotificationBell movies={movies} onSelectMovie={onSelectMovie} />

          <button
            type="button"
            onClick={onRefresh}
            disabled={refreshing}
            title="Sync latest snapshot"
            aria-label="Refresh box office snapshot"
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-white/[0.08] bg-[#12151E] text-zinc-300 transition hover:border-white/20 hover:text-white disabled:opacity-50"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${refreshing ? "animate-spin" : ""}`} />
          </button>
        </div>
      </div>

      {showSearch && (
        <div className="border-t border-white/[0.06] px-3 py-2 lg:hidden sm:px-6">
          <div className="relative">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-zinc-500" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => onSearchChange(e.target.value)}
              placeholder="Search movies, languages, or actors..."
              className="min-h-[38px] w-full rounded-xl border border-white/[0.08] bg-[#12151E] py-1.5 pl-8 pr-8 text-xs text-zinc-100 placeholder:text-zinc-500 focus:border-[#F59E0B]/60 focus:outline-none"
            />
            {searchQuery && (
              <button
                type="button"
                onClick={() => onSearchChange("")}
                aria-label="Clear mobile search"
                className="absolute right-2.5 top-1/2 -translate-y-1/2 text-zinc-500 hover:text-zinc-200"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            )}
          </div>
        </div>
      )}
    </header>
  );
}
