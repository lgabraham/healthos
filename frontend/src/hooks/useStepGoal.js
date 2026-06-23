import { useState } from "react";

// Shared, persisted daily step goal (drives Streak + Workouts). Stored in
// localStorage so the choice sticks and both tabs read the same value.
const KEY = "healthos.stepGoal";
export const STEP_GOALS = [8000, 10000, 12000];
const DEFAULT = 10000;

export function useStepGoal() {
  const [goal, setGoal] = useState(() => {
    const v = Number(localStorage.getItem(KEY));
    return STEP_GOALS.includes(v) ? v : DEFAULT;
  });
  const update = (g) => {
    localStorage.setItem(KEY, String(g));
    setGoal(g);
  };
  return [goal, update];
}
