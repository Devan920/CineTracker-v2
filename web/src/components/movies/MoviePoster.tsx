import { Clapperboard, Film } from "lucide-react";
import { useEffect, useState } from "react";
import type { MovieRecord } from "../../lib/supabase";

interface MoviePosterProps {
  movie: Pick<MovieRecord, "title" | "language" | "release_date" | "poster_url" | "backdrop_url" | "day_count">;
  srcOverride?: string | null;
  alt?: string;
  className?: string;
  compact?: boolean;
  crossOrigin?: "anonymous" | "use-credentials";
}

const LANG_ACCENT_GRADIENTS: Record<string, string> = {
  malayalam: "from-emerald-950/90 via-[#12151E] to-amber-950/60",
  hindi: "from-amber-950/90 via-[#12151E] to-zinc-950",
  tamil: "from-indigo-950/90 via-[#12151E] to-emerald-950/50",
  telugu: "from-sky-950/90 via-[#12151E] to-amber-950/50",
  kannada: "from-rose-950/85 via-[#12151E] to-amber-950/50",
  "pan-india": "from-amber-900/70 via-[#12151E] to-emerald-900/60",
};

/**
 * Resilient movie poster component that gracefully degrades on null URLs or onError
 * into a custom typographic theatrical poster card (zero broken image icons).
 */
export function MoviePoster({
  movie,
  srcOverride,
  alt,
  className = "h-full w-full object-cover",
  compact = false,
  crossOrigin,
}: MoviePosterProps) {
  const targetSrc = (srcOverride ?? movie.poster_url ?? movie.backdrop_url ?? "").trim();
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    setFailed(false);
  }, [targetSrc]);

  if (targetSrc && !failed) {
    return (
      <img
        src={targetSrc}
        alt={alt ?? movie.title}
        loading="lazy"
        decoding="async"
        crossOrigin={crossOrigin}
        onError={() => setFailed(true)}
        className={className}
      />
    );
  }

  const grad =
    LANG_ACCENT_GRADIENTS[movie.language.toLowerCase()] ??
    "from-[#171B26] via-[#12151E] to-[#090A0F]";
  const releaseYear = movie.release_date?.slice(0, 4) ?? "2026";

  return (
    <div
      className={`relative flex h-full w-full flex-col justify-between overflow-hidden bg-gradient-to-br ${grad} ${
        compact ? "p-2.5" : "p-4"
      }`}
    >
      {/* Subtle theatrical radial glow & geometric marquee lines */}
      <div className="pointer-events-none absolute -right-10 -top-10 h-32 w-32 rounded-full bg-[#F59E0B]/10 blur-2xl" />
      <div className="pointer-events-none absolute -bottom-10 -left-10 h-32 w-32 rounded-full bg-[#10B981]/10 blur-2xl" />
      <div className="pointer-events-none absolute inset-2 rounded-xl border border-white/[0.06]" />

      <div className="relative z-10 flex items-center justify-between">
        <span className="inline-flex items-center gap-1 rounded-md border border-white/10 bg-[#090A0F]/75 px-1.5 py-0.5 font-mono text-[9px] font-semibold uppercase tracking-wider text-[#F59E0B]">
          {compact ? <Film className="h-2.5 w-2.5" /> : <Clapperboard className="h-3 w-3" />}
          {movie.language}
        </span>
        {!compact && (
          <span className="font-mono text-[10px] font-medium text-zinc-400">
            {releaseYear}
          </span>
        )}
      </div>

      <div className="relative z-10 my-auto py-2 text-center">
        <p
          className={`font-display font-bold tracking-tight text-white drop-shadow ${
            compact ? "line-clamp-3 text-xs leading-tight" : "line-clamp-4 text-lg leading-snug sm:text-xl"
          }`}
        >
          {movie.title}
        </p>
        {!compact && (
          <div className="mx-auto mt-2.5 h-0.5 w-10 rounded-full bg-gradient-to-r from-[#10B981] to-[#F59E0B] opacity-75" />
        )}
      </div>

      <div className="relative z-10 flex items-center justify-between font-mono text-[9px] uppercase tracking-widest text-zinc-400">
        <span>CineTracker</span>
        {movie.day_count > 0 && <span>Day {movie.day_count}</span>}
      </div>
    </div>
  );
}
