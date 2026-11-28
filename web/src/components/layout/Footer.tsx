import { GitCompare, ShieldCheck, TrendingUp } from "lucide-react";
import { Link } from "react-router-dom";
import { BrandLogo } from "../BrandLogo";

export function Footer() {
  return (
    <footer className="mt-12 border-t border-white/[0.08] bg-[#090A0F]">
      <div className="mx-auto flex max-w-7xl flex-col gap-4 px-4 py-6 sm:flex-row sm:items-center sm:justify-between sm:px-6">
        <div className="flex min-w-0 flex-wrap items-center gap-3 text-xs text-zinc-400">
          <Link to="/" className="focus:outline-none">
            <BrandLogo variant="full" size="sm" showLiveBadge={false} />
          </Link>
          <span className="hidden text-zinc-600 sm:inline">•</span>
          <span className="truncate">Real-Time Indian &amp; Malayalam Box Office Intelligence</span>
        </div>

        <div className="flex flex-wrap items-center gap-4 text-xs">
          <Link
            to="/"
            className="inline-flex items-center gap-1.5 text-zinc-400 transition hover:text-zinc-200"
          >
            <TrendingUp className="h-3.5 w-3.5 text-[#10B981]" />
            Box Office Grid
          </Link>
          <Link
            to="/compare"
            className="inline-flex items-center gap-1.5 text-zinc-400 transition hover:text-zinc-200"
          >
            <GitCompare className="h-3.5 w-3.5 text-sky-400" />
            Compare Movies
          </Link>
          <span className="h-3 w-px bg-white/[0.1]" />
          <Link
            to="/admin"
            className="inline-flex items-center gap-1.5 rounded-lg border border-white/[0.08] bg-[#12151E] px-2.5 py-1.5 text-xs font-medium text-zinc-300 transition hover:border-[#F59E0B]/40 hover:text-[#F59E0B]"
          >
            <ShieldCheck className="h-3.5 w-3.5 text-[#F59E0B]" />
            Admin Portal
          </Link>
        </div>
      </div>
    </footer>
  );
}
