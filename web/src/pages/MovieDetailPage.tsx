import { ArrowLeft, Film } from "lucide-react";
import { Link, useParams } from "react-router-dom";
import { MovieDetailSkeleton } from "../components/layout/Skeletons";
import { MovieDetailView } from "../components/movies/MovieDetailView";
import { useDocumentMeta } from "../hooks/useDocumentMeta";
import { formatCrores } from "../lib/formatters";
import type { MovieRecord } from "../lib/supabase";

interface MovieDetailPageProps {
  movies: MovieRecord[];
  loading: boolean;
  onPlayTrailer?: (movie: MovieRecord) => void;
}

export function MovieDetailPage({ movies, loading, onPlayTrailer }: MovieDetailPageProps) {
  const { slug } = useParams<{ slug: string }>();
  const movie = movies.find((m) => m.movie_slug === slug) ?? null;

  useDocumentMeta({
    title: movie
      ? `${movie.title} (${movie.language}) Box Office Collection — CineTracker`
      : "Movie Box Office Breakdown — CineTracker",
    description: movie
      ? `${movie.title} (${movie.language}) live theatrical collection: India Net ${formatCrores(
          movie.india_net_cr
        )}, Worldwide ${formatCrores(movie.worldwide_gross_cr ?? movie.india_net_cr)} across Day ${
          movie.day_count
        }.`
      : "Real-time Indian & Malayalam theatrical box office breakdown, ROI meter, and official trailer on CineTracker.",
    image: movie?.backdrop_url || movie?.poster_url || null,
  });

  if (loading && movies.length === 0) {
    return <MovieDetailSkeleton />;
  }

  if (!movie) {
    return (
      <div className="rounded-2xl border border-dashed border-white/[0.1] bg-[#12151E] p-12 text-center">
        <Film className="mx-auto h-8 w-8 text-zinc-500" />
        <h2 className="mt-3 font-display text-lg font-bold text-white">Movie Not Found</h2>
        <p className="mt-1 text-xs text-zinc-400">
          No tracked box office record matched slug <code className="text-[#F59E0B]">{slug}</code>.
        </p>
        <Link
          to="/"
          className="mt-4 inline-flex min-h-[40px] items-center gap-1.5 rounded-xl bg-[#F59E0B] px-4 py-2 text-xs font-bold text-black hover:bg-amber-400"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
          Back to Dashboard
        </Link>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <Link
          to="/"
          className="inline-flex min-h-[40px] items-center gap-1.5 rounded-xl border border-white/[0.08] bg-[#12151E] px-3 py-1.5 text-xs font-medium text-zinc-200 transition hover:border-white/20 hover:text-[#F59E0B]"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
          Back to Box Office Grid
        </Link>
      </div>

      <MovieDetailView movie={movie} onPlayTrailer={onPlayTrailer} />
    </div>
  );
}
