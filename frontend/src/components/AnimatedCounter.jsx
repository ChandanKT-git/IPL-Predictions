import React, { useEffect, useRef, useState } from "react";

/** Tickers from 0 to `value` over `duration` ms. */
export const AnimatedCounter = ({
  value,
  duration = 1400,
  className = "",
  decimals = 0,
  suffix = "",
  prefix = "",
}) => {
  const [display, setDisplay] = useState(0);
  const startedRef = useRef();
  const fromRef = useRef(0);

  useEffect(() => {
    const from = fromRef.current;
    const to = Number(value) || 0;
    const startedAt = performance.now();
    startedRef.current = startedAt;
    let raf;
    const tick = (now) => {
      if (startedRef.current !== startedAt) return; // newer animation took over
      const t = Math.min(1, (now - startedAt) / duration);
      const eased = 1 - Math.pow(1 - t, 3);
      setDisplay(from + (to - from) * eased);
      if (t < 1) raf = requestAnimationFrame(tick);
      else fromRef.current = to;
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [value, duration]);

  return (
    <span className={`tabular ${className}`}>
      {prefix}
      {display.toFixed(decimals)}
      {suffix}
    </span>
  );
};

export default AnimatedCounter;
