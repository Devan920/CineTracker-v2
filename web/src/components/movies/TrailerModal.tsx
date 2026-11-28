import { AnimatePresence, motion } from "framer-motion";
import { ExternalLink, Film, Loader2, PlayCircle, X } from "lucide-react";
import { useEffect, useState } from "react";
import { fetchMovieTrailerId } from "../../lib/api";
import { getYoutubeSearchUrl } from "../../lib/formatters";
import type { MovieRecord } from "../../lib/supabase";

interface TrailerModalProps {
  movie: MovieRecord | null;
  onClose: () => void;
}

export function TrailerModal({ movie, onClose }: TrailerModalProps) {
  const [resolvedId, setResolvedId] = useState<string | null>(
    movie?.trailer_youtube_id ?? null
  );
  const [resolving, setResolving] = useState(false);

  useEffect(() => {
    if (!movie) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [movie, onClose]);

  useEffect(() => {
    if (!movie) {
      setResolvedId(null);
      setResolving(false);
      return;
    }
    if (movie.trailer_youtube_id) {
      setResolvedId(movie.trailer_youtube_id);
      setResolving(false);
      return;
    }

    let cancelled = false;
    setResolvedId(null);
    setResolving(true);
    void fetchMovieTrailerId(movie)
      .then((vid) => {
        if (!cancelled) {
          setResolvedId(vid);
        }
      })
      .finally(() => {
        if (!cancelled) {
          setResolving(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [movie]);

  if (!movie) return null;

  const embedUrl = resolvedId
    ? `https://www.youtube-nocookie.com/embed/${encodeURIComponent(
        resolvedId
      )}?rel=0&modestbranding=1&autoplay=1`
    : null;

  return (
    <AnimatePresence>
      <motion.div
        role="dialog"
        aria-modal="true"
        aria-label={`${movie.title} trailer player`}
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        className="fixed inset-0 z-[60] flex items-center justify-center bg-black/85 p-3 backdrop-blur-md sm:p-6"
        onClick={onClose}
      >
        <motion.div
          initial={{ scale: 0.96, opacity: 0, y: 16 }}
          animate={{ scale: 1, opacity: 1, y: 0 }}
          exit={{ scale: 0.96, opacity: 0, y: 16 }}
          transition={{ duration: 0.2 }}
          onClick={(e) => e.stopPropagation()}
          className="w-full max-w-4xl overflow-hidden rounded-2xl border border-white/[0.12] bg-[#090A0F] shadow-2xl"
        >
          {/* Theater Header Bar */}
          <div className="flex items-center justify-between gap-3 border-b border-white/[0.08] bg-[#12151E] px-4 py-3 sm:px-5">
            <div className="flex min-w-0 items-center gap-2.5">
              <PlayCircle className="h-5 w-5 shrink-0 text-[#F59E0B]" />
              <div className="min-w-0">
                <h3 className="truncate font-display text-sm font-bold text-white sm:text-base">
                  {movie.title}
                </h3>
                <p className="text-[11px] text-zinc-400">
                  {movie.language} • Official Theatrical Trailer
                </p>
              </div>
            </div>

            <div className="flex shrink-0 items-center gap-2">
              <a
                href={getYoutubeSearchUrl(movie)}
                target="_blank"
                rel="noreferrer"
                className="hidden items-center gap-1 rounded-xl border border-white/[0.1] bg-[#090A0F] px-3 py-1.5 text-xs font-medium text-zinc-300 transition hover:border-white/25 hover:text-white sm:inline-flex"
              >
                YouTube <ExternalLink className="h-3 w-3" />
              </a>
              <button
                type="button"
                onClick={onClose}
                aria-label="Close trailer player"
                className="flex min-h-[40px] min-w-[40px] items-center justify-center rounded-xl border border-white/15 bg-[#090A0F] text-zinc-200 transition hover:border-[#F59E0B]/50 hover:text-white"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
          </div>

          {/* Responsive 16:9 Trailer Embed */}
          <div className="relative aspect-video w-full bg-black">
            {resolving ? (
              <div className="flex h-full w-full flex-col items-center justify-center gap-2.5 text-xs text-zinc-400">
                <Loader2 className="h-7 w-7 animate-spin text-[#F59E0B]" />
                <span>Resolving official theatrical trailer...</span>
              </div>
            ) : embedUrl ? (
              <iframe
                src={embedUrl}
                title={`${movie.title} Official Trailer`}
                allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"
                allowFullScreen
                className="absolute inset-0 h-full w-full border-0"
              />
            ) : (
              <div className="flex h-full w-full flex-col items-center justify-center gap-3 p-6 text-center">
                <Film className="h-9 w-9 text-zinc-500" />
                <p className="text-xs text-zinc-300">
                  Embedded trailer unavailable in offline mode. Search YouTube directly:
                </p>
                <a
                  href={getYoutubeSearchUrl(movie)}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex min-h-[40px] items-center gap-1.5 rounded-xl bg-[#F59E0B] px-4 py-2 text-xs font-bold text-black hover:bg-amber-400"
                >
                  Open YouTube Trailer Search <ExternalLink className="h-3.5 w-3.5" />
                </a>
              </div>
            )}
          </div>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  );
}
