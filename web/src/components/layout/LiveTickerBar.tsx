import { Flame, TrendingUp } from "lucide-react";
import { useMemo } from "react";
import { formatCrores, getLatestDayStats, isMovieLiveRunning } from "../../lib/formatters";
import type { MovieRecord } from "../../lib/supabase";

interface LiveTickerBarProps {
  movies: MovieRecord[];
  onSelectMovie: (movie: MovieRecord) => void;
}

export function LiveTickerBar({ movies, onSelectMovie }: LiveTickerBarProps) {
  const tickerItems = useMemo(() => {
    const live = movies
      .filter((m) => isMovieLiveRunning(m))
      .sort((a, b) => {
        const msA = new Date(a.last_scraped_at).getTime() || 0;
        const msB = new Date(b.last_scraped_at).getTime() || 0;
        if (Math.abs(msB - msA) > 6 * 3600_000) return msB - msA;
        return (b.worldwide_gross_cr ?? b.india_net_cr) - (a.worldwide_gross_cr ?? a.india_net_cr);
      });

    const source = live.length >= 4 ? live : movies.slice(0, 12);
    return source.slice(0, 16);
  }, [movies]);

  if (tickerItems.length === 0) return null;

  const renderTrack = (copyKey: string) =>
    tickerItems.map((movie) => {
      const latest = getLatestDayStats(movie);
      const isLive = isMovieLiveRunning(movie);
      return (
        <button
          key={`${copyKey}-${movie.movie_slug}`}
          type="button"
          onClick={() => onSelectMovie(movie)}
          className="group inline-flex shrink-0 items-center gap-2 rounded-full border border-white/[0.08] bg-[#12151E]/90 px-3 py-1 text-xs transition hover:border-[#F59E0B]/40 hover:bg-[#171C28]"
        >
          <span
            className={`h-1.5 w-1.5 rounded-full ${
              isLive ? "animate-pulse bg-[#10B981]" : "bg-[#F59E0B]"
            }`}
          />
          <span className="font-semibold text-white group-hover:text-[#F59E0B]">
            {movie.title}
          </span>
          <span className="rounded bg-white/[0.06] px-1.5 py-0.5 font-mono text-[10px] text-zinc-300">
            {movie.language}
          </span>
          {latest ? (
            <span className="font-mono text-[11px] font-bold tabular-nums text-[#10B981]">
              D{latest.day}: {formatCrores(latest.india_net_cr, { compact: true })}
            </span>
          ) : (
            <span className="font-mono text-[11px] font-bold tabular-nums text-[#10B981]">
              Net {formatCrores(movie.india_net_cr, { compact: true })}
            </span>
          )}
          {movie.worldwide_gross_cr !== null && (
            <span className="font-mono text-[11px] tabular-nums text-[#F59E0B]">
              • WW {formatCrores(movie.worldwide_gross_cr, { compact: true })}
            </span>
          )}
        </button>
      );
    });

  return (
    <div className="border-b border-white/[0.08] bg-[#090A0F]/95 backdrop-blur-md">
      <div className="mx-auto flex max-w-7xl items-center gap-3 px-4 py-2 sm:px-6">
        <div className="inline-flex shrink-0 items-center gap-1.5 rounded-full border border-[#10B981]/30 bg-[#10B981]/10 px-2.5 py-1 text-[10px] font-bold uppercase tracking-wider text-[#34D399]">
          <Flame className="h-3 w-3 text-[#F59E0B]" />
          <span className="hidden sm:inline">Live Box Office</span>
          <span className="sm:hidden">Live</span>
        </div>

        <div className="ticker-wrap relative flex-1 overflow-hidden">
          <div className="animate-ticker flex items-center gap-2.5">
            {renderTrack("a")}
            {renderTrack("b")}
          </div>
          <div className="pointer-events-none absolute inset-y-0 left-0 w-6 bg-gradient-to-r from-[#090A0F] to-transparent" />
          <div className="pointer-events-none absolute inset-y-0 right-0 w-10 bg-gradient-to-l from-[#090A0F] to-transparent" />
        </div>

        <div className="hidden items-center gap-1 text-[11px] text-zinc-400 lg:flex">
          <TrendingUp className="h-3 w-3 text-[#10B981]" />
          <span className="font-mono tabular-nums">{tickerItems.length} tracked</span>
        </div>
      </div>
    </div>
  );
}
