import { api } from "../api.js";
import { useHealthData } from "../hooks/useHealthData.js";
import { useRhrOffset, RHR_OFFSETS } from "../hooks/useRhrOffset.js";
import { sleepStreak, BEDTIME_WINDOW } from "../lib/streaks.js";
import { Badge } from "@/components/ui/badge";

// A night "counts" toward the sleep streak if your resting HR came in at/under
// target (the primary win) — OR you stayed on routine, bedtime within an hour
// of your median, as the fallback. Either keeps the streak; missing both breaks
// it. Nights with no recorded sleep are skipped (don't extend or break), so sync
// gaps don't hurt. The night before a travel day (a calendar event tagged
// "travel") is likewise skipped — an early flight or pre-trip packing shouldn't
// count against the streak.
const MILESTONES = [7, 14, 30];

const MARK_COLOR = {
  recovered: "#2dd4bf", // low resting HR — the primary win (teal)
  routine: "#818cf8", // on-routine bedtime, RHR not low — fallback (indigo)
  miss: "#5b1a1a", // off-routine and elevated HR — streak broke
  travel: "#3f3f5e", // night before a travel day — skipped (muted indigo)
  nodata: "#141414", // no sleep recorded — skipped
  pending: "#1a1a1a", // tonight, not recorded yet
};

function fmtClock(mfn) {
  if (mfn == null) return "—";
  // Round to whole minutes (a median can land on a half-minute -> "9:53.5pm").
  const t = Math.round((((mfn + 720) % 1440) + 1440) % 1440) % 1440;
  let h = Math.floor(t / 60);
  const min = t % 60;
  const ap = h < 12 ? "am" : "pm";
  h = h % 12 || 12;
  return `${h}:${String(min).padStart(2, "0")}${ap}`;
}

function markLabel(n) {
  const bedStr = n.bed != null ? `bed ${fmtClock(n.bed)}` : "no bedtime";
  const rhrStr = n.rhr != null ? ` · RHR ${Math.round(n.rhr)}` : "";
  if (n.mark === "routine") return `on routine · ${bedStr}${rhrStr}`;
  if (n.mark === "recovered") return `low RHR${rhrStr} · ${bedStr}`;
  if (n.mark === "miss") return `off routine · ${bedStr}${rhrStr}`;
  if (n.mark === "travel") return `travel eve — skipped · ${bedStr}${rhrStr}`;
  if (n.mark === "pending") return "tonight — not recorded yet";
  return "no sleep recorded";
}

// Pad to weekday columns so the first night lands on its weekday, then chunk
// into weeks of 7 (same grid as the activity streak).
function toWeeks(nights) {
  if (!nights.length) return [];
  const cells = [];
  const firstDow = new Date(`${nights[0].date}T00:00:00`).getDay();
  for (let i = 0; i < firstDow; i++) cells.push(null);
  cells.push(...nights);
  const weeks = [];
  for (let i = 0; i < cells.length; i += 7) weeks.push(cells.slice(i, i + 7));
  return weeks;
}

function MilestoneStrip({ streak }) {
  const next = MILESTONES.find((m) => streak < m);
  return (
    <div className="legend" style={{ gap: "1.1rem" }}>
      {MILESTONES.map((m) => {
        const hit = streak >= m;
        const isNext = m === next;
        return (
          <span key={m} style={{ color: hit ? "var(--good)" : isNext ? "var(--accent)" : "var(--muted)" }}>
            {hit ? "🎉" : isNext ? "🎯" : "○"} {m}-night
            {isNext ? ` · ${m - streak} to go` : ""}
          </span>
        );
      })}
    </div>
  );
}

export default function SleepView() {
  const [rhrOffset, setRhrOffset] = useRhrOffset();
  const { data: sleep, loading, error } = useHealthData(() => api.sleep(90), []);
  const { data: rhr } = useHealthData(() => api.trend("resting_hr", 90, 1), []);
  const { data: calendar } = useHealthData(() => api.calendar(90), []);

  if (loading) return <div className="muted mono">loading…</div>;
  if (error) return <div className="error">error: {error}</div>;

  // All streak logic (median bedtime, RHR target, travel skips, per-night marks)
  // lives in the shared lib so the Sleep tab and the Pulse headliner agree.
  const { streak, longest, nights, haveSleep, medBed, medWake, bedSpread, wakeSpread, rhrMedian, rhrTarget } =
    sleepStreak({ sleep, rhrSeries: rhr?.series, calendar, rhrOffset });
  const weeks = toWeeks(nights);
  // Skipped nights (travel) are excluded from the weekly "kept" ratio so they
  // neither help nor hurt it.
  const last7 = nights.slice(-7).filter((n) => haveSleep.has(n.date) && n.mark !== "travel");
  const keptThisWeek = last7.filter((n) => n.mark === "routine" || n.mark === "recovered").length;
  const justHit = MILESTONES.includes(streak);
  const tier =
    streak >= 30 ? "🌙 dialed in" : streak >= 14 ? "😴 steady" : streak >= 7 ? "✨ settling in" : streak > 0 ? "keep it going" : "start tonight";

  return (
    // order: graph (1) → streak stats (2,3) → the rules + threshold toggle (4)
    <div style={{ display: "flex", flexDirection: "column" }}>
      <div
        className="statusline"
        style={{ order: 4, marginBottom: 0, marginTop: "0.85rem", display: "flex", alignItems: "center", gap: "0.7rem", flexWrap: "wrap" }}
      >
        <span>
          a night counts if{" "}
          {rhrTarget ? "resting HR is low or bedtime is within " : "bedtime is within "}
          {BEDTIME_WINDOW}m of your median ({fmtClock(medBed)}) · last 90 nights
        </span>
        {rhrMedian != null && (
          <span style={{ display: "flex", alignItems: "center", gap: "0.45rem" }}>
            <span className="muted" style={{ fontSize: "0.72rem" }}>low HR ≤</span>
            <div className="toggle">
              {RHR_OFFSETS.map((o) => (
                <button key={o} className={rhrOffset === o ? "active" : ""} onClick={() => setRhrOffset(o)}>
                  {rhrMedian + o}
                </button>
              ))}
            </div>
          </span>
        )}
      </div>

      <div className="grid cols-3" style={{ order: 2, marginBottom: "0.85rem" }}>
        <div className="panel hero">
          <div className="label">Sleep streak</div>
          <div className="metric-value xl" style={{ color: streak > 0 ? "var(--accent)" : "var(--muted)" }}>
            🌙 {streak}
          </div>
          <div className="metric-sub">
            {justHit ? `🎉 ${streak} nights kept!` : streak > 0 ? "nights kept going" : "low HR or on time tonight"}
          </div>
        </div>
        <div className="panel hero">
          <div className="label">Bedtime</div>
          <div className="metric-value xl">{fmtClock(medBed)}</div>
          <div className="metric-sub">
            {bedSpread != null ? `± ${Math.round(bedSpread)}m typical · last 30` : "median"}
          </div>
        </div>
        <div className="panel hero">
          <div className="label">Wake</div>
          <div className="metric-value xl">{fmtClock(medWake)}</div>
          <div className="metric-sub">
            {wakeSpread != null ? `± ${Math.round(wakeSpread)}m typical · last 30` : "median"}
          </div>
        </div>
      </div>

      <div className="panel" style={{ order: 3, marginBottom: "0.85rem", display: "flex", alignItems: "center", gap: "0.8rem", flexWrap: "wrap" }}>
        <Badge variant={streak >= 7 ? "default" : "secondary"}>{tier}</Badge>
        <MilestoneStrip streak={streak} />
        <span className="muted mono" style={{ fontSize: "0.72rem", marginLeft: "auto" }}>
          {keptThisWeek}/{last7.length || 7} nights kept this week
        </span>
      </div>

      <div className="panel" style={{ order: 1, marginBottom: "0.85rem", overflowX: "auto" }}>
        <div className="label">Last 90 nights</div>
        <div style={{ display: "flex", gap: "3px", marginTop: "0.4rem", width: "max-content" }}>
          <div style={{ display: "flex", flexDirection: "column", gap: "3px", marginRight: "4px" }}>
            {["S", "M", "T", "W", "T", "F", "S"].map((l, i) => (
              <span key={i} style={{ height: 14, fontSize: 9, lineHeight: "14px", color: "var(--muted)", fontFamily: "var(--mono)" }}>
                {i % 2 === 1 ? l : ""}
              </span>
            ))}
          </div>
          {weeks.map((week, wi) => (
            <div key={wi} style={{ display: "flex", flexDirection: "column", gap: "3px" }}>
              {Array.from({ length: 7 }).map((_, di) => {
                const n = week[di];
                if (!n) return <span key={di} style={{ width: 14, height: 14 }} />;
                return (
                  <span
                    key={di}
                    title={`${n.date} · ${markLabel(n)}`}
                    style={{
                      width: 14,
                      height: 14,
                      borderRadius: 2,
                      // "no data" reads as a hollow dashed cell so it's clearly
                      // distinct from the filled travel/miss marks.
                      background: n.mark === "nodata" ? "transparent" : MARK_COLOR[n.mark] || "#141414",
                      border:
                        n.mark === "nodata"
                          ? "1px dashed var(--border)"
                          : n.mark === "pending"
                            ? "1px solid var(--border)"
                            : "none",
                    }}
                  />
                );
              })}
            </div>
          ))}
        </div>
        <div className="legend" style={{ marginTop: "0.8rem" }}>
          <span><i style={{ background: MARK_COLOR.recovered }} />low RHR</span>
          <span><i style={{ background: MARK_COLOR.routine }} />on routine</span>
          <span><i style={{ background: MARK_COLOR.miss }} />off routine</span>
          <span><i style={{ background: MARK_COLOR.travel }} />travel eve (skipped)</span>
          <span><i style={{ background: "transparent", border: "1px dashed var(--border)" }} />no data</span>
        </div>
      </div>
    </div>
  );
}
