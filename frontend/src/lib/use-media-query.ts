import { useSyncExternalStore } from "react";

/** Assina uma media query; no servidor assume `fallback` (as telas que usam isso só montam após carregar dados no cliente). */
export function useMediaQuery(query: string, fallback = true): boolean {
  return useSyncExternalStore(
    (cb) => {
      const m = window.matchMedia(query);
      m.addEventListener("change", cb);
      return () => m.removeEventListener("change", cb);
    },
    () => window.matchMedia(query).matches,
    () => fallback,
  );
}
