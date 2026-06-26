import { useState } from "react";
import SleepView from "./SleepView.jsx";
import StreakView from "./StreakView.jsx";

// Sleep and activity are both "streaks", so they share one tab with a small
// sub-toggle (frees a top-level nav slot for the Journal).
export default function StreaksView() {
  const [tab, setTab] = useState("sleep");
  return (
    <>
      <div className="toggle" style={{ marginBottom: "0.9rem" }}>
        <button className={tab === "sleep" ? "active" : ""} onClick={() => setTab("sleep")}>
          Sleep
        </button>
        <button className={tab === "activity" ? "active" : ""} onClick={() => setTab("activity")}>
          Activity
        </button>
      </div>
      {tab === "sleep" ? <SleepView /> : <StreakView />}
    </>
  );
}
