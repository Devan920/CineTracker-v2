import { Flame, GitCompare, Sparkles } from "lucide-react";
import { Link } from "react-router-dom";

interface MobileBottomNavProps {
  activeTab: "trending" | "malayalam" | "compare" | "admin";
  compareCount: number;
  onSelectTrending: () => void;
  onSelectMalayalam: () => void;
}

export function MobileBottomNav({
  activeTab,
  compareCount,
  onSelectTrending,
  onSelectMalayalam,
}: MobileBottomNavProps) {
  return (
    <nav
      aria-label="Mobile Bottom Navigation"
      className="fixed inset-x-0 bottom-0 z-40 border-t border-white/[0.08] bg-[#090A0F]/95 backdrop-blur-xl md:hidden"
      style={{ paddingBottom: "env(safe-area-inset-bottom)" }}
    >
      <div className="grid grid-cols-3">
        <Link
          to="/"
          onClick={onSelectTrending}
          className={`flex min-h-[52px] flex-col items-center justify-center gap-1 py-2 text-[11px] font-medium transition-colors ${
            activeTab === "trending" ? "text-[#F59E0B]" : "text-zinc-400 hover:text-zinc-200"
          }`}
        >
          <Flame className="h-4 w-4" />
          <span>Trending</span>
        </Link>

        <Link
          to="/"
          onClick={onSelectMalayalam}
          className={`flex min-h-[52px] flex-col items-center justify-center gap-1 py-2 text-[11px] font-medium transition-colors ${
            activeTab === "malayalam" ? "text-[#10B981]" : "text-zinc-400 hover:text-zinc-200"
          }`}
        >
          <Sparkles className="h-4 w-4" />
          <span>Malayalam</span>
        </Link>

        <Link
          to="/compare"
          className={`relative flex min-h-[52px] flex-col items-center justify-center gap-1 py-2 text-[11px] font-medium transition-colors ${
            activeTab === "compare" ? "text-sky-400" : "text-zinc-400 hover:text-zinc-200"
          }`}
        >
          <div className="relative">
            <GitCompare className="h-4 w-4" />
            {compareCount > 0 && (
              <span className="absolute -right-2.5 -top-1.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-[#F59E0B] px-1 font-mono text-[9px] font-bold tabular-nums text-black">
                {compareCount}
              </span>
            )}
          </div>
          <span>Compare</span>
        </Link>
      </div>
    </nav>
  );
}
