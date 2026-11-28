import { motion } from "framer-motion";
import { AlertTriangle, CheckCircle2, Clock, GitCompare, Lock, Play } from "lucide-react";
import {
  computeBudgetRecoveryPct,
  formatCrores,
  formatRelativeTime,
  getLatestDayStats,
  getVerdictStyle,
  isMovieLiveRunning,
} from "../../lib/formatters";
import type { MovieRecord } from "../../lib/supabase";
import { MoviePoster } from "./MoviePoster";

interface MovieCardProps {
  movie: MovieRecord;
  index: number;
  onSelect: (movie: MovieRecord) => void;
  onToggleCompare: (movie: MovieRecord) => void;
  onPlayTrailer?: (movie: MovieRecord) => void;
  isCompared: boolean;
}

export function MovieCard({
  movie,
  index,
  onSelect,
  onToggleCompare,
  onPlayTrailer,
  isCompared,
}: MovieCardProps) {
  const recoveryPct = computeBudgetRecoveryPct(movie);
  const verdictMeta = getVerdictStyle(movie.verdict);
  const clampedPct = recoveryPct !== null ? Math.min(100, Math.max(0, recoveryPct)) : 0;
  const isLive = isMovieLiveRunning(movie);
  const latestDay = getLatestDayStats(movie);

  return (
    <motion.article
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.24, delay: Math.min(index * 0.015, 0.18) }}
      className="group relative flex min-w-0 flex-col overflow-hidden rounded-2xl border border-white/[0.08] bg-[#12151E] shadow-lg transition-all duration-200 hover:-translate-y-1 hover:border-white/[0.18] hover:shadow-2xl hover:shadow-black/60"
    >
      {/* Vertical 2:3 Theatrical Poster */}
      <div className="relative aspect-[2/3] w-full overflow-hidden bg-[#090A0F]">
        <button
          type="button"
          onClick={() => onSelect(movie)}
          className="block h-full w-full text-left focus:outline-none"
        >
          <MoviePoster
            movie={movie}
            srcOverride={movie.poster_url || movie.backdrop_url || ""}
            className="h-full w-full object-cover object-center transition-transform duration-500 group-hover:scale-105"
          />
          <div className="pointer-events-none absolute inset-0 bg-gradient-to-t from-[#12151E] via-[#12151E]/25 to-transparent" />
        </button>

        {/* Floating Top Pills: Language + Day N Live */}
        <div className="pointer-events-none absolute left-2 right-2 top-2 flex items-center justify-between gap-1 sm:left-3 sm:right-3 sm:top-3 sm:gap-2">
          <span className="truncate rounded-lg border border-white/15 bg-[#090A0F]/80 px-1.5 py-0.5 text-[10px] font-semibold text-zinc-100 backdrop-blur-md sm:px-2 sm:text-[11px]">
            {movie.language}
          </span>
          <span
            className={`inline-flex shrink-0 items-center gap-1 rounded-lg border px-1.5 py-0.5 font-mono text-[9px] font-bold uppercase tracking-wider backdrop-blur-md sm:px-2 sm:text-[10px] ${
              isLive
                ? "border-[#10B981]/50 bg-[#090A0F]/85 text-[#34D399]"
                : "border-white/15 bg-[#090A0F]/80 text-zinc-200"
            }`}
          >
            {isLive && <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-[#10B981]" />}
            Day {movie.day_count}
          </span>
        </div>

        {/* Bottom Poster Tags: Verdict + Verification / Quick Trailer Play */}
        <div className="absolute bottom-2 left-2 right-2 flex items-center justify-between gap-1 sm:bottom-2.5 sm:left-3 sm:right-3 sm:gap-2">
          <span
            className={`pointer-events-none truncate rounded-md px-1.5 py-0.5 text-[9px] font-semibold backdrop-blur-md sm:px-2 sm:text-[10px] ${verdictMeta.className}`}
          >
            {verdictMeta.label}
          </span>
          <div className="flex shrink-0 items-center gap-1">
            {movie.trailer_youtube_id && onPlayTrailer && (
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  onPlayTrailer(movie);
                }}
                aria-label={`Watch ${movie.title} trailer`}
                title="Watch Official Trailer"
                className="inline-flex h-6 w-6 items-center justify-center rounded-full border border-[#F59E0B]/60 bg-[#090A0F]/90 text-[#F59E0B] shadow-md backdrop-blur-md transition hover:bg-[#F59E0B] hover:text-black sm:h-7 sm:w-7"
              >
                <Play className="h-3 w-3 fill-current" />
              </button>
            )}
            {movie.variance_flag ? (
              <span
                title="Sources diverge by >25% — flagged for review"
                className="pointer-events-none hidden items-center gap-1 rounded-md border border-[#F59E0B]/40 bg-[#090A0F]/80 px-1.5 py-0.5 text-[10px] font-medium text-[#FCD34D] backdrop-blur-md sm:inline-flex"
              >
                <AlertTriangle className="h-3 w-3" />
                Conflict
              </span>
            ) : (
              <span
                title="Cross-source validated"
                className="pointer-events-none hidden items-center gap-1 rounded-md border border-[#10B981]/30 bg-[#090A0F]/75 px-1.5 py-0.5 text-[10px] font-medium text-[#34D399] backdrop-blur-md sm:inline-flex"
              >
                <CheckCircle2 className="h-3 w-3" />
                Verified
              </span>
            )}
          </div>
        </div>
      </div>

      {/* Card Body */}
      <div className="flex flex-1 flex-col justify-between gap-2 p-2.5 sm:gap-3 sm:p-4">
        <div className="min-w-0">
          <div className="flex items-start justify-between gap-1.5 sm:gap-2">
            <button
              type="button"
              onClick={() => onSelect(movie)}
              className="min-w-0 text-left focus:outline-none"
            >
              <h3 className="line-clamp-1 font-display text-xs font-bold text-white transition-colors group-hover:text-[#F59E0B] sm:text-base">
                {movie.title}
              </h3>
            </button>
            {movie.manual_override && (
              <span title="Locked by Admin Override" className="shrink-0 text-sky-400">
                <Lock className="h-3 w-3 sm:h-3.5 sm:w-3.5" />
              </span>
            )}
          </div>

          <div className="mt-1 flex items-center justify-between gap-1 text-[10px] text-zinc-500 sm:gap-2 sm:text-[11px]">
            <span className="truncate">
              {movie.release_date ? movie.release_date : "TBA"}
            </span>
            <span className="inline-flex shrink-0 items-center gap-0.5 font-mono text-[9px] tabular-nums text-zinc-400 sm:gap-1 sm:text-[10px]">
              <Clock className="h-2.5 w-2.5 text-zinc-500" />
              {formatRelativeTime(movie.last_scraped_at)}
            </span>
          </div>
        </div>

        {/* Crisp 2-Column Financial Grid */}
        <div className="grid grid-cols-2 gap-1.5 rounded-xl border border-white/[0.07] bg-[#090A0F]/65 p-2 sm:gap-2 sm:p-2.5">
          <div className="min-w-0">
            <p className="text-[9px] uppercase tracking-wider text-zinc-500 sm:text-[10px]">
              India Net
            </p>
            <p className="mt-0.5 truncate whitespace-nowrap font-mono text-xs font-bold tabular-nums text-[#10B981] sm:text-sm">
              {formatCrores(movie.india_net_cr, { compact: true })}
            </p>
          </div>
          <div className="min-w-0">
            <p className="text-[9px] uppercase tracking-wider text-zinc-500 sm:text-[10px]">
              Worldwide
            </p>
            <p className="mt-0.5 truncate whitespace-nowrap font-mono text-xs font-bold tabular-nums text-[#F59E0B] sm:text-sm">
              {formatCrores(movie.worldwide_gross_cr, { compact: true })}
            </p>
          </div>
        </div>

        {latestDay && (
          <div className="hidden items-center justify-between rounded-lg border border-white/[0.05] bg-white/[0.02] px-2.5 py-1 text-[11px] sm:flex">
            <span className="text-zinc-400">Day {latestDay.day} Net</span>
            <span className="font-mono font-semibold tabular-nums text-zinc-100">
              {formatCrores(latestDay.india_net_cr, { compact: true })}
            </span>
          </div>
        )}

        {/* Budget Recovery Bar */}
        <div className="hidden sm:block">
          <div className="mb-1 flex items-center justify-between text-[11px]">
            <span className="truncate text-zinc-400">
              Budget:{" "}
              <span className="font-mono tabular-nums text-zinc-200">
                {formatCrores(movie.budget_cr, { compact: true })}
              </span>
            </span>
            <span className="font-mono font-semibold tabular-nums text-zinc-300">
              {recoveryPct !== null ? `${recoveryPct.toFixed(0)}%` : "N/A"}
            </span>
          </div>
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-white/[0.07]">
            <div
              className={`h-full rounded-full transition-all duration-500 ${
                recoveryPct === null
                  ? "bg-zinc-700"
                  : recoveryPct >= 200
                  ? "bg-[#F59E0B]"
                  : recoveryPct >= 100
                  ? "bg-[#10B981]"
                  : "bg-amber-600"
              }`}
              style={{ width: `${recoveryPct !== null ? clampedPct : 0}%` }}
            />
          </div>
        </div>

        {/* Footer Actions */}
        <div className="flex items-center justify-between gap-1 border-t border-white/[0.06] pt-2 sm:gap-2 sm:pt-2.5">
          <button
            type="button"
            onClick={() => onSelect(movie)}
            className="min-h-[32px] text-[11px] font-semibold text-zinc-200 transition hover:text-[#F59E0B] sm:text-xs"
          >
            <span className="hidden sm:inline">Full Breakdown →</span>
            <span className="sm:hidden">Breakdown →</span>
          </button>
          <button
            type="button"
            onClick={() => onToggleCompare(movie)}
            className={`inline-flex min-h-[32px] shrink-0 items-center gap-1 rounded-lg border px-1.5 py-1 text-[10px] font-medium transition sm:px-2 sm:text-[11px] ${
              isCompared
                ? "border-[#10B981]/50 bg-[#10B981]/15 text-[#34D399]"
                : "border-white/[0.08] bg-[#090A0F]/60 text-zinc-400 hover:border-white/20 hover:text-zinc-100"
            }`}
          >
            <GitCompare className="h-3 w-3" />
            <span className="hidden sm:inline">{isCompared ? "Added" : "Compare"}</span>
          </button>
        </div>
      </div>
    </motion.article>
  );
}
