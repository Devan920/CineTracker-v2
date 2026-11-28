import { AnimatePresence, motion } from "framer-motion";
import { ExternalLink, X } from "lucide-react";
import { Link } from "react-router-dom";
import type { MovieRecord } from "../../lib/supabase";
import { MovieDetailView } from "./MovieDetailView";

interface MovieDetailModalProps {
  movie: MovieRecord | null;
  onClose: () => void;
  onPlayTrailer?: (movie: MovieRecord) => void;
}

export function MovieDetailModal({
  movie,
  onClose,
  onPlayTrailer,
}: MovieDetailModalProps) {
  if (!movie) return null;

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        className="fixed inset-0 z-50 flex items-end justify-center bg-black/80 backdrop-blur-sm sm:items-center sm:p-4"
        onClick={onClose}
      >
        <motion.div
          initial={{ y: 40, opacity: 0, scale: 0.98 }}
          animate={{ y: 0, opacity: 1, scale: 1 }}
          exit={{ y: 40, opacity: 0, scale: 0.98 }}
          transition={{ type: "spring", stiffness: 320, damping: 28 }}
          onClick={(e) => e.stopPropagation()}
          className="relative max-h-[92vh] w-full max-w-5xl overflow-x-hidden overflow-y-auto rounded-t-3xl border border-white/[0.1] bg-[#090A0F] p-3.5 shadow-2xl sm:rounded-3xl sm:p-7"
        >
          <MovieDetailView
            movie={movie}
            onPlayTrailer={onPlayTrailer}
            headerActions={
              <>
                <Link
                  to={`/movie/${movie.movie_slug}`}
                  onClick={onClose}
                  title="Open full page view"
                  className="inline-flex min-h-[40px] items-center gap-1.5 rounded-xl border border-white/15 bg-[#090A0F]/85 px-3 text-xs font-medium text-zinc-200 backdrop-blur-md transition hover:border-[#F59E0B]/50 hover:text-[#F59E0B]"
                >
                  <ExternalLink className="h-3.5 w-3.5" />
                  <span className="hidden sm:inline">Full Page</span>
                </Link>
                <button
                  type="button"
                  onClick={onClose}
                  aria-label="Close details"
                  className="flex min-h-[40px] min-w-[40px] items-center justify-center rounded-xl border border-white/15 bg-[#090A0F]/85 text-zinc-300 backdrop-blur-md transition hover:border-white/30 hover:text-white"
                >
                  <X className="h-4 w-4" />
                </button>
              </>
            }
          />
        </motion.div>
      </motion.div>
    </AnimatePresence>
  );
}
