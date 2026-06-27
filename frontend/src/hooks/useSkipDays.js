import { useState } from "react";

// Persisted "allowed skip days" for the activity streak: how many weekday rest
// days in a row are forgiven before the streak breaks (weekends are always
// free). 1 reproduces the original "one weekday rest is fine" rule.
const KEY = "healthos.skipDays";
export const SKIP_DAYS = [0, 1, 2];
const DEFAULT = 1;

export function useSkipDays() {
  const [skips, setSkips] = useState(() => {
    const v = Number(localStorage.getItem(KEY));
    return SKIP_DAYS.includes(v) ? v : DEFAULT;
  });
  const update = (n) => {
    localStorage.setItem(KEY, String(n));
    setSkips(n);
  };
  return [skips, update];
}
