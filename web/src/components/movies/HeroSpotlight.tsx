import { motion } from "framer-motion";
import { ArrowUpRight, Calendar, Flame, GitCompare, Globe, Lock, PlayCircle } from "lucide-react";
import {
  formatCrores,
  formatSourceLabel,
  getLatestDayStats,
  getVerdictStyle,
  getYoutubeSearchUrl,
  isMovieLiveRunning,
} from "../../lib/formatters";
import type { MovieRecord } from "../../lib/supabase";
import { BrandLogo } from "../BrandLogo";
import { AnimatedNumber } from "./AnimatedNumber";
import { MoviePoster } from "./MoviePoster";

interface HeroSpotlightProps {
  movie: MovieRecord;
  onOpenDetails: (movie: MovieRecord) => void;
  onToggleCompare: (movie: MovieRecord) => void;
  onPlayTrailer?: (movie: MovieRecord) => void;
  isCompared: boolean;
}

export function HeroSpotlight({
  movie,
  onOpenDetails,
  onToggleCompare,
  onPlayTrailer,
  isCompared,
}: HeroSpotlightProps) {
  const verdictMeta = getVerdictStyle(movie.verdict);
  const latestDay = getLatestDayStats(movie);
  const isLive = isMovieLiveRunning(movie);
  const headlineGross = movie.worldwide_gross_cr ?? movie.india_gross_cr ?? movie.india_net_cr;
  const heroMetricLabel =
    movie.worldwide_gross_cr !== null ? "Worldwide Gross" : "India Net Total";

  return (
    <motion.section
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, ease: "easeOut" }}
      className="relative overflow-hidden rounded-2xl border border-white/[0.08] bg-[#12151E] shadow-2xl sm:rounded-3xl"
    >
      {/* Full-bleed atmospheric blurred backdrop */}
      <div className="pointer-events-none absolute inset-0 overflow-hidden">
        {movie.backdrop_url || movie.poster_url ? (
          <img
            src={movie.backdrop_url || movie.poster_url || ""}
            alt=""
            aria-hidden="true"
            loading="lazy"
            decoding="async"
            onError={(e) => {
              e.currentTarget.style.display = "none";
            }}
            className="h-full w-full scale-110 object-cover object-center opacity-30 blur-md"
          />
        ) : null}
        <div className="absolute inset-0 bg-gradient-to-br from-[#F59E0B]/10 via-[#090A0F]/80 to-[#10B981]/10" />
        <div className="absolute inset-0 bg-gradient-to-r from-[#090A0F] via-[#090A0F]/85 to-[#090A0F]/45" />
        <div className="absolute inset-0 bg-gradient-to-t from-[#090A0F] via-transparent to-transparent" />
      </div>

      <div className="relative z-10 grid gap-4 p-4 sm:gap-6 sm:p-8 lg:grid-cols-[auto_1fr_auto] lg:items-center">
        {/* Sharp 2:3 Theatrical Poster Frame */}
        <button
          type="button"
          onClick={() => onOpenDetails(movie)}
          className="group relative mx-auto aspect-[2/3] w-28 shrink-0 overflow-hidden rounded-2xl border border-white/[0.12] bg-[#090A0F] shadow-2xl transition-transform duration-300 hover:scale-[1.02] sm:mx-0 sm:w-44"
        >
          <MoviePoster
            movie={movie}
            srcOverride={movie.poster_url || movie.backdrop_url || ""}
            className="h-full w-full object-cover object-center transition-transform duration-500 group-hover:scale-105"
          />
          <div className="pointer-events-none absolute inset-0 ring-1 ring-inset ring-white/10" />
        </button>

        {/* Title, Badges, Live Day Pill & CTAs */}
        <div className="min-w-0 space-y-3 sm:space-y-4">
          <div className="flex flex-wrap items-center gap-1.5 sm:gap-2">
            <span className="inline-flex items-center gap-1.5 rounded-full border border-[#F59E0B]/35 bg-[#F59E0B]/10 py-0.5 pl-1 pr-2.5 text-[10px] font-semibold uppercase tracking-wider text-[#FCD34D] sm:text-[11px]">
              <BrandLogo variant="icon" size="sm" className="[&>svg]:h-4 [&>svg]:w-4" />
              #1 Spotlight
            </span>
            <span
              className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 font-mono text-[10px] font-bold sm:text-[11px] ${
                isLive
                  ? "border-[#10B981]/40 bg-[#10B981]/15 text-[#34D399]"
                  : "border-white/[0.1] bg-white/[0.05] text-zinc-200"
              }`}
            >
              {isLive && <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-[#10B981]" />}
              DAY {movie.day_count} {isLive ? "LIVE" : ""}
            </span>
            <span className="rounded-full border border-white/[0.1] bg-[#090A0F]/80 px-2.5 py-0.5 text-[11px] font-medium text-zinc-200 sm:text-xs">
              {movie.language}
            </span>
            <span className={`rounded-full px-2.5 py-0.5 text-[11px] font-semibold sm:text-xs ${verdictMeta.className}`}>
              {verdictMeta.label}
            </span>
            {movie.manual_override && (
              <span className="inline-flex items-center gap-1 rounded-full border border-sky-500/30 bg-sky-500/10 px-2 py-0.5 text-[11px] text-sky-300">
                <Lock className="h-3 w-3" /> Admin Verified
              </span>
            )}
          </div>

          <div className="space-y-1.5 sm:space-y-2">
            <h1 className="font-display text-2xl font-bold tracking-tight text-white sm:text-4xl">
              {movie.title}
            </h1>
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-zinc-400">
              {movie.release_date && (
                <span className="flex items-center gap-1">
                  <Calendar className="h-3.5 w-3.5 text-zinc-500" />
                  Released {movie.release_date}
                </span>
              )}
              <span className="flex items-center gap-1">
                <Globe className="h-3.5 w-3.5 text-zinc-500" />
                Feed: {formatSourceLabel(movie.primary_source)}
              </span>
              {movie.cast_summary && (
                <span className="line-clamp-1 text-zinc-300">{movie.cast_summary}</span>
              )}
            </div>
          </div>

          {latestDay && (
            <div className="inline-flex max-w-full flex-wrap items-center gap-1.5 rounded-xl border border-[#10B981]/25 bg-[#10B981]/10 px-3 py-1.5 text-[11px] sm:gap-2 sm:text-xs">
              <Flame className="h-3.5 w-3.5 shrink-0 text-[#F59E0B]" />
              <span className="font-medium text-zinc-200">
                Day {latestDay.day} India Net:
              </span>
              <span className="font-mono font-bold tabular-nums text-[#34D399]">
                {formatCrores(latestDay.india_net_cr, { compact: true })}
              </span>
              {latestDay.shows !== null && (
                <span className="font-mono text-[11px] tabular-nums text-zinc-300">
                  • {latestDay.shows.toLocaleString("en-IN")} shows
                </span>
              )}
              {latestDay.occupancy_pct !== null && (
                <span className="font-mono text-[11px] tabular-nums text-amber-300">
                  • {latestDay.occupancy_pct.toFixed(1)}% occ.
                </span>
              )}
            </div>
          )}

          <div className="flex flex-wrap items-center gap-2 pt-1 sm:gap-2.5">
            <button
              type="button"
              onClick={() => onOpenDetails(movie)}
              className="inline-flex min-h-[40px] items-center gap-1.5 rounded-xl bg-[#F59E0B] px-4 py-2 text-xs font-bold text-black shadow-lg shadow-[#F59E0B]/20 transition hover:bg-amber-400"
            >
              View Full Breakdown
              <ArrowUpRight className="h-4 w-4" />
            </button>

            {onPlayTrailer ? (
              <button
                type="button"
                onClick={() => onPlayTrailer(movie)}
                className="inline-flex min-h-[40px] items-center gap-1.5 rounded-xl border border-[#10B981]/45 bg-[#10B981]/15 px-3.5 py-2 text-xs font-semibold text-[#34D399] transition hover:bg-[#10B981]/25"
              >
                <PlayCircle className="h-4 w-4" />
                Watch Trailer
              </button>
            ) : (
              <a
                href={getYoutubeSearchUrl(movie)}
                target="_blank"
                rel="noreferrer"
                className="inline-flex min-h-[40px] items-center gap-1.5 rounded-xl border border-white/[0.12] bg-[#090A0F]/80 px-3.5 py-2 text-xs font-semibold text-zinc-200 transition hover:border-[#F59E0B]/50 hover:text-[#F59E0B]"
              >
                <PlayCircle className="h-4 w-4 text-[#F59E0B]" />
                Watch Trailer
              </a>
            )}

            <button
              type="button"
              onClick={() => onToggleCompare(movie)}
              className={`inline-flex min-h-[40px] items-center gap-1.5 rounded-xl border px-3.5 py-2 text-xs font-semibold transition ${
                isCompared
                  ? "border-[#10B981]/50 bg-[#10B981]/15 text-[#34D399]"
                  : "border-white/[0.1] bg-[#090A0F]/80 text-zinc-200 hover:border-white/25"
              }`}
            >
              <GitCompare className="h-3.5 w-3.5" />
              {isCompared ? "Selected" : "Compare"}
            </button>
          </div>
        </div>

        {/* Live Telemetry Card */}
        <div className="min-w-0 rounded-2xl border border-white/[0.08] bg-[#090A0F]/85 p-4 backdrop-blur-xl sm:min-w-[310px] sm:p-5">
          <div className="flex items-center justify-between text-[11px] font-medium uppercase tracking-wider text-zinc-400">
            <span>{heroMetricLabel}</span>
            <span className="flex items-center gap-1 text-[#10B981]">
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-[#10B981]" />
              LIVE
            </span>
          </div>
          <div className="mt-1 whitespace-nowrap font-mono text-2xl font-bold tabular-nums tracking-tight text-[#F59E0B] sm:text-4xl">
            <AnimatedNumber value={headlineGross} prefix="₹" suffix=" Cr" />
          </div>

          <div className="mt-4 grid grid-cols-3 gap-2 border-t border-white/[0.08] pt-3 text-xs sm:gap-3">
            <div className="min-w-0">
              <p className="text-[10px] uppercase text-zinc-500">India Net</p>
              <p className="mt-0.5 truncate whitespace-nowrap font-mono font-semibold tabular-nums text-[#10B981]">
                {formatCrores(movie.india_net_cr, { compact: true })}
              </p>
            </div>
            <div className="min-w-0">
              <p className="text-[10px] uppercase text-zinc-500">Overseas</p>
              <p className="mt-0.5 truncate whitespace-nowrap font-mono font-semibold tabular-nums text-zinc-200">
                {formatCrores(movie.overseas_cr, { compact: true })}
              </p>
            </div>
            <div className="min-w-0">
              <p className="text-[10px] uppercase text-zinc-500">Budget</p>
              <p className="mt-0.5 truncate whitespace-nowrap font-mono font-semibold tabular-nums text-zinc-300">
                {formatCrores(movie.budget_cr, { compact: true })}
              </p>
            </div>
          </div>
        </div>
      </div>
    </motion.section>
  );
}
