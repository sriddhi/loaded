"use client";

import { useEffect, useState } from "react";
import { MOBILE_BREAKPOINT } from "../../theme/tokens";

/** True when the viewport is at/below the mobile breakpoint. SSR-safe (false first render). */
export function useIsMobile(breakpoint: number = MOBILE_BREAKPOINT): boolean {
  const [mobile, setMobile] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia(`(max-width: ${breakpoint}px)`);
    const update = (): void => setMobile(mq.matches);
    update();
    mq.addEventListener("change", update);
    return () => mq.removeEventListener("change", update);
  }, [breakpoint]);
  return mobile;
}
