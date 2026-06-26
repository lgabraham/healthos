import SleepView from "./SleepView.jsx";
import StreakView from "./StreakView.jsx";

// Sleep and activity streaks live on one "Streak" tab, stacked — no toggle.
function SectionHeading({ children, divider }) {
  return (
    <div
      style={{
        fontFamily: "var(--mono)",
        fontSize: "0.78rem",
        letterSpacing: "0.08em",
        textTransform: "uppercase",
        color: "var(--muted)",
        margin: divider ? "1.6rem 0 0.8rem" : "0 0 0.8rem",
        paddingTop: divider ? "1.1rem" : 0,
        borderTop: divider ? "1px solid var(--border)" : "none",
      }}
    >
      {children}
    </div>
  );
}

export default function StreaksView() {
  return (
    <>
      <SectionHeading>Sleep</SectionHeading>
      <SleepView />
      <SectionHeading divider>Activity</SectionHeading>
      <StreakView />
    </>
  );
}
