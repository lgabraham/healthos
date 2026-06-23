import { STEP_GOALS } from "../hooks/useStepGoal.js";

// Dumb toggle for the shared daily step goal. Reuses the same `.toggle` styling
// as the Trends range switch so the two feel of a piece.
export default function StepGoalToggle({ value, onChange }) {
  return (
    <div className="toggle">
      {STEP_GOALS.map((g) => (
        <button key={g} className={value === g ? "active" : ""} onClick={() => onChange(g)}>
          {g / 1000}k
        </button>
      ))}
    </div>
  );
}
