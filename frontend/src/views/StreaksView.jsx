import SleepView from "./SleepView.jsx";
import StreakView from "./StreakView.jsx";

// Sleep and activity streaks sit side by side (two columns on a wide screen,
// stacking only when there isn't room) so neither requires scrolling past the
// other.
function SectionHeading({ children }) {
  return (
    <div
      style={{
        fontFamily: "var(--mono)",
        fontSize: "0.78rem",
        letterSpacing: "0.08em",
        textTransform: "uppercase",
        color: "var(--muted)",
        margin: "0 0 0.8rem",
      }}
    >
      {children}
    </div>
  );
}

export default function StreaksView() {
  return (
    <div
      className="streaks"
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fit, minmax(440px, 1fr))",
        gap: "1.5rem",
        alignItems: "start",
      }}
    >
      <div>
        <SectionHeading>Sleep</SectionHeading>
        <SleepView />
      </div>
      <div>
        <SectionHeading>Activity</SectionHeading>
        <StreakView />
      </div>
    </div>
  );
}
