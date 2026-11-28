import { useCallback, useEffect, useMemo, useState } from "react";
import {
  fetchMovies,
  isSupabaseConfigured,
  subscribeToMovies,
  type MovieRecord,
  type RealtimeStatus,
} from "../lib/supabase";

export function useMovies() {
  const [movies, setMovies] = useState<MovieRecord[]>([]);
  const [loading, setLoading] = useState<boolean>(isSupabaseConfigured);
  const [error, setError] = useState<string | null>(null);
  const [realtimeStatus, setRealtimeStatus] = useState<RealtimeStatus>(
    isSupabaseConfigured ? "CONNECTING" : "UNCONFIGURED"
  );
  const [lastUpdatedEventAt, setLastUpdatedEventAt] = useState<string | null>(null);

  const loadInitial = useCallback(async () => {
    if (!isSupabaseConfigured) {
      setLoading(false);
      setRealtimeStatus("UNCONFIGURED");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const rows = await fetchMovies();
      setMovies(rows);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load movies from Supabase.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadInitial();

    const unsubscribe = subscribeToMovies((event) => {
      setLastUpdatedEventAt(new Date().toISOString());
      setMovies((prev) => {
        if (event.eventType === "DELETE" && event.oldSlug) {
          return prev.filter((m) => m.movie_slug !== event.oldSlug);
        }
        if (!event.newRecord) return prev;
        const incoming = event.newRecord;
        const idx = prev.findIndex((m) => m.movie_slug === incoming.movie_slug);
        if (idx === -1) {
          return [incoming, ...prev].sort((a, b) => b.india_net_cr - a.india_net_cr);
        }
        const next = [...prev];
        next[idx] = incoming;
        return next.sort((a, b) => b.india_net_cr - a.india_net_cr);
      });
    }, setRealtimeStatus);

    return () => {
      unsubscribe();
    };
  }, [loadInitial]);

  const latestScrapedAt = useMemo(() => {
    const timestamps = movies
      .map((m) => m.last_scraped_at)
      .filter(Boolean)
      .map((ts) => new Date(ts).getTime())
      .filter((ms) => !Number.isNaN(ms));

    if (lastUpdatedEventAt) {
      const eventMs = new Date(lastUpdatedEventAt).getTime();
      if (!Number.isNaN(eventMs)) {
        timestamps.push(eventMs);
      }
    }

    if (!timestamps.length) return null;
    return new Date(Math.max(...timestamps)).toISOString();
  }, [movies, lastUpdatedEventAt]);

  return {
    movies,
    setMovies,
    loading,
    error,
    realtimeStatus,
    latestScrapedAt,
    refresh: loadInitial,
  };
}
