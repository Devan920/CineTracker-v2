import { toPng } from "html-to-image";
import {
  AlertTriangle,
  ArrowDownRight,
  ArrowUpRight,
  BarChart3,
  Calendar,
  CheckCircle2,
  Download,
  ExternalLink,
  LineChart as LineChartIcon,
  Lock,
  PlayCircle,
  Share2,
} from "lucide-react";
import { useMemo, useRef, useState } from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  computeBudgetRecoveryPct,
  computeRoiMultiple,
  formatCrores,
  formatExactTimestamp,
  formatSourceLabel,
  getVerdictStyle,
  getYoutubeSearchUrl,
  isMovieLiveRunning,
} from "../../lib/formatters";
import type { MovieRecord } from "../../lib/supabase";
import { BrandLogo } from "../BrandLogo";
import { MoviePoster } from "./MoviePoster";

interface MovieDetailViewProps {
  movie: MovieRecord;
  headerActions?: React.ReactNode;
  onPlayTrailer?: (movie: MovieRecord) => void;
}

export function MovieDetailView({
  movie,
  headerActions,
  onPlayTrailer,
}: MovieDetailViewProps) {
  const [chartMode, setChartMode] = useState<"daily" | "cumulative">("daily");
  const [exportingPng, setExportingPng] = useState(false);
  const [exportNote, setExportNote] = useState<string | null>(null);
  const shareCardRef = useRef<HTMLDivElement | null>(null);

  const chartData = useMemo(() => {
    let running = 0;
    return movie.daily_breakdown.map((entry) => {
      running = Number((running + entry.india_net_cr).toFixed(2));
      return {
        dayLabel: `D${entry.day}`,
        day: entry.day,
        date: entry.date,
        india_net_cr: entry.india_net_cr,
        cumulative_cr: running,
        change_pct: entry.change_pct,
        shows: entry.shows ?? null,
        occupancy_pct: entry.occupancy_pct ?? null,
      };
    });
  }, [movie]);

  const regionalData = useMemo(() => {
    const indiaGross = movie.india_gross_cr ?? movie.india_net_cr * 1.18;
    const overseas =
      movie.overseas_cr ??
      Math.max(0, (movie.worldwide_gross_cr ?? indiaGross) - indiaGross);
    return [
      { name: "India Gross", value: Number(indiaGross.toFixed(2)), color: "#10B981" },
      { name: "Overseas", value: Number(overseas.toFixed(2)), color: "#F59E0B" },
    ].filter((i) => i.value > 0);
  }, [movie]);

  const day1Opening = useMemo(() => {
    const d1 = movie.daily_breakdown.find((d) => d.day === 1);
    return d1 ? d1.india_net_cr : null;
  }, [movie]);

  const hasShowsColumn = useMemo(
    () => movie.daily_breakdown.some((d) => d.shows !== null && d.shows !== undefined),
    [movie]
  );

  const verdictMeta = getVerdictStyle(movie.verdict);
  const recoveryPct = computeBudgetRecoveryPct(movie);
  const roiMultiple = computeRoiMultiple(movie);
  const regionalTotal = regionalData.reduce((s, x) => s + x.value, 0);
  const isLive = isMovieLiveRunning(movie);

  const handleExportReportPng = async () => {
    if (!shareCardRef.current) return;
    setExportingPng(true);
    setExportNote(null);
    try {
      const dataUrl = await toPng(shareCardRef.current, {
        cacheBust: true,
        pixelRatio: 2,
        backgroundColor: "#090A0F",
      });
      const link = document.createElement("a");
      link.download = `cinetracker-${movie.movie_slug}-report.png`;
      link.href = dataUrl;
      link.click();
      setExportNote("Report card PNG exported.");
    } catch {
      try {
        const fallbackUrl = await toPng(shareCardRef.current, {
          cacheBust: true,
          pixelRatio: 2,
          backgroundColor: "#090A0F",
          filter: (node) => node.tagName !== "IMG",
        });
        const link = document.createElement("a");
        link.download = `cinetracker-${movie.movie_slug}-report.png`;
        link.href = fallbackUrl;
        link.click();
        setExportNote("Exported typography card (external image skipped due to CORS).");
      } catch (err) {
        setExportNote(err instanceof Error ? err.message : "Failed to export PNG.");
      }
    } finally {
      setExportingPng(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Full-Bleed Backdrop Header + Large Poster */}
      <div className="relative overflow-hidden rounded-2xl border border-white/[0.08] bg-[#12151E]">
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
          <div className="absolute inset-0 bg-gradient-to-r from-[#090A0F] via-[#090A0F]/85 to-[#090A0F]/60" />
          <div className="absolute inset-0 bg-gradient-to-t from-[#12151E] via-transparent to-transparent" />
        </div>

        {headerActions && (
          <div className="absolute right-4 top-4 z-20 flex items-center gap-2">
            {headerActions}
          </div>
        )}

        <div className="relative z-10 flex flex-col gap-5 p-5 sm:flex-row sm:items-end sm:p-7">
          <div className="mx-auto aspect-[2/3] w-32 shrink-0 overflow-hidden rounded-2xl border border-white/15 bg-[#090A0F] shadow-2xl sm:mx-0 sm:w-40">
            <MoviePoster
              movie={movie}
              srcOverride={movie.poster_url || movie.backdrop_url || ""}
              className="h-full w-full object-cover object-center"
            />
          </div>

          <div className="min-w-0 flex-1 space-y-3 sm:pr-12">
            <div className="flex flex-wrap items-center gap-2">
              <span className="rounded-full border border-white/15 bg-[#090A0F]/80 px-2.5 py-0.5 text-xs font-semibold text-zinc-200">
                {movie.language}
              </span>
              <span
                className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 font-mono text-[11px] font-bold ${
                  isLive
                    ? "border-[#10B981]/40 bg-[#10B981]/15 text-[#34D399]"
                    : "border-white/15 bg-[#090A0F]/80 text-zinc-200"
                }`}
              >
                {isLive && <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-[#10B981]" />}
                Day {movie.day_count} {isLive ? "Live" : ""}
              </span>
              <span className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${verdictMeta.className}`}>
                {verdictMeta.label}
              </span>
              {movie.manual_override && (
                <span className="inline-flex items-center gap-1 rounded-full border border-sky-500/30 bg-sky-500/10 px-2 py-0.5 text-[11px] text-sky-300">
                  <Lock className="h-3 w-3" /> Locked
                </span>
              )}
            </div>

            <h2 className="font-display text-2xl font-bold tracking-tight text-white sm:text-3xl">
              {movie.title}
            </h2>

            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-zinc-400">
              {movie.release_date && (
                <span className="inline-flex items-center gap-1">
                  <Calendar className="h-3.5 w-3.5 text-zinc-500" />
                  Released {movie.release_date}
                </span>
              )}
              <span>Updated {formatExactTimestamp(movie.last_scraped_at)}</span>
            </div>

            {movie.cast_summary && (
              <p className="text-xs text-zinc-300">
                <span className="text-zinc-500">Cast: </span>
                {movie.cast_summary}
              </p>
            )}

            <div className="pt-1">
              {onPlayTrailer ? (
                <button
                  type="button"
                  onClick={() => onPlayTrailer(movie)}
                  className="inline-flex min-h-[40px] items-center gap-2 rounded-xl bg-[#F59E0B] px-4 py-2 text-xs font-bold text-black shadow-lg shadow-[#F59E0B]/20 transition hover:bg-amber-400"
                >
                  <PlayCircle className="h-4 w-4" />
                  Watch Trailer
                </button>
              ) : (
                <a
                  href={getYoutubeSearchUrl(movie)}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex min-h-[40px] items-center gap-2 rounded-xl border border-white/[0.15] bg-[#090A0F]/85 px-4 py-2 text-xs font-semibold text-zinc-100 transition hover:border-[#F59E0B]/50 hover:text-[#F59E0B]"
                >
                  <PlayCircle className="h-4 w-4 text-[#F59E0B]" />
                  Watch Trailer
                  <ExternalLink className="h-3 w-3 opacity-75" />
                </a>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Conflict Warning if variance_flag */}
      {movie.variance_flag && (
        <div className="flex items-start gap-3 rounded-2xl border border-[#F59E0B]/40 bg-[#F59E0B]/10 p-3.5 text-xs text-amber-200">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-[#F59E0B]" />
          <div>
            <p className="font-semibold">Cross-Source Variance Alert (&gt;25%)</p>
            <p className="mt-0.5 text-amber-200/80">
              Secondary trackers reported figures diverging by more than 25% from primary feed{" "}
              <span className="font-semibold">{formatSourceLabel(movie.primary_source)}</span>. Reviewable in Admin.
            </p>
          </div>
        </div>
      )}

      {/* 7-Metric KPI Stat Grid */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 xl:grid-cols-7">
        <div className="rounded-2xl border border-white/[0.08] bg-[#12151E] p-3.5">
          <p className="text-[10px] uppercase tracking-wider text-zinc-400">Day 1 Opening</p>
          <p className="mt-1 whitespace-nowrap font-mono text-sm font-bold tabular-nums text-zinc-100 xl:text-[15px]">
            {formatCrores(day1Opening, { compact: true })}
          </p>
        </div>
        <div className="rounded-2xl border border-white/[0.08] bg-[#12151E] p-3.5">
          <p className="text-[10px] uppercase tracking-wider text-zinc-400">India Net</p>
          <p className="mt-1 whitespace-nowrap font-mono text-sm font-bold tabular-nums text-[#10B981] xl:text-[15px]">
            {formatCrores(movie.india_net_cr, { compact: true })}
          </p>
        </div>
        <div className="rounded-2xl border border-white/[0.08] bg-[#12151E] p-3.5">
          <p className="text-[10px] uppercase tracking-wider text-zinc-400">India Gross</p>
          <p className="mt-1 whitespace-nowrap font-mono text-sm font-bold tabular-nums text-zinc-100 xl:text-[15px]">
            {formatCrores(movie.india_gross_cr, { compact: true })}
          </p>
        </div>
        <div className="rounded-2xl border border-white/[0.08] bg-[#12151E] p-3.5">
          <p className="text-[10px] uppercase tracking-wider text-zinc-400">Overseas</p>
          <p className="mt-1 whitespace-nowrap font-mono text-sm font-bold tabular-nums text-zinc-100 xl:text-[15px]">
            {formatCrores(movie.overseas_cr, { compact: true })}
          </p>
        </div>
        <div className="rounded-2xl border border-white/[0.08] bg-[#12151E] p-3.5">
          <p className="text-[10px] uppercase tracking-wider text-zinc-400">Worldwide</p>
          <p className="mt-1 whitespace-nowrap font-mono text-sm font-bold tabular-nums text-[#F59E0B] xl:text-[15px]">
            {formatCrores(movie.worldwide_gross_cr, { compact: true })}
          </p>
        </div>
        <div className="rounded-2xl border border-white/[0.08] bg-[#12151E] p-3.5">
          <p className="text-[10px] uppercase tracking-wider text-zinc-400">Budget</p>
          <p className="mt-1 whitespace-nowrap font-mono text-sm font-bold tabular-nums text-zinc-200 xl:text-[15px]">
            {formatCrores(movie.budget_cr, { compact: true })}
          </p>
        </div>
        <div className="col-span-2 rounded-2xl border border-white/[0.08] bg-[#12151E] p-3.5 sm:col-span-1">
          <p className="text-[10px] uppercase tracking-wider text-zinc-400">ROI %</p>
          <p
            className={`mt-1 whitespace-nowrap font-mono text-sm font-bold tabular-nums xl:text-[15px] ${
              recoveryPct === null
                ? "text-zinc-400"
                : recoveryPct >= 100
                ? "text-[#10B981]"
                : "text-[#F59E0B]"
            }`}
          >
            {recoveryPct !== null ? `${recoveryPct.toFixed(1)}%` : "N/A"}
          </p>
        </div>
      </div>

      {/* Main Charts Row */}
      <div className="grid gap-5 lg:grid-cols-3">
        {/* Day-by-Day Collection Curve */}
        <div className="rounded-2xl border border-white/[0.08] bg-[#12151E] p-4 sm:p-5 lg:col-span-2">
          <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
            <div>
              <h3 className="font-display text-sm font-bold text-white sm:text-base">
                Day-by-Day India Net Trajectory
              </h3>
              <p className="text-xs text-zinc-400">
                {chartData.length} tracked days (in ₹ Crores)
              </p>
            </div>
            <div className="flex rounded-xl border border-white/[0.08] bg-[#090A0F] p-0.5 text-xs">
              <button
                type="button"
                onClick={() => setChartMode("daily")}
                className={`flex items-center gap-1 rounded-lg px-2.5 py-1 font-medium transition ${
                  chartMode === "daily" ? "bg-white/[0.1] text-white" : "text-zinc-400 hover:text-zinc-200"
                }`}
              >
                <BarChart3 className="h-3.5 w-3.5" />
                Daily
              </button>
              <button
                type="button"
                onClick={() => setChartMode("cumulative")}
                className={`flex items-center gap-1 rounded-lg px-2.5 py-1 font-medium transition ${
                  chartMode === "cumulative" ? "bg-white/[0.1] text-white" : "text-zinc-400 hover:text-zinc-200"
                }`}
              >
                <LineChartIcon className="h-3.5 w-3.5" />
                Cumulative
              </button>
            </div>
          </div>

          {chartData.length > 0 ? (
            <div className="h-[240px] w-full">
              <ResponsiveContainer width="100%" height={240}>
                {chartMode === "daily" ? (
                  <BarChart data={chartData} margin={{ top: 8, right: 8, left: -12, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#1E2434" vertical={false} />
                    <XAxis dataKey="dayLabel" stroke="#71717A" fontSize={11} tickLine={false} />
                    <YAxis stroke="#71717A" fontSize={11} tickLine={false} />
                    <Tooltip
                      content={({ active, payload }) => {
                        if (!active || !payload?.length) return null;
                        const row = payload[0].payload as (typeof chartData)[number];
                        return (
                          <div className="rounded-xl border border-white/15 bg-[#090A0F]/95 p-3 text-xs shadow-xl">
                            <p className="font-semibold text-white">
                              Day {row.day} {row.date ? `• ${row.date}` : ""}
                            </p>
                            <p className="mt-1 font-mono font-bold tabular-nums text-[#10B981]">
                              {formatCrores(row.india_net_cr)}
                            </p>
                            {row.change_pct !== null && (
                              <p
                                className={`mt-0.5 font-mono text-[11px] tabular-nums ${
                                  row.change_pct >= 0 ? "text-[#34D399]" : "text-rose-400"
                                }`}
                              >
                                {row.change_pct >= 0 ? "+" : ""}
                                {row.change_pct.toFixed(1)}% vs prev day
                              </p>
                            )}
                          </div>
                        );
                      }}
                    />
                    <Bar dataKey="india_net_cr" radius={[4, 4, 0, 0]}>
                      {chartData.map((entry) => (
                        <Cell
                          key={entry.day}
                          fill={
                            entry.change_pct === null || entry.change_pct >= 0
                              ? "#10B981"
                              : "#F59E0B"
                          }
                        />
                      ))}
                    </Bar>
                  </BarChart>
                ) : (
                  <AreaChart data={chartData} margin={{ top: 8, right: 8, left: -12, bottom: 0 }}>
                    <defs>
                      <linearGradient id="cumGold" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#F59E0B" stopOpacity={0.45} />
                        <stop offset="95%" stopColor="#F59E0B" stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke="#1E2434" vertical={false} />
                    <XAxis dataKey="dayLabel" stroke="#71717A" fontSize={11} tickLine={false} />
                    <YAxis stroke="#71717A" fontSize={11} tickLine={false} />
                    <Tooltip
                      content={({ active, payload }) => {
                        if (!active || !payload?.length) return null;
                        const row = payload[0].payload as (typeof chartData)[number];
                        return (
                          <div className="rounded-xl border border-white/15 bg-[#090A0F]/95 p-3 text-xs shadow-xl">
                            <p className="font-semibold text-white">Day {row.day}</p>
                            <p className="mt-1 font-mono font-bold tabular-nums text-[#F59E0B]">
                              Cumulative: {formatCrores(row.cumulative_cr)}
                            </p>
                            <p className="mt-0.5 font-mono tabular-nums text-zinc-300">
                              Day Net: {formatCrores(row.india_net_cr)}
                            </p>
                          </div>
                        );
                      }}
                    />
                    <Area
                      type="monotone"
                      dataKey="cumulative_cr"
                      stroke="#F59E0B"
                      strokeWidth={2.5}
                      fill="url(#cumGold)"
                    />
                  </AreaChart>
                )}
              </ResponsiveContainer>
            </div>
          ) : (
            <div className="flex h-64 items-center justify-center rounded-xl border border-dashed border-white/[0.08] text-xs text-zinc-500">
              No day-by-day array reported yet for this title.
            </div>
          )}
        </div>

        {/* Regional Split Donut + ROI Meter */}
        <div className="flex flex-col gap-5">
          <div className="rounded-2xl border border-white/[0.08] bg-[#12151E] p-4 sm:p-5">
            <h3 className="font-display text-sm font-bold text-white">
              India Gross vs. Overseas Split
            </h3>
            {regionalData.length > 0 ? (
              <div className="mt-2 flex flex-col items-center gap-4 sm:flex-row">
                <div className="h-36 w-full max-w-[160px] shrink-0">
                  <ResponsiveContainer width="100%" height={144}>
                    <PieChart>
                      <Pie
                        data={regionalData}
                        dataKey="value"
                        nameKey="name"
                        innerRadius={38}
                        outerRadius={58}
                        paddingAngle={3}
                      >
                        {regionalData.map((item) => (
                          <Cell key={item.name} fill={item.color} />
                        ))}
                      </Pie>
                      <Tooltip
                        formatter={(val: number) => formatCrores(val)}
                        contentStyle={{
                          backgroundColor: "#090A0F",
                          borderColor: "rgba(255,255,255,0.12)",
                          borderRadius: "0.75rem",
                          fontSize: "12px",
                        }}
                      />
                    </PieChart>
                  </ResponsiveContainer>
                </div>
                <div className="space-y-2.5 text-xs">
                  {regionalData.map((item) => {
                    const share = regionalTotal > 0 ? (item.value / regionalTotal) * 100 : 0;
                    return (
                      <div key={item.name}>
                        <div className="flex items-center gap-1.5 text-zinc-400">
                          <span
                            className="h-2.5 w-2.5 rounded-full"
                            style={{ backgroundColor: item.color }}
                          />
                          <span>{item.name}</span>
                        </div>
                        <p className="font-mono font-bold tabular-nums text-white">
                          {formatCrores(item.value)}{" "}
                          <span className="text-[11px] font-normal text-zinc-400">
                            ({share.toFixed(1)}%)
                          </span>
                        </p>
                      </div>
                    );
                  })}
                </div>
              </div>
            ) : (
              <p className="mt-4 text-xs text-zinc-500">Regional split unavailable.</p>
            )}
          </div>

          <div className="rounded-2xl border border-white/[0.08] bg-[#12151E] p-4 sm:p-5">
            <div className="flex items-center justify-between">
              <h3 className="font-display text-sm font-bold text-white">ROI &amp; Verdict Meter</h3>
              {roiMultiple !== null && (
                <span className="rounded-md bg-[#F59E0B]/15 px-2 py-0.5 font-mono text-xs font-bold tabular-nums text-[#F59E0B]">
                  {roiMultiple.toFixed(2)}x Gross
                </span>
              )}
            </div>
            <div className="mt-3 space-y-2 text-xs">
              <div className="flex justify-between text-zinc-400">
                <span>Budget Recovery</span>
                <span className="font-mono font-semibold tabular-nums text-white">
                  {recoveryPct !== null ? `${recoveryPct.toFixed(1)}%` : "Budget Unknown"}
                </span>
              </div>
              <div className="relative h-3 w-full overflow-hidden rounded-full bg-[#090A0F]">
                <div
                  className={`h-full rounded-full transition-all duration-500 ${
                    recoveryPct === null
                      ? "bg-zinc-700"
                      : recoveryPct >= 200
                      ? "bg-gradient-to-r from-[#10B981] to-[#F59E0B]"
                      : recoveryPct >= 100
                      ? "bg-[#10B981]"
                      : "bg-amber-600"
                  }`}
                  style={{
                    width: `${recoveryPct !== null ? Math.min(100, Math.max(4, recoveryPct / 2)) : 0}%`,
                  }}
                />
                <div
                  title="100% Budget Breakeven"
                  className="absolute bottom-0 top-0 left-1/2 w-0.5 bg-white/60"
                />
              </div>
              <div className="flex justify-between text-[10px] text-zinc-500">
                <span>0%</span>
                <span>100% Breakeven</span>
                <span>200%+ Blockbuster</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Shareable Box Office Report Card Generator */}
      <div className="rounded-2xl border border-white/[0.08] bg-[#12151E] p-4 sm:p-5">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <div>
            <h3 className="flex items-center gap-2 font-display text-sm font-bold text-white sm:text-base">
              <Share2 className="h-4 w-4 text-[#F59E0B]" />
              Shareable Box Office Report Card
            </h3>
            <p className="text-xs text-zinc-400">
              Export a high-resolution PNG card for X, Instagram, or WhatsApp updates.
            </p>
          </div>
          <button
            type="button"
            onClick={() => void handleExportReportPng()}
            disabled={exportingPng}
            className="inline-flex items-center gap-2 rounded-xl bg-[#10B981] px-4 py-2 text-xs font-bold text-black transition hover:bg-emerald-400 disabled:opacity-60"
          >
            <Download className="h-3.5 w-3.5" />
            {exportingPng ? "Rendering PNG..." : "Download PNG Card"}
          </button>
        </div>

        {exportNote && (
          <p className="mb-3 text-xs font-medium text-[#34D399]">{exportNote}</p>
        )}

        <div
          ref={shareCardRef}
          className="relative overflow-hidden rounded-2xl border border-[#F59E0B]/30 bg-gradient-to-br from-[#090A0F] via-[#12151E] to-[#090A0F] p-6"
        >
          <div className="flex flex-col justify-between gap-5 sm:flex-row sm:items-center">
            <div className="flex items-center gap-4">
              <div className="h-24 w-16 shrink-0 overflow-hidden rounded-xl border border-white/15 bg-[#090A0F]">
                <MoviePoster
                  movie={movie}
                  compact
                  crossOrigin="anonymous"
                  className="h-full w-full object-cover"
                />
              </div>
              <div>
                <div className="flex flex-wrap items-center gap-2">
                  <BrandLogo variant="full" size="sm" showLiveBadge={false} />
                  <span className="font-mono text-[10px] font-bold uppercase tracking-widest text-[#F59E0B]">
                    • Official Report
                  </span>
                </div>
                <h4 className="mt-1.5 font-display text-xl font-bold text-white sm:text-2xl">
                  {movie.title}
                </h4>
                <div className="mt-1.5 flex flex-wrap items-center gap-2 text-xs text-zinc-300">
                  <span>{movie.language}</span>
                  <span>•</span>
                  <span>Day {movie.day_count}</span>
                  <span>•</span>
                  <span className="font-semibold text-[#34D399]">{verdictMeta.label}</span>
                </div>
              </div>
            </div>

            <div className="grid grid-cols-3 gap-4 border-t border-white/[0.08] pt-4 sm:border-l sm:border-t-0 sm:pl-6 sm:pt-0">
              <div>
                <p className="text-[10px] uppercase tracking-wider text-zinc-500">India Net</p>
                <p className="mt-0.5 font-mono text-base font-bold tabular-nums text-[#10B981]">
                  {formatCrores(movie.india_net_cr)}
                </p>
              </div>
              <div>
                <p className="text-[10px] uppercase tracking-wider text-zinc-500">Overseas</p>
                <p className="mt-0.5 font-mono text-base font-bold tabular-nums text-zinc-100">
                  {formatCrores(movie.overseas_cr)}
                </p>
              </div>
              <div>
                <p className="text-[10px] uppercase tracking-wider text-zinc-500">Worldwide</p>
                <p className="mt-0.5 font-mono text-base font-bold tabular-nums text-[#F59E0B]">
                  {formatCrores(movie.worldwide_gross_cr)}
                </p>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Day-by-Day Table with Trend Arrows */}
      {movie.daily_breakdown.length > 0 && (
        <div className="rounded-2xl border border-white/[0.08] bg-[#12151E] p-4 sm:p-5">
          <h3 className="mb-3 font-display text-sm font-bold text-white">
            Daily Collection Ledger
          </h3>
          <div className="max-h-72 overflow-x-auto overflow-y-auto rounded-xl border border-white/[0.07]">
            <table className="w-full min-w-[420px] text-left text-xs">
              <thead className="sticky top-0 bg-[#090A0F] text-[11px] uppercase text-zinc-400">
                <tr>
                  <th className="whitespace-nowrap px-3 py-2.5">Day</th>
                  <th className="whitespace-nowrap px-3 py-2.5">Date</th>
                  {hasShowsColumn && (
                    <th className="whitespace-nowrap px-3 py-2.5 text-right">Shows / Occ.</th>
                  )}
                  <th className="whitespace-nowrap px-3 py-2.5 text-right">India Net</th>
                  <th className="whitespace-nowrap px-3 py-2.5 text-right">Day-over-Day</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/[0.06]">
                {movie.daily_breakdown.map((d) => (
                  <tr key={d.day} className="hover:bg-white/[0.03]">
                    <td className="px-3 py-2 font-mono font-semibold text-white">
                      {d.day === 0 ? "Day 0 (Previews)" : `Day ${d.day}`}
                    </td>
                    <td className="px-3 py-2 font-mono tabular-nums text-zinc-400">
                      {d.date ?? "—"}
                    </td>
                    {hasShowsColumn && (
                      <td className="px-3 py-2 text-right font-mono tabular-nums text-zinc-300">
                        {d.shows ? d.shows.toLocaleString("en-IN") : "—"}
                        {d.occupancy_pct !== null && d.occupancy_pct !== undefined
                          ? ` • ${d.occupancy_pct.toFixed(1)}%`
                          : ""}
                      </td>
                    )}
                    <td className="px-3 py-2 text-right font-mono font-semibold tabular-nums text-[#10B981]">
                      {formatCrores(d.india_net_cr)}
                    </td>
                    <td className="px-3 py-2 text-right font-mono tabular-nums">
                      {d.change_pct === null ? (
                        <span className="text-zinc-500">—</span>
                      ) : d.change_pct >= 0 ? (
                        <span className="inline-flex items-center justify-end gap-0.5 font-semibold text-[#10B981]">
                          <ArrowUpRight className="h-3.5 w-3.5" />+{d.change_pct.toFixed(1)}%
                        </span>
                      ) : (
                        <span className="inline-flex items-center justify-end gap-0.5 font-semibold text-rose-400">
                          <ArrowDownRight className="h-3.5 w-3.5" />
                          {d.change_pct.toFixed(1)}%
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* White-Label Intelligence Attribution */}
      <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-zinc-500">
        <div className="flex items-center gap-2">
          <CheckCircle2 className="h-3.5 w-3.5 text-[#10B981]" />
          <span>
            Verified Feed:{" "}
            <strong className="text-zinc-300">{formatSourceLabel(movie.primary_source)}</strong>
          </span>
        </div>
        <span className="font-mono text-[11px] text-zinc-500">
          CineTracker Multi-Source Index
        </span>
      </div>
    </div>
  );
}
