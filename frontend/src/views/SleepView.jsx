import { api } from "../api.js";
import { useHealthData } from "../hooks/useHealthData.js";
import { useRhrOffset, RHR_OFFSETS } from "../hooks/useRhrOffset.js";
import { Badge } from "@/components/ui/badge";

// A night "counts" toward the sleep streak if you stayed on routine — bedtime
// within an hour of your median bedtime — OR your resting HR came in at/under
// target. Either keeps the streak; a miss on both breaks it. Nights with no
// recorded sleep are skipped (don't extend or break), so sync gaps don't hurt.
const BEDTIME_WINDOW = 60; // minutes around median bedtime that count as "on routine"
const MILESTONES = [7, 14, 30];

const MARK_COLOR = {
  routine: "#818cf8", // on-routine bedtime (indigo)
  recovered: "#2dd4bf", // off-routine but low resting HR (teal)
  miss: "#5b1a1a", // off-routine and elevated HR — streak broke
  nodata: "#141414", // no sleep recorded — skipped
  pending: "#1a1a1a", // tonight, not recorded yet
};

function todayISO() {
  return new Date().toLocaleDateString("en-CA");
}

// Wall-clock minutes relative to noon: evening bedtimes land ~540–840, morning
// wakes ~1080–1140, so a normal night is monotonic and never wraps midnight.
// Parses the HH:MM straight out of the local ISO string (no tz math needed).
function minutesFromNoon(iso) {
  const m = (iso || "").match(/T(\d{2}):(\d{2})/);
  if (!m) return null;
  return ((+m[1] * 60 + +m[2]) - 720 + 1440) % 1440;
}

function fmtClock(mfn) {
  if (mfn == null) return "—";
  const t = (((mfn + 720) % 1440) + 1440) % 1440;
  let h = Math.floor(t / 60);
  const min = t % 60;
  const ap = h < 12 ? "am" : "pm";
  h = h % 12 || 12;
  return `${h}:${String(min).padStart(2, "0")}${ap}`;
}

function median(arr) {
  if (!arr.length) return null;
  const s = [...arr].sort((a, b) => a - b);
  const m = Math.floor(s.length / 2);
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
}

// Mean absolute deviation around the median — a robust "± how much it wanders".
function spread(arr, med) {
  if (!arr.length || med == null) return null;
  return arr.reduce((a, v) => a + Math.abs(v - med), 0) / arr.length;
}

function buildNights(sleep, rhrSeries, rhrTarget, medBed) {
  const rhrByDate = {};
  for (const d of rhrSeries || []) if (d.value != null) rhrByDate[d.date] = d.value;
  return (sleep || []).map((s) => {
    const bed = minutesFromNoon(s.start_time);
    const onRoutine = bed != null && medBed != null && Math.abs(bed - medBed) <= BEDTIME_WINDOW;
    const rhr = rhrByDate[s.date] ?? null;
    const recovered = rhr != null && rhrTarget != null && rhr <= rhrTarget;
    return { date: s.date, bed, wake: minutesFromNoon(s.end_time), rhr, onRoutine, recovered };
  });
}

function computeStreak(nights, haveSleepByDate) {
  // Walk every calendar day in range so a night with no sleep is a true gap.
  const today = todayISO();
  let streak = 0;
  let longest = 0;
  for (const n of nights) {
    if (n.date === today && !haveSleepByDate.has(n.date)) {
      n.mark = "pending";
      continue;
    }
    if (!haveSleepByDate.has(n.date)) {
      n.mark = "nodata";
      continue;
    }
    if (n.onRoutine) {
      streak += 1;
      n.mark = "routine";
    } else if (n.recovered) {
      streak += 1;
      n.mark = "recovered";
    } else {
      streak = 0;
      n.mark = "miss";
    }
    longest = Math.max(longest, streak);
  }
  return { streak, longest };
}

function markLabel(n) {
  const bedStr = n.bed != null ? `bed ${fmtClock(n.bed)}` : "no bedtime";
  const rhrStr = n.rhr != null ? ` · RHR ${Math.round(n.rhr)}` : "";
  if (n.mark === "routine") return `on routine · ${bedStr}${rhrStr}`;
  if (n.mark === "recovered") return `low RHR${rhrStr} · ${bedStr}`;
  if (n.mark === "miss") return `off routine · ${bedStr}${rhrStr}`;
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

  if (loading) return <div className="muted mono">loading…</div>;
  if (error) return <div className="error">error: {error}</div>;

  // Regularity over the recent window (last 30 nights), which is what you can
  // actually act on; older data is sparse.
  const recent = (sleep || []).slice(-30);
  const bedtimes = recent.map((s) => minutesFromNoon(s.start_time)).filter((v) => v != null);
  const waketimes = recent.map((s) => minutesFromNoon(s.end_time)).filter((v) => v != null);
  const medBed = median(bedtimes);
  const medWake = median(waketimes);
  const bedSpread = spread(bedtimes, medBed);
  const wakeSpread = spread(waketimes, medWake);

  // Personalized RHR target: your median resting HR, shifted by the chosen
  // difficulty offset. Nights at or below it "count" even if bedtime drifted.
  const rhrVals = (rhr?.series || []).map((d) => d.value).filter((v) => v != null);
  const rhrMedian = rhrVals.length ? Math.round(median(rhrVals)) : null;
  const rhrTarget = rhrMedian == null ? null : rhrMedian + rhrOffset;

  const haveSleep = new Set((sleep || []).map((s) => s.date));
  const nights = buildNights(sleep, rhr?.series, rhrTarget, medBed);
  const { streak, longest } = computeStreak(nights, haveSleep);
  const weeks = toWeeks(nights);
  const last7 = nights.slice(-7).filter((n) => haveSleep.has(n.date));
  const onRoutineWeek = last7.filter((n) => n.mark === "routine" || n.mark === "recovered").length;
  const justHit = MILESTONES.includes(streak);
  const tier =
    streak >= 30 ? "🌙 dialed in" : streak >= 14 ? "😴 steady" : streak >= 7 ? "✨ settling in" : streak > 0 ? "keep it going" : "start tonight";

  return (
    <>
      <div
        className="statusline"
        style={{ marginBottom: "0.8rem", display: "flex", alignItems: "center", gap: "0.7rem", flexWrap: "wrap" }}
      >
        <span>
          a night counts if bedtime is within {BEDTIME_WINDOW}m of your median ({fmtClock(medBed)})
          {rhrTarget ? " or resting HR is low ·" : " ·"} last 90 nights
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

      <div className="grid cols-3" style={{ marginBottom: "0.85rem" }}>
        <div className="panel hero">
          <div className="label">Sleep streak</div>
          <div className="metric-value xl" style={{ color: streak > 0 ? "var(--accent)" : "var(--muted)" }}>
            🌙 {streak}
          </div>
          <div className="metric-sub">
            {justHit ? `🎉 ${streak} nights on routine!` : streak > 0 ? "nights kept going" : "get to bed on time"}
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

      <div className="panel" style={{ marginBottom: "0.85rem", display: "flex", alignItems: "center", gap: "0.8rem", flexWrap: "wrap" }}>
        <Badge variant={streak >= 7 ? "default" : "secondary"}>{tier}</Badge>
        <MilestoneStrip streak={streak} />
        <span className="muted mono" style={{ fontSize: "0.72rem", marginLeft: "auto" }}>
          {onRoutineWeek}/{last7.length || 7} on routine this week
        </span>
      </div>

      <div className="panel" style={{ overflowX: "auto" }}>
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
                      background: MARK_COLOR[n.mark] || "#141414",
                      border: n.mark === "nodata" || n.mark === "pending" ? "1px solid #2a2a2e" : "none",
                    }}
                  />
                );
              })}
            </div>
          ))}
        </div>
        <div className="legend" style={{ marginTop: "0.8rem" }}>
          <span><i style={{ background: MARK_COLOR.routine }} />on routine</span>
          <span><i style={{ background: MARK_COLOR.recovered }} />low RHR</span>
          <span><i style={{ background: MARK_COLOR.miss }} />off routine</span>
          <span><i style={{ background: MARK_COLOR.nodata, border: "1px solid #2a2a2e" }} />no data</span>
        </div>
      </div>
    </>
  );
}
