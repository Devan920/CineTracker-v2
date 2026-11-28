import { useCallback, useEffect, useRef, useState } from "react";
import { BrandLogo } from "./BrandLogo";

interface SplashScreenProps {
  open: boolean;
  onFinish: () => void;
}

export function SplashScreen({ open, onFinish }: SplashScreenProps) {
  const [exiting, setExiting] = useState(false);
  const finishedRef = useRef(false);
  const exitTimeoutRef = useRef<number | null>(null);
  const holdTimeoutRef = useRef<number | null>(null);

  const reducedMotion =
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  const completeExit = useCallback(
    (exitMs: number) => {
      if (finishedRef.current) return;
      finishedRef.current = true;
      setExiting(true);

      if (holdTimeoutRef.current !== null) {
        window.clearTimeout(holdTimeoutRef.current);
        holdTimeoutRef.current = null;
      }

      exitTimeoutRef.current = window.setTimeout(() => {
        try {
          sessionStorage.setItem("ct_intro_played", "1");
        } catch {
          // ignore private browsing storage errors
        }
        onFinish();
      }, exitMs);
    },
    [onFinish]
  );

  useEffect(() => {
    if (!open) return;
    finishedRef.current = false;
    setExiting(false);

    try {
      sessionStorage.setItem("ct_intro_played", "1");
    } catch {
      // ignore storage errors
    }

    const holdDurationMs = reducedMotion ? 320 : 1680;
    const exitDurationMs = reducedMotion ? 180 : 550;

    holdTimeoutRef.current = window.setTimeout(() => {
      completeExit(exitDurationMs);
    }, holdDurationMs);

    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape" || e.key === "Enter" || e.key === " ") {
        completeExit(reducedMotion ? 150 : 320);
      }
    };
    window.addEventListener("keydown", onKeyDown);

    return () => {
      window.removeEventListener("keydown", onKeyDown);
      if (holdTimeoutRef.current !== null) {
        window.clearTimeout(holdTimeoutRef.current);
      }
      if (exitTimeoutRef.current !== null) {
        window.clearTimeout(exitTimeoutRef.current);
      }
    };
  }, [open, reducedMotion, completeExit]);

  if (!open) return null;

  const exitTransition = reducedMotion
    ? "opacity 180ms ease-out"
    : "opacity 550ms cubic-bezier(0.22, 1, 0.36, 1), transform 550ms cubic-bezier(0.22, 1, 0.36, 1)";

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="CineTracker brand intro splash screen"
      onClick={() => completeExit(reducedMotion ? 150 : 320)}
      style={{
        opacity: exiting ? 0 : 1,
        transform: exiting && !reducedMotion ? "scale(1.04) translateY(-8px)" : "scale(1) translateY(0px)",
        transition: exitTransition,
        willChange: "transform, opacity",
      }}
      className={`fixed inset-0 z-[100] flex select-none flex-col items-center justify-center overflow-hidden bg-[#06070B] px-6 ${
        exiting ? "pointer-events-none" : "cursor-pointer pointer-events-auto"
      }`}
    >
      {/* Ambient Radial Golden-Emerald Spotlight */}
      <div
        aria-hidden="true"
        className="ct-anim-spotlight pointer-events-none absolute inset-0"
        style={{
          background:
            "radial-gradient(circle at 50% 45%, rgba(245, 158, 11, 0.16) 0%, rgba(16, 185, 129, 0.11) 34%, rgba(6, 7, 11, 0) 70%)",
        }}
      />

      {/* Center Stage Logo & Typography Lockup */}
      <div className="relative z-10 flex w-full max-w-lg flex-col items-center text-center">
        {/* 0.0s - 0.6s: Animated Vector Icon */}
        <BrandLogo
          variant="icon"
          animated
          className="justify-center [&>svg]:h-20 [&>svg]:w-20 sm:[&>svg]:h-24 sm:[&>svg]:w-24"
        />

        {/* 0.55s - 1.35s: Masked Wordmark Reveal */}
        <div className="mt-5 overflow-hidden py-1 sm:mt-6">
          <h1 className="ct-anim-wordmark font-display text-3xl font-bold sm:text-5xl">
            <span className="text-[#F8FAFC]">CINE</span>
            <span className="bg-gradient-to-r from-[#F59E0B] via-[#FBBF24] to-[#F59E0B] bg-clip-text text-transparent">
              TRACKER
            </span>
          </h1>
        </div>

        {/* Tagline with Shimmer Sweep */}
        <div className="relative mt-2.5 overflow-hidden px-3 py-0.5">
          <p className="ct-anim-tagline font-mono text-[9.5px] font-semibold uppercase leading-relaxed tracking-[0.14em] text-zinc-300 sm:text-xs sm:tracking-[0.24em]">
            LIVE INDIAN &amp; MALAYALAM BOX OFFICE INTELLIGENCE
          </p>
          <div
            aria-hidden="true"
            className="ct-anim-shimmer pointer-events-none absolute inset-0 bg-gradient-to-r from-transparent via-amber-200/30 to-transparent"
          />
        </div>

        {/* Live Telemetry Pulse Pill */}
        <div className="ct-anim-pill mt-4 inline-flex items-center gap-2 rounded-full border border-[#10B981]/35 bg-[#10B981]/10 px-3.5 py-1 text-[10px] font-bold uppercase tracking-[0.18em] text-[#34D399] sm:text-[11px]">
          <span className="h-2 w-2 animate-pulse rounded-full bg-[#10B981]" />
          <span>REAL-TIME THEATRICAL ANALYTICS</span>
        </div>

        {/* 1.4s - 2.2s: Sleek Golden-Emerald Hairline Progress Bar */}
        <div className="mt-7 h-[2px] w-48 overflow-hidden rounded-full bg-white/[0.08] sm:w-64">
          <div className="ct-anim-progress h-full w-full rounded-full bg-gradient-to-r from-[#10B981] via-[#F59E0B] to-[#34D399]" />
        </div>
      </div>

      {/* Subtle Skip Hint */}
      <p className="pointer-events-none absolute bottom-6 text-[11px] font-medium tracking-wide text-zinc-500">
        Tap anywhere to skip
      </p>
    </div>
  );
}
