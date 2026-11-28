import { motion } from "framer-motion";
import {
  isMovieLiveRunning,
  LANGUAGE_FILTERS,
  LIVE_RUNNING_FILTER,
  type LanguageFilter,
} from "../../lib/formatters";
import type { MovieRecord } from "../../lib/supabase";

interface LanguagePillsProps {
  selectedLanguage: LanguageFilter;
  onSelect: (lang: LanguageFilter) => void;
  movies: MovieRecord[];
}

export function LanguagePills({ selectedLanguage, onSelect, movies }: LanguagePillsProps) {
  const counts = LANGUAGE_FILTERS.reduce<Record<string, number>>((acc, lang) => {
    if (lang === "All") {
      acc[lang] = movies.length;
    } else if (lang === LIVE_RUNNING_FILTER) {
      acc[lang] = movies.filter((m) => isMovieLiveRunning(m)).length;
    } else {
      acc[lang] = movies.filter(
        (m) => m.language.toLowerCase() === lang.toLowerCase()
      ).length;
    }
    return acc;
  }, {});

  return (
    <div className="no-scrollbar flex items-center gap-2 overflow-x-auto pb-1 pt-0.5">
      {LANGUAGE_FILTERS.map((lang) => {
        const active = selectedLanguage === lang;
        const isLivePill = lang === LIVE_RUNNING_FILTER;
        return (
          <button
            key={lang}
            type="button"
            onClick={() => onSelect(lang)}
            className={`relative inline-flex min-h-[40px] shrink-0 items-center whitespace-nowrap rounded-full px-3.5 py-2 text-xs font-semibold transition-colors ${
              active
                ? "text-black"
                : isLivePill
                ? "border border-[#10B981]/35 bg-[#10B981]/10 text-[#34D399] hover:border-[#10B981]/60 hover:bg-[#10B981]/15"
                : "border border-white/[0.08] bg-[#12151E] text-zinc-300 hover:border-white/20 hover:text-white"
            }`}
          >
            {active && (
              <motion.span
                layoutId="active-language-pill"
                transition={{ type: "spring", stiffness: 420, damping: 32 }}
                className={`absolute inset-0 rounded-full ${
                  isLivePill ? "bg-[#10B981]" : "bg-[#F59E0B]"
                }`}
              />
            )}
            <span className="relative z-10 flex items-center gap-1.5">
              <span>{lang}</span>
              <span
                className={`rounded-full px-1.5 py-0.2 font-mono text-[10px] tabular-nums ${
                  active
                    ? "bg-black/15 text-black"
                    : isLivePill
                    ? "bg-[#10B981]/20 text-[#34D399]"
                    : "bg-white/[0.06] text-zinc-400"
                }`}
              >
                {counts[lang] ?? 0}
              </span>
            </span>
          </button>
        );
      })}
    </div>
  );
}
