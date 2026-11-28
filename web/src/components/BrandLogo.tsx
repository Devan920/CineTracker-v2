import { useId } from "react";

export type BrandLogoVariant = "full" | "icon";
export type BrandLogoSize = "sm" | "md" | "lg";

interface BrandLogoProps {
  variant?: BrandLogoVariant;
  size?: BrandLogoSize;
  showLiveBadge?: boolean;
  animated?: boolean;
  subtitle?: string;
  className?: string;
}

const SIZE_MAP: Record<
  BrandLogoSize,
  {
    iconPx: string;
    gap: string;
    wordmarkText: string;
    badgeText: string;
    badgePad: string;
    dotSize: string;
    subtitleText: string;
  }
> = {
  sm: {
    iconPx: "h-8 w-8",
    gap: "gap-2",
    wordmarkText: "text-sm sm:text-[15px]",
    badgeText: "text-[8px]",
    badgePad: "px-1.5 py-0.5",
    dotSize: "h-1.5 w-1.5",
    subtitleText: "text-[10px]",
  },
  md: {
    iconPx: "h-9 w-9 sm:h-10 sm:w-10",
    gap: "gap-2 sm:gap-2.5",
    wordmarkText: "text-sm sm:text-base",
    badgeText: "text-[9px]",
    badgePad: "px-1.5 py-0.5",
    dotSize: "h-1.5 w-1.5",
    subtitleText: "text-[10px] sm:text-[11px]",
  },
  lg: {
    iconPx: "h-11 w-11 sm:h-12 sm:w-12",
    gap: "gap-3",
    wordmarkText: "text-lg sm:text-xl",
    badgeText: "text-[10px]",
    badgePad: "px-2 py-0.5",
    dotSize: "h-2 w-2",
    subtitleText: "text-xs",
  },
};

export function BrandLogo({
  variant = "full",
  size = "md",
  showLiveBadge = true,
  animated = false,
  subtitle,
  className = "",
}: BrandLogoProps) {
  const uid = useId().replace(/:/g, "");
  const s = SIZE_MAP[size];

  const borderGradId = `ct-border-${uid}`;
  const bgGradId = `ct-bg-${uid}`;
  const goldGradId = `ct-gold-${uid}`;
  const emeraldGradId = `ct-emerald-${uid}`;
  const trendGradId = `ct-trend-${uid}`;

  return (
    <div
      className={`inline-flex min-w-0 items-center ${s.gap} ${
        animated ? "ct-anim-icon" : ""
      } ${className}`}
    >
      {/* Razor-Sharp Vector Obsidian & Gold/Emerald Aperture Mark */}
      <svg
        viewBox="0 0 64 64"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        aria-hidden="true"
        className={`${s.iconPx} shrink-0 drop-shadow-[0_4px_12px_rgba(245,158,11,0.18)]`}
      >
        <defs>
          <linearGradient id={bgGradId} x1="6" y1="4" x2="58" y2="60" gradientUnits="userSpaceOnUse">
            <stop offset="0%" stopColor="#161C2C" />
            <stop offset="55%" stopColor="#0F131E" />
            <stop offset="100%" stopColor="#090C14" />
          </linearGradient>
          <linearGradient id={borderGradId} x1="2" y1="2" x2="62" y2="62" gradientUnits="userSpaceOnUse">
            <stop offset="0%" stopColor="#F59E0B" stopOpacity="0.95" />
            <stop offset="50%" stopColor="#FBBF24" stopOpacity="0.45" />
            <stop offset="100%" stopColor="#10B981" stopOpacity="0.9" />
          </linearGradient>
          <linearGradient id={goldGradId} x1="12" y1="14" x2="42" y2="52" gradientUnits="userSpaceOnUse">
            <stop offset="0%" stopColor="#FDE68A" />
            <stop offset="55%" stopColor="#F59E0B" />
            <stop offset="100%" stopColor="#D97706" />
          </linearGradient>
          <linearGradient id={emeraldGradId} x1="25" y1="24" x2="45" y2="47" gradientUnits="userSpaceOnUse">
            <stop offset="0%" stopColor="#34D399" />
            <stop offset="100%" stopColor="#10B981" />
          </linearGradient>
          <linearGradient id={trendGradId} x1="23" y1="36" x2="50" y2="15" gradientUnits="userSpaceOnUse">
            <stop offset="0%" stopColor="#10B981" />
            <stop offset="100%" stopColor="#FDE047" />
          </linearGradient>
        </defs>

        {/* Rounded Obsidian Housing with Subtle Metallic Gold-to-Emerald Border */}
        <rect x="2.5" y="2.5" width="59" height="59" rx="14.5" fill={`url(#${bgGradId})`} />
        <rect
          x="2.5"
          y="2.5"
          width="59"
          height="59"
          rx="14.5"
          stroke={`url(#${borderGradId})`}
          strokeWidth="2.25"
        />

        {/* Subtle Inner Aperture Hairline */}
        <rect
          x="6.5"
          y="6.5"
          width="51"
          height="51"
          rx="11"
          stroke="rgba(255,255,255,0.06)"
          strokeWidth="1"
        />

        {/* Clapperboard / Cinema Frame Sprocket Accents */}
        <rect x="14" y="10.5" width="6" height="2" rx="1" fill="rgba(245,158,11,0.45)" />
        <rect x="23" y="10.5" width="6" height="2" rx="1" fill="rgba(245,158,11,0.28)" />

        {/* Geometric "C" Cinema Aperture Arc */}
        <path
          d="M 41 18.5 A 16.5 16.5 0 1 0 41 46"
          pathLength={animated ? 100 : undefined}
          stroke={`url(#${goldGradId})`}
          strokeWidth="4.6"
          strokeLinecap="round"
          className={animated ? "ct-anim-aperture" : undefined}
        />

        {/* 3 Ascending Box-Office Revenue Bars */}
        <rect
          x="25.5"
          y="34"
          width="4.5"
          height="9.5"
          rx="1.4"
          fill={`url(#${emeraldGradId})`}
          className={animated ? "ct-anim-bar-1" : undefined}
        />
        <rect
          x="32.5"
          y="29"
          width="4.5"
          height="14.5"
          rx="1.4"
          fill={`url(#${emeraldGradId})`}
          className={animated ? "ct-anim-bar-2" : undefined}
        />
        <rect
          x="39.5"
          y="23.5"
          width="4.5"
          height="20"
          rx="1.4"
          fill={`url(#${goldGradId})`}
          className={animated ? "ct-anim-bar-3" : undefined}
        />

        {/* Sharp Upward Trend Vector & Arrowhead */}
        <path
          d="M 24.5 29.5 L 33.5 23 L 46.5 14"
          pathLength={animated ? 100 : undefined}
          stroke={`url(#${trendGradId})`}
          strokeWidth="2.75"
          strokeLinecap="round"
          strokeLinejoin="round"
          className={animated ? "ct-anim-trend" : undefined}
        />
        <path
          d="M 40.5 13.5 L 47.5 13.2 L 46.8 20.2"
          pathLength={animated ? 100 : undefined}
          stroke="#FDE047"
          strokeWidth="2.6"
          strokeLinecap="round"
          strokeLinejoin="round"
          className={animated ? "ct-anim-arrowhead" : undefined}
        />
      </svg>

      {variant === "full" && (
        <div className="min-w-0">
          <div className="flex items-center gap-1.5 leading-none">
            <span
              className={`inline-flex items-baseline font-display font-bold tracking-[0.04em] ${s.wordmarkText}`}
            >
              <span className="text-[#F8FAFC]">CINE</span>
              <span className="bg-gradient-to-r from-[#F59E0B] via-[#FBBF24] to-[#F59E0B] bg-clip-text text-transparent">
                TRACKER
              </span>
            </span>

            {showLiveBadge && (
              <span
                className={`hidden shrink-0 items-center gap-1 rounded-full border border-[#10B981]/35 bg-[#10B981]/10 font-mono font-bold uppercase tracking-wider text-[#34D399] sm:inline-flex ${s.badgePad} ${s.badgeText}`}
              >
                <span className={`animate-pulse rounded-full bg-[#10B981] ${s.dotSize}`} />
                <span>LIVE BO</span>
              </span>
            )}
          </div>

          {subtitle && (
            <p className={`mt-0.5 hidden truncate whitespace-nowrap text-zinc-400 sm:block ${s.subtitleText}`}>
              {subtitle}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
