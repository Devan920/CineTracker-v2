import { ArrowLeftRight, GitCompare, Trophy } from "lucide-react";
import { useMemo, useState } from "react";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  computeBudgetRecoveryPct,
  computeMovieMilestones,
  formatCrores,
  getVerdictStyle,
} from "../../lib/formatters";
import type { MovieRecord } from "../../lib/supabase";

interface ComparisonViewProps {
  movies: MovieRecord[];
  selectedSlugs: string[];
  onChangeSlugs: (next: string[]) => void;
}

export function ComparisonView({
  movies,
  selectedSlugs,
  onChangeSlugs,
}: ComparisonViewProps) {
  const [metricMode, setMetricMode] = useState<"cumulative" | "daily">("cumulative");

  const slugA =
    selectedSlugs[0] && movies.some((m) => m.movie_slug === selectedSlugs[0])
      ? selectedSlugs[0]
      : movies[0]?.movie_slug ?? "";
  const slugB =
    selectedSlugs[1] && movies.some((m) => m.movie_slug === selectedSlugs[1])
      ? selectedSlugs[1]
      : movies.find((m) => m.movie_slug !== slugA)?.movie_slug ??
        movies[0]?.movie_slug ??
        "";

  const movieA = movies.find((m) => m.movie_slug === slugA) ?? null;
  const movieB = movies.find((m) => m.movie_slug === slugB) ?? null;

  const milestonesA = useMemo(
    () => computeMovieMilestones(movieA?.daily_breakdown ?? []),
    [movieA]
  );
  const milestonesB = useMemo(
    () => computeMovieMilestones(movieB?.daily_breakdown ?? []),
    [movieB]
  );

  const trajectoryData = useMemo(() => {
    if (!movieA && !movieB) return [];
    const mapA = new Map<number, number>();
    const mapB = new Map<number, number>();
    (movieA?.daily_breakdown ?? []).forEach((d) => mapA.set(d.day, d.india_net_cr));
    (movieB?.daily_breakdown ?? []).forEach((d) => mapB.set(d.day, d.india_net_cr));

    const allDays = Array.from(new Set([...mapA.keys(), ...mapB.keys()])).sort((a, b) => a - b);
    let cumA = 0;
    let cumB = 0;

    return allDays.map((day) => {
      const valA = mapA.get(day);
      const valB = mapB.get(day);
      if (valA !== undefined) cumA = Number((cumA + valA).toFixed(2));
      if (valB !== undefined) cumB = Number((cumB + valB).toFixed(2));

      return {
        dayLabel: `D${day}`,
        day,
        aDaily: valA ?? null,
        bDaily: valB ?? null,
        aCumulative: valA !== undefined || day <= (movieA?.day_count ?? 0) ? cumA : null,
        bCumulative: valB !== undefined || day <= (movieB?.day_count ?? 0) ? cumB : null,
      };
    });
  }, [movieA, movieB]);

  if (movies.length < 2) {
    return (
      <div className="rounded-2xl border border-zinc-800 bg-[#18181B] p-8 text-center">
        <GitCompare className="mx-auto h-8 w-8 text-zinc-500" />
        <h2 className="mt-3 font-display text-lg font-bold text-white">
          Comparison Mode Needs At Least 2 Movies
        </h2>
        <p className="mt-1 text-xs text-zinc-400">
          Sync at least two movies in Supabase to overlay Day 1, Weekend 1, and cumulative box office curves.
        </p>
      </div>
    );
  }

  const recoveryA = movieA ? computeBudgetRecoveryPct(movieA) : null;
  const recoveryB = movieB ? computeBudgetRecoveryPct(movieB) : null;

  const rows: Array<{
    label: string;
    valA: string;
    valB: string;
    rawA: number | null;
    rawB: number | null;
  }> = [
    {
      label: "Day 1 Opening (India Net)",
      valA: formatCrores(milestonesA.day1),
      valB: formatCrores(milestonesB.day1),
      rawA: milestonesA.day1,
      rawB: milestonesB.day1,
    },
    {
      label: "Weekend 1 (Up to Day 3)",
      valA: formatCrores(milestonesA.weekend1),
      valB: formatCrores(milestonesB.weekend1),
      rawA: milestonesA.weekend1,
      rawB: milestonesB.weekend1,
    },
    {
      label: "Week 1 (Up to Day 7)",
      valA: formatCrores(milestonesA.week1),
      valB: formatCrores(milestonesB.week1),
      rawA: milestonesA.week1,
      rawB: milestonesB.week1,
    },
    {
      label: "Total India Net",
      valA: formatCrores(movieA?.india_net_cr),
      valB: formatCrores(movieB?.india_net_cr),
      rawA: movieA?.india_net_cr ?? null,
      rawB: movieB?.india_net_cr ?? null,
    },
    {
      label: "Worldwide Gross",
      valA: formatCrores(movieA?.worldwide_gross_cr),
      valB: formatCrores(movieB?.worldwide_gross_cr),
      rawA: movieA?.worldwide_gross_cr ?? null,
      rawB: movieB?.worldwide_gross_cr ?? null,
    },
    {
      label: "Budget Recovery %",
      valA: recoveryA !== null ? `${recoveryA.toFixed(1)}%` : "—",
      valB: recoveryB !== null ? `${recoveryB.toFixed(1)}%` : "—",
      rawA: recoveryA,
      rawB: recoveryB,
    },
  ];

  return (
    <div className="space-y-6">
      {/* Header & Movie Pickers */}
      <div className="rounded-2xl border border-zinc-800 bg-[#18181B] p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="flex items-center gap-2 font-display text-xl font-bold text-white sm:text-2xl">
              <GitCompare className="h-5 w-5 text-[#EAB308]" />
              Box Office Clash — Head-to-Head Comparison
            </h1>
            <p className="mt-0.5 text-xs text-zinc-400">
              Compare Day 1, Weekend 1, and full theatrical trajectories side-by-side.
            </p>
          </div>
          <button
            type="button"
            onClick={() => onChangeSlugs([slugB, slugA])}
            className="inline-flex items-center gap-1.5 rounded-xl border border-zinc-700 bg-[#09090B] px-3 py-1.5 text-xs font-medium text-zinc-200 hover:border-zinc-600"
          >
            <ArrowLeftRight className="h-3.5 w-3.5 text-[#EAB308]" />
            Swap Sides
          </button>
        </div>

        <div className="mt-4 grid gap-4 sm:grid-cols-2">
          <div className="rounded-xl border border-[#EAB308]/35 bg-[#09090B]/80 p-3.5">
            <label className="block text-[11px] font-semibold uppercase tracking-wider text-[#EAB308]">
              Contender A (Gold Curve)
            </label>
            <select
              value={slugA}
              onChange={(e) => onChangeSlugs([e.target.value, slugB])}
              className="mt-1.5 w-full rounded-lg border border-zinc-700 bg-[#18181B] px-3 py-2 text-sm font-medium text-white focus:border-[#EAB308] focus:outline-none"
            >
              {movies.map((m) => (
                <option key={m.movie_slug} value={m.movie_slug}>
                  {m.title} ({m.language}) — {formatCrores(m.india_net_cr)}
                </option>
              ))}
            </select>
            {movieA && (
              <div className="mt-2.5 flex items-center gap-2 text-xs text-zinc-400">
                <span className={`rounded px-2 py-0.5 text-[11px] font-semibold ${getVerdictStyle(movieA.verdict).className}`}>
                  {getVerdictStyle(movieA.verdict).label}
                </span>
                <span>Day {movieA.day_count}</span>
              </div>
            )}
          </div>

          <div className="rounded-xl border border-[#10B981]/35 bg-[#09090B]/80 p-3.5">
            <label className="block text-[11px] font-semibold uppercase tracking-wider text-[#10B981]">
              Contender B (Emerald Curve)
            </label>
            <select
              value={slugB}
              onChange={(e) => onChangeSlugs([slugA, e.target.value])}
              className="mt-1.5 w-full rounded-lg border border-zinc-700 bg-[#18181B] px-3 py-2 text-sm font-medium text-white focus:border-[#10B981] focus:outline-none"
            >
              {movies.map((m) => (
                <option key={m.movie_slug} value={m.movie_slug}>
                  {m.title} ({m.language}) — {formatCrores(m.india_net_cr)}
                </option>
              ))}
            </select>
            {movieB && (
              <div className="mt-2.5 flex items-center gap-2 text-xs text-zinc-400">
                <span className={`rounded px-2 py-0.5 text-[11px] font-semibold ${getVerdictStyle(movieB.verdict).className}`}>
                  {getVerdictStyle(movieB.verdict).label}
                </span>
                <span>Day {movieB.day_count}</span>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Overlaid Trajectory Chart */}
      <div className="rounded-2xl border border-zinc-800 bg-[#18181B] p-5">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
          <div>
            <h2 className="font-display text-base font-bold text-white">
              Overlaid Theatrical Trajectory (India Net ₹ Cr)
            </h2>
            <p className="text-xs text-zinc-400">Aligned by release day index (Day 0 to Day N)</p>
          </div>
          <div className="flex rounded-xl border border-zinc-800 bg-[#09090B] p-0.5 text-xs">
            <button
              type="button"
              onClick={() => setMetricMode("cumulative")}
              className={`rounded-lg px-3 py-1 font-medium transition ${
                metricMode === "cumulative" ? "bg-zinc-800 text-white" : "text-zinc-400"
              }`}
            >
              Cumulative Curve
            </button>
            <button
              type="button"
              onClick={() => setMetricMode("daily")}
              className={`rounded-lg px-3 py-1 font-medium transition ${
                metricMode === "daily" ? "bg-zinc-800 text-white" : "text-zinc-400"
              }`}
            >
              Daily Collection
            </button>
          </div>
        </div>

        {trajectoryData.length > 0 ? (
          <div className="h-[240px] w-full sm:h-80">
            <ResponsiveContainer width="100%" height={240}>
              <LineChart data={trajectoryData} margin={{ top: 10, right: 12, left: -10, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#27272A" vertical={false} />
                <XAxis dataKey="dayLabel" stroke="#71717A" fontSize={11} tickLine={false} />
                <YAxis stroke="#71717A" fontSize={11} tickLine={false} />
                <Tooltip
                  formatter={(value: number | string) => formatCrores(Number(value))}
                  contentStyle={{
                    backgroundColor: "#090A0F",
                    borderColor: "rgba(255,255,255,0.12)",
                    borderRadius: "0.75rem",
                    fontSize: "12px",
                  }}
                />
                <Legend wrapperStyle={{ fontSize: "12px", paddingTop: "8px" }} />
                <Line
                  type="monotone"
                  name={movieA?.title ?? "Movie A"}
                  dataKey={metricMode === "cumulative" ? "aCumulative" : "aDaily"}
                  stroke="#F59E0B"
                  strokeWidth={2.5}
                  dot={false}
                  connectNulls={false}
                />
                <Line
                  type="monotone"
                  name={movieB?.title ?? "Movie B"}
                  dataKey={metricMode === "cumulative" ? "bCumulative" : "bDaily"}
                  stroke="#10B981"
                  strokeWidth={2.5}
                  dot={false}
                  connectNulls={false}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        ) : (
          <div className="flex h-64 items-center justify-center rounded-xl border border-dashed border-zinc-800 text-xs text-zinc-500">
            Neither selected film has day-wise breakdown rows yet.
          </div>
        )}
      </div>

      {/* Side-by-Side Milestone Table */}
      <div className="overflow-x-auto rounded-2xl border border-white/[0.08] bg-[#12151E]">
        <table className="w-full min-w-[460px] text-left text-xs sm:text-sm">
          <thead className="border-b border-zinc-800 bg-[#09090B] text-[11px] uppercase tracking-wider text-zinc-400">
            <tr>
              <th className="px-4 py-3">Milestone Metric</th>
              <th className="px-4 py-3 text-right text-[#EAB308]">{movieA?.title ?? "Movie A"}</th>
              <th className="px-4 py-3 text-right text-[#10B981]">{movieB?.title ?? "Movie B"}</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-800/70">
            {rows.map((row) => {
              const aLeads =
                row.rawA !== null && row.rawB !== null && row.rawA > row.rawB;
              const bLeads =
                row.rawA !== null && row.rawB !== null && row.rawB > row.rawA;
              return (
                <tr key={row.label} className="hover:bg-zinc-900/50">
                  <td className="px-4 py-3 font-medium text-zinc-300">{row.label}</td>
                  <td
                    className={`px-4 py-3 text-right font-mono font-semibold ${
                      aLeads ? "text-[#EAB308]" : "text-zinc-200"
                    }`}
                  >
                    {aLeads && <Trophy className="mr-1.5 inline h-3.5 w-3.5 text-[#EAB308]" />}
                    {row.valA}
                  </td>
                  <td
                    className={`px-4 py-3 text-right font-mono font-semibold ${
                      bLeads ? "text-[#10B981]" : "text-zinc-200"
                    }`}
                  >
                    {bLeads && <Trophy className="mr-1.5 inline h-3.5 w-3.5 text-[#10B981]" />}
                    {row.valB}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
