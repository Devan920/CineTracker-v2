import { animate, useMotionValue } from "framer-motion";
import { useEffect, useState } from "react";

interface AnimatedNumberProps {
  value: number;
  decimals?: number;
  prefix?: string;
  suffix?: string;
  className?: string;
}

export function AnimatedNumber({
  value,
  decimals = 2,
  prefix = "",
  suffix = "",
  className = "",
}: AnimatedNumberProps) {
  const safeValue = Number.isFinite(value) ? value : 0;
  const motionVal = useMotionValue(0);
  const [display, setDisplay] = useState<string>(() =>
    new Intl.NumberFormat("en-IN", {
      minimumFractionDigits: decimals,
      maximumFractionDigits: decimals,
    }).format(safeValue)
  );

  useEffect(() => {
    const controls = animate(motionVal, safeValue, {
      duration: 0.9,
      ease: [0.22, 1, 0.36, 1],
      onUpdate: (latest) => {
        const finiteLatest = Number.isFinite(latest) ? latest : safeValue;
        setDisplay(
          new Intl.NumberFormat("en-IN", {
            minimumFractionDigits: decimals,
            maximumFractionDigits: decimals,
          }).format(finiteLatest)
        );
      },
    });
    return () => controls.stop();
  }, [safeValue, decimals, motionVal]);

  return (
    <span className={`tabular-nums ${className}`}>
      {prefix}
      {display}
      {suffix}
    </span>
  );
}
