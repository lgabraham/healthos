import { useState } from "react";

// Persisted difficulty for the sleep streak's "low resting HR" rule, stored as
// an offset (bpm) from your median RHR. Tighter offset = harder to "rescue" a
// night on HR alone. Shared so the choice sticks across reloads.
const KEY = "healthos.rhrOffset";
export const RHR_OFFSETS = [0, -2, -4];
const DEFAULT = 0;

export function useRhrOffset() {
  const [offset, setOffset] = useState(() => {
    const v = Number(localStorage.getItem(KEY));
    return RHR_OFFSETS.includes(v) ? v : DEFAULT;
  });
  const update = (o) => {
    localStorage.setItem(KEY, String(o));
    setOffset(o);
  };
  return [offset, update];
}
