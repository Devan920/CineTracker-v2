import { Bell, CheckCheck, Flame, Sparkles, Trophy } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  formatCrores,
  formatRelativeTime,
  getLatestDayStats,
  isMovieLiveRunning,
} from "../../lib/formatters";
import type { MovieRecord } from "../../lib/supabase";

interface NotificationBellProps {
  movies: MovieRecord[];
  onSelectMovie: (movie: MovieRecord) => void;
}

interface AlertItem {
  id: string;
  movie: MovieRecord;
  badge: string;
  badgeClass: string;
  headline: string;
  detail: string;
  timestampMs: number;
  icon: "live" | "milestone";
}

const STORAGE_KEY = "ct_notif_read_ms";

export function NotificationBell({ movies, onSelectMovie }: NotificationBellProps) {
  const [open, setOpen] = useState(false);
  const [lastReadMs, setLastReadMs] = useState<number>(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      return saved ? Number(saved) || 0 : 0;
    } catch {
      return 0;
    }
  });
  const containerRef = useRef<HTMLDivElement | null>(null);

  const alerts = useMemo<AlertItem[]>(() => {
    if (!movies.length) return [];
    const items: AlertItem[] = [];
    const seenSlugs = new Set<string>();

    const liveSorted = [...movies]
      .filter((m) => isMovieLiveRunning(m))
      .sort((a, b) => {
        const msA = new Date(a.last_scraped_at).getTime() || 0;
        const msB = new Date(b.last_scraped_at).getTime() || 0;
        return msB - msA;
      });

    for (const movie of liveSorted.slice(0, 4)) {
      const latest = getLatestDayStats(movie);
      const ts = new Date(movie.last_scraped_at).getTime() || 0;
      seenSlugs.add(movie.movie_slug);
      items.push({
        id: `live-${movie.movie_slug}`,
        movie,
        badge: `Day ${movie.day_count} Live`,
        badgeClass: "border-[#10B981]/40 bg-[#10B981]/15 text-[#34D399]",
        headline: movie.title,
        detail: latest
          ? `Day ${latest.day} Net ${formatCrores(latest.india_net_cr, { compact: true })} • Total ${formatCrores(movie.india_net_cr, { compact: true })}`
          : `India Net ${formatCrores(movie.india_net_cr, { compact: true })}`,
        timestampMs: ts,
        icon: "live",
      });
    }

    const milestones = [...movies]
      .filter((m) => !seenSlugs.has(m.movie_slug) && ((m.worldwide_gross_cr ?? 0) >= 100 || (m.verdict ?? "").toLowerCase().includes("blockbuster")))
      .sort((a, b) => (b.worldwide_gross_cr ?? b.india_net_cr) - (a.worldwide_gross_cr ?? a.india_net_cr));

    for (const movie of milestones.slice(0, 3)) {
      const ts = new Date(movie.last_scraped_at).getTime() || 0;
      items.push({
        id: `milestone-${movie.movie_slug}`,
        movie,
        badge: movie.verdict || "₹100Cr+ Club",
        badgeClass: "border-[#F59E0B]/40 bg-[#F59E0B]/15 text-[#FCD34D]",
        headline: movie.title,
        detail: `Worldwide ${formatCrores(movie.worldwide_gross_cr ?? movie.india_net_cr, { compact: true })} • ${movie.language}`,
        timestampMs: ts,
        icon: "milestone",
      });
    }

    return items.slice(0, 6);
  }, [movies]);

  const unreadCount = useMemo(
    () => alerts.filter((a) => a.timestampMs > lastReadMs).length,
    [alerts, lastReadMs]
  );

  useEffect(() => {
    if (!open) return;
    const handleOutside = (event: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", handleOutside);
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("mousedown", handleOutside);
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [open]);

  const handleMarkAllRead = () => {
    const now = Date.now();
    setLastReadMs(now);
    try {
      localStorage.setItem(STORAGE_KEY, String(now));
    } catch {
      // ignore storage quota errors
    }
  };

  return (
    <div ref={containerRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((prev) => !prev)}
        aria-label="Box office notifications"
        aria-expanded={open}
        title="Box Office Alerts"
        className={`relative flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border transition ${
          open
            ? "border-[#F59E0B]/60 bg-[#F59E0B]/15 text-[#F59E0B]"
            : "border-white/[0.08] bg-[#12151E] text-zinc-300 hover:border-white/20 hover:text-white"
        }`}
      >
        <Bell className="h-3.5 w-3.5" />
        {unreadCount > 0 && (
          <span className="absolute -right-1 -top-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-[#10B981] px-1 font-mono text-[9px] font-bold tabular-nums text-black shadow-sm">
            {unreadCount}
          </span>
        )}
      </button>

      {open && (
        <div
          role="region"
          aria-label="Box office alert feed"
          className="fixed inset-x-3 top-14 z-50 rounded-2xl border border-white/[0.12] bg-[#0B0D14]/95 p-3 shadow-2xl shadow-black/80 backdrop-blur-xl sm:absolute sm:inset-x-auto sm:right-0 sm:top-full sm:mt-2 sm:w-80"
        >
          <div className="mb-2 flex items-center justify-between border-b border-white/[0.08] pb-2">
            <div className="flex items-center gap-1.5">
              <Sparkles className="h-3.5 w-3.5 text-[#F59E0B]" />
              <span className="font-display text-xs font-bold uppercase tracking-wider text-white">
                Live Box Office Alerts
              </span>
            </div>
            {alerts.length > 0 && (
              <button
                type="button"
                onClick={handleMarkAllRead}
                className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-[10px] font-medium text-zinc-400 transition hover:bg-white/[0.06] hover:text-zinc-200"
              >
                <CheckCheck className="h-3 w-3 text-[#10B981]" />
                Mark read
              </button>
            )}
          </div>

          {alerts.length === 0 ? (
            <div className="py-6 text-center text-xs text-zinc-500">
              No live theatrical updates synced yet.
            </div>
          ) : (
            <ul className="max-h-80 space-y-1.5 overflow-y-auto pr-0.5">
              {alerts.map((item) => {
                const isUnread = item.timestampMs > lastReadMs;
                return (
                  <li key={item.id}>
                    <button
                      type="button"
                      onClick={() => {
                        onSelectMovie(item.movie);
                        setOpen(false);
                      }}
                      className={`w-full rounded-xl border p-2.5 text-left transition ${
                        isUnread
                          ? "border-[#10B981]/25 bg-[#12151E] hover:border-[#F59E0B]/40"
                          : "border-white/[0.06] bg-[#12151E]/60 hover:border-white/[0.15]"
                      }`}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span
                          className={`inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 font-mono text-[9px] font-bold uppercase ${item.badgeClass}`}
                        >
                          {item.icon === "live" ? (
                            <Flame className="h-2.5 w-2.5" />
                          ) : (
                            <Trophy className="h-2.5 w-2.5" />
                          )}
                          {item.badge}
                        </span>
                        <span className="font-mono text-[10px] text-zinc-500">
                          {formatRelativeTime(item.movie.last_scraped_at)}
                        </span>
                      </div>
                      <p className="mt-1 truncate text-xs font-semibold text-white">
                        {item.headline}
                      </p>
                      <p className="mt-0.5 truncate font-mono text-[11px] text-zinc-400">
                        {item.detail}
                      </p>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
