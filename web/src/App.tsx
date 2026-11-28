import { AlertCircle, ArrowRight, Database, GitCompare, Sparkles, TrendingUp } from "lucide-react";
import { Suspense, lazy, useEffect, useMemo, useState } from "react";
import { BrowserRouter, Link, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { SplashScreen } from "./components/SplashScreen";
import { ErrorBoundary } from "./components/layout/ErrorBoundary";
import { Footer } from "./components/layout/Footer";
import { LanguagePills } from "./components/layout/LanguagePills";
import { LiveTickerBar } from "./components/layout/LiveTickerBar";
import { MobileBottomNav } from "./components/layout/MobileBottomNav";
import { Navbar } from "./components/layout/Navbar";
import {
  AdminSkeleton,
  ComparisonSkeleton,
  HeroSpotlightSkeleton,
  MovieCardGridSkeleton,
  MovieDetailSkeleton,
} from "./components/layout/Skeletons";
import { HeroSpotlight } from "./components/movies/HeroSpotlight";
import { MovieCard } from "./components/movies/MovieCard";
import { useDocumentMeta } from "./hooks/useDocumentMeta";
import { useMovies } from "./hooks/useMovies";
import {
  formatCrores,
  isMovieLiveRunning,
  LIVE_RUNNING_FILTER,
  type LanguageFilter,
} from "./lib/formatters";
import { isSupabaseConfigured, type MovieRecord } from "./lib/supabase";

const ComparisonView = lazy(() =>
  import("./components/movies/ComparisonView").then((m) => ({ default: m.ComparisonView }))
);
const MovieDetailModal = lazy(() =>
  import("./components/movies/MovieDetailModal").then((m) => ({ default: m.MovieDetailModal }))
);
const TrailerModal = lazy(() =>
  import("./components/movies/TrailerModal").then((m) => ({ default: m.TrailerModal }))
);
const MovieDetailPage = lazy(() =>
  import("./pages/MovieDetailPage").then((m) => ({ default: m.MovieDetailPage }))
);
const AdminDashboard = lazy(() =>
  import("./pages/AdminDashboard").then((m) => ({ default: m.AdminDashboard }))
);

type SortOption = "latest_updated" | "worldwide" | "india_net" | "new_releases";

function AppShell() {
  const { movies, setMovies, loading, error, realtimeStatus, latestScrapedAt, refresh } =
    useMovies();
  const [selectedLanguage, setSelectedLanguage] = useState<LanguageFilter>("All");
  const [searchQuery, setSearchQuery] = useState("");
  const [sortBy, setSortBy] = useState<SortOption>("latest_updated");
  const [visibleCount, setVisibleCount] = useState(48);
  const [activeMovieSlug, setActiveMovieSlug] = useState<string | null>(null);
  const [trailerMovie, setTrailerMovie] = useState<MovieRecord | null>(null);
  const [compareSlugs, setCompareSlugs] = useState<string[]>([]);
  const [showSplash, setShowSplash] = useState<boolean>(() => {
    try {
      return !sessionStorage.getItem("ct_intro_played");
    } catch {
      return true;
    }
  });
  const [splashReplayKey, setSplashReplayKey] = useState(0);

  const handleReplayIntro = () => {
    setSplashReplayKey((prev) => prev + 1);
    setShowSplash(true);
  };

  useEffect(() => {
    setVisibleCount(48);
  }, [selectedLanguage, searchQuery, sortBy]);

  const location = useLocation();
  const navigate = useNavigate();

  const routeMeta = useMemo(() => {
    if (location.pathname === "/compare") {
      return {
        title: "Box Office Clash & Head-to-Head Comparison — CineTracker",
        description:
          "Compare Day 1, Weekend 1, Week 1, and cumulative India Net theatrical curves side-by-side.",
      };
    }
    if (location.pathname === "/admin") {
      return {
        title: "Admin Override Console — CineTracker",
        description:
          "CineTracker authenticated editorial & box office orchestration console.",
      };
    }
    return {
      title: "CineTracker — Live Indian & Malayalam Box Office Intelligence",
      description:
        "Live Indian & Malayalam Box Office Intelligence powered by multi-source theatrical tracking, Day-N splits, trailers, and TMDB enrichment.",
    };
  }, [location.pathname]);

  useDocumentMeta({
    title: routeMeta.title,
    description: routeMeta.description,
    image: !location.pathname.startsWith("/movie/") ? movies[0]?.backdrop_url || movies[0]?.poster_url : undefined,
  });

  const activeTab: "trending" | "malayalam" | "compare" | "admin" =
    location.pathname === "/admin"
      ? "admin"
      : location.pathname === "/compare"
      ? "compare"
      : selectedLanguage === "Malayalam"
      ? "malayalam"
      : "trending";

  const filteredMovies = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    const list = movies.filter((m) => {
      if (selectedLanguage === LIVE_RUNNING_FILTER) {
        if (!isMovieLiveRunning(m)) return false;
      } else if (
        selectedLanguage !== "All" &&
        m.language.toLowerCase() !== selectedLanguage.toLowerCase()
      ) {
        return false;
      }
      if (q) {
        const hay = `${m.title} ${m.language} ${m.cast_summary ?? ""}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });

    return [...list].sort((a, b) => {
      if (sortBy === "worldwide") {
        return (b.worldwide_gross_cr ?? b.india_net_cr) - (a.worldwide_gross_cr ?? a.india_net_cr);
      }
      if (sortBy === "india_net") {
        return b.india_net_cr - a.india_net_cr;
      }
      if (sortBy === "new_releases") {
        const relA = a.release_date ? new Date(a.release_date).getTime() : 0;
        const relB = b.release_date ? new Date(b.release_date).getTime() : 0;
        if (relB !== relA) return relB - relA;
        return b.india_net_cr - a.india_net_cr;
      }

      const updBucketA = a.last_scraped_at
        ? Math.floor(new Date(a.last_scraped_at).getTime() / (30 * 60_000))
        : 0;
      const updBucketB = b.last_scraped_at
        ? Math.floor(new Date(b.last_scraped_at).getTime() / (30 * 60_000))
        : 0;
      if (updBucketB !== updBucketA) return updBucketB - updBucketA;

      const liveA = isMovieLiveRunning(a) ? 1 : 0;
      const liveB = isMovieLiveRunning(b) ? 1 : 0;
      if (liveB !== liveA) return liveB - liveA;

      return (b.worldwide_gross_cr ?? b.india_net_cr) - (a.worldwide_gross_cr ?? a.india_net_cr);
    });
  }, [movies, selectedLanguage, searchQuery, sortBy]);

  const heroMovie = filteredMovies[0] ?? null;
  const gridMovies = heroMovie ? filteredMovies.slice(1) : [];
  const activeMovie = useMemo(
    () => movies.find((m) => m.movie_slug === activeMovieSlug) ?? null,
    [movies, activeMovieSlug]
  );

  const totalMarketNetCr = useMemo(
    () => filteredMovies.reduce((sum, m) => sum + (m.india_net_cr || 0), 0),
    [filteredMovies]
  );

  const toggleCompare = (movie: MovieRecord) => {
    setCompareSlugs((prev) => {
      if (prev.includes(movie.movie_slug)) {
        return prev.filter((slug) => slug !== movie.movie_slug);
      }
      if (prev.length >= 2) {
        return [prev[1], movie.movie_slug];
      }
      return [...prev, movie.movie_slug];
    });
  };

  const handleMovieUpdated = (updated: MovieRecord) => {
    setMovies((prev) => {
      const idx = prev.findIndex((m) => m.movie_slug === updated.movie_slug);
      if (idx === -1) return [updated, ...prev];
      const next = [...prev];
      next[idx] = updated;
      return next;
    });
  };

  return (
    <div className="flex min-h-screen flex-col overflow-x-hidden bg-[#090A0F] pb-20 text-zinc-100 md:pb-0">
      <SplashScreen
        key={splashReplayKey}
        open={showSplash}
        onFinish={() => setShowSplash(false)}
      />

      <Navbar
        movies={movies}
        realtimeStatus={realtimeStatus}
        latestScrapedAt={latestScrapedAt}
        searchQuery={searchQuery}
        onSearchChange={setSearchQuery}
        onRefresh={() => void refresh()}
        refreshing={loading}
        compareCount={compareSlugs.length}
        activeTab={activeTab}
        onSelectMalayalam={() => setSelectedLanguage("Malayalam")}
        onSelectTrending={() => setSelectedLanguage("All")}
        onSelectMovie={(m) => setActiveMovieSlug(m.movie_slug)}
        onReplayIntro={handleReplayIntro}
      />

      {location.pathname === "/" && (
        <LiveTickerBar
          movies={movies}
          onSelectMovie={(m) => setActiveMovieSlug(m.movie_slug)}
        />
      )}

      <main className="mx-auto w-full max-w-7xl flex-1 px-3 pt-4 sm:px-6 sm:pt-5">
        {!isSupabaseConfigured && location.pathname !== "/admin" && (
          <div className="mb-6 flex flex-col gap-3 rounded-2xl border border-[#F59E0B]/35 bg-[#F59E0B]/10 p-4 sm:flex-row sm:items-center sm:justify-between sm:p-5">
            <div className="flex items-start gap-3">
              <Database className="mt-0.5 h-5 w-5 shrink-0 text-[#F59E0B]" />
              <div>
                <h2 className="font-display text-sm font-bold text-white">
                  Connect Your Supabase Backend
                </h2>
                <p className="mt-0.5 text-xs text-zinc-300">
                  Add <code className="text-[#FCD34D]">VITE_SUPABASE_URL</code> and{" "}
                  <code className="text-[#FCD34D]">VITE_SUPABASE_ANON_KEY</code> to{" "}
                  <code className="text-[#FCD34D]">.env</code> to stream live box office collections.
                </p>
              </div>
            </div>
            <Link
              to="/admin"
              className="inline-flex min-h-[40px] shrink-0 items-center gap-1.5 rounded-xl bg-[#F59E0B] px-3.5 py-2 text-xs font-bold text-black"
            >
              Setup Status <ArrowRight className="h-3.5 w-3.5" />
            </Link>
          </div>
        )}

        {error && (
          <div className="mb-6 flex items-center gap-2.5 rounded-2xl border border-rose-500/40 bg-rose-500/10 p-4 text-xs text-rose-300">
            <AlertCircle className="h-4 w-4 shrink-0" />
            <span>Supabase Error: {error}</span>
          </div>
        )}

        <Routes>
          <Route
            path="/"
            element={
              <ErrorBoundary resetKey={location.pathname} sectionLabel="Box Office Dashboard">
                <div className="space-y-5 sm:space-y-6">
                  {/* Sticky Glassmorphic Filter & Sort Bar */}
                  <div className="z-30 -mx-3 border-b border-white/[0.08] bg-[#090A0F]/90 px-3 py-2.5 backdrop-blur-xl sm:-mx-6 sm:px-6 sm:py-3 lg:sticky lg:top-[72px]">
                    <div className="flex flex-col gap-2.5">
                      <div className="min-w-0 w-full">
                        <LanguagePills
                          selectedLanguage={selectedLanguage}
                          onSelect={setSelectedLanguage}
                          movies={movies}
                        />
                      </div>

                      <div className="flex items-center justify-between gap-3">
                        <div className="flex min-w-0 items-center gap-1.5 text-xs text-zinc-400">
                          <TrendingUp className="h-3.5 w-3.5 shrink-0 text-[#10B981]" />
                          <span className="truncate">Tracked Net:</span>
                          <span className="whitespace-nowrap font-mono font-semibold tabular-nums text-white">
                            {formatCrores(totalMarketNetCr)}
                          </span>
                        </div>
                        <select
                          aria-label="Sort movies"
                          value={sortBy}
                          onChange={(e) => setSortBy(e.target.value as SortOption)}
                          className="min-h-[40px] shrink-0 rounded-xl border border-white/[0.08] bg-[#12151E] px-3 py-2 text-xs font-medium text-zinc-200 focus:border-[#F59E0B] focus:outline-none"
                        >
                          <option value="latest_updated">Latest Updated</option>
                          <option value="worldwide">Highest Worldwide Gross</option>
                          <option value="india_net">Highest India Net</option>
                          <option value="new_releases">New Releases</option>
                        </select>
                      </div>
                    </div>
                  </div>

                  {/* Shimmer Loading Skeletons */}
                  {loading && movies.length === 0 ? (
                    <div className="space-y-5">
                      <HeroSpotlightSkeleton />
                      <MovieCardGridSkeleton count={8} />
                    </div>
                  ) : filteredMovies.length === 0 ? (
                    <div className="rounded-2xl border border-dashed border-white/[0.1] bg-[#12151E]/70 p-10 text-center sm:p-12">
                      <Sparkles className="mx-auto h-8 w-8 text-zinc-500" />
                      <h2 className="mt-3 font-display text-lg font-bold text-white">
                        No Box Office Records Found
                      </h2>
                      <p className="mt-1 text-xs text-zinc-400">
                        {movies.length === 0
                          ? "Run the backend sync or add a movie in /admin to populate Supabase."
                          : "Try clearing your language filter or search query."}
                      </p>
                    </div>
                  ) : (
                    <>
                      {heroMovie && (
                        <HeroSpotlight
                          movie={heroMovie}
                          onOpenDetails={(m) => setActiveMovieSlug(m.movie_slug)}
                          onToggleCompare={toggleCompare}
                          onPlayTrailer={(m) => setTrailerMovie(m)}
                          isCompared={compareSlugs.includes(heroMovie.movie_slug)}
                        />
                      )}

                      {gridMovies.length > 0 && (
                        <>
                          <section className="grid grid-cols-2 gap-3 sm:grid-cols-3 sm:gap-4 lg:grid-cols-4 lg:gap-5">
                            {gridMovies.slice(0, visibleCount).map((movie, idx) => (
                              <MovieCard
                                key={movie.movie_slug}
                                movie={movie}
                                index={idx}
                                onSelect={(m) => setActiveMovieSlug(m.movie_slug)}
                                onToggleCompare={toggleCompare}
                                onPlayTrailer={(m) => setTrailerMovie(m)}
                                isCompared={compareSlugs.includes(movie.movie_slug)}
                              />
                            ))}
                          </section>

                          {gridMovies.length > visibleCount && (
                            <div className="flex flex-wrap items-center justify-center gap-3 pt-2">
                              <button
                                type="button"
                                onClick={() => setVisibleCount((prev) => prev + 48)}
                                className="min-h-[40px] rounded-xl border border-white/[0.1] bg-[#12151E] px-5 py-2 text-xs font-semibold text-zinc-100 transition hover:border-[#F59E0B]/50 hover:text-[#F59E0B]"
                              >
                                Load More Movies ({gridMovies.length - visibleCount} remaining)
                              </button>
                              <button
                                type="button"
                                onClick={() => setVisibleCount(gridMovies.length)}
                                className="min-h-[40px] rounded-xl border border-white/[0.06] bg-white/[0.03] px-4 py-2 text-xs font-medium text-zinc-400 transition hover:text-zinc-200"
                              >
                                Show All ({gridMovies.length})
                              </button>
                            </div>
                          )}
                        </>
                      )}
                    </>
                  )}
                </div>
              </ErrorBoundary>
            }
          />

          <Route
            path="/movie/:slug"
            element={
              <ErrorBoundary resetKey={location.pathname} sectionLabel="Movie Detail Breakdown">
                <Suspense fallback={<MovieDetailSkeleton />}>
                  <MovieDetailPage
                    movies={movies}
                    loading={loading}
                    onPlayTrailer={(m) => setTrailerMovie(m)}
                  />
                </Suspense>
              </ErrorBoundary>
            }
          />

          <Route
            path="/compare"
            element={
              <ErrorBoundary resetKey={location.pathname} sectionLabel="Box Office Clash">
                <Suspense fallback={<ComparisonSkeleton />}>
                  <ComparisonView
                    movies={movies}
                    selectedSlugs={compareSlugs}
                    onChangeSlugs={setCompareSlugs}
                  />
                </Suspense>
              </ErrorBoundary>
            }
          />

          <Route
            path="/admin"
            element={
              <ErrorBoundary resetKey={location.pathname} sectionLabel="Admin Console">
                <Suspense fallback={<AdminSkeleton />}>
                  <AdminDashboard movies={movies} onMoviesUpdated={handleMovieUpdated} />
                </Suspense>
              </ErrorBoundary>
            }
          />
        </Routes>
      </main>

      <Footer />

      {/* Floating Comparison Bar when movies selected on home */}
      {location.pathname === "/" && compareSlugs.length > 0 && (
        <div className="fixed bottom-16 right-3 z-30 flex items-center gap-3 rounded-2xl border border-[#10B981]/40 bg-[#090A0F]/95 px-4 py-2.5 shadow-2xl backdrop-blur-xl sm:right-4 md:bottom-6">
          <span className="text-xs font-medium text-zinc-200">
            <strong className="font-mono tabular-nums text-[#10B981]">
              {compareSlugs.length}/2
            </strong>{" "}
            selected
          </span>
          <button
            type="button"
            onClick={() => navigate("/compare")}
            className="inline-flex min-h-[36px] items-center gap-1.5 rounded-xl bg-[#10B981] px-3 py-1.5 text-xs font-bold text-black hover:bg-emerald-400"
          >
            <GitCompare className="h-3.5 w-3.5" />
            Compare Now
          </button>
        </div>
      )}

      <Suspense fallback={null}>
        {activeMovie && (
          <MovieDetailModal
            movie={activeMovie}
            onClose={() => setActiveMovieSlug(null)}
            onPlayTrailer={(m) => setTrailerMovie(m)}
          />
        )}
      </Suspense>

      <Suspense fallback={null}>
        {trailerMovie && (
          <TrailerModal
            movie={trailerMovie}
            onClose={() => setTrailerMovie(null)}
          />
        )}
      </Suspense>

      <MobileBottomNav
        activeTab={activeTab}
        compareCount={compareSlugs.length}
        onSelectTrending={() => setSelectedLanguage("All")}
        onSelectMalayalam={() => setSelectedLanguage("Malayalam")}
      />
    </div>
  );
}

export function App() {
  return (
    <ErrorBoundary sectionLabel="CineTracker Application">
      <BrowserRouter>
        <AppShell />
      </BrowserRouter>
    </ErrorBoundary>
  );
}

export default App;
