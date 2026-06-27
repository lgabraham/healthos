import { api } from "../api.js";
import { useHealthData } from "../hooks/useHealthData.js";
import { useRhrOffset, RHR_OFFSETS } from "../hooks/useRhrOffset.js";
import { Badge } from "@/components/ui/badge";

// A night "counts" toward the sleep streak if your resting HR came in at/under
// target (the primary win) — OR you stayed on routine, bedtime within an hour
// of your median, as the fallback. Either keeps the streak; missing both breaks
// it. Nights with no recorded sleep are skipped (don't extend or break), so sync
// gaps don't hurt. The night before a travel day (a calendar event tagged
// "travel") is likewise skipped — an early flight or pre-trip packing shouldn't
// count against the streak.
const BEDTIME_WINDOW = 60; // minutes around median bedtime that count as "on routine"
const MILESTONES = [7, 14, 30];

const MARK_COLOR = {
  recovered: "#2dd4bf", // low resting HR — the primary win (teal)
  routine: "#818cf8", // on-routine bedtime, RHR not low — fallback (indigo)
  miss: "#5b1a1a", // off-routine and elevated HR — streak broke
  travel: "#3f3f5e", // night before a travel day — skipped (muted indigo)
  nodata: "#141414", // no sleep recorded — skipped
  pending: "#1a1a1a", // tonight, not recorded yet
};

function todayISO() {
  return new Date().toLocaleDateString("en-CA");
}

function shiftDate(iso, days) {
  const d = new Date(`${iso}T00:00:00`);
  d.setDate(d.getDate() + days);
  return d.toLocaleDateString("en-CA");
}

// Whole-word travel match, derived from the event text rather than the stored
// keywords (which historically used substring matching and mis-tagged words
// like "department" → travel). "departure"/"departing" count; "department" does
// not. A travel day's *prior* night is the one skipped.
const TRAVEL_RE = /\b(flights?|airport|layover|depart(?:ure|ing)?|trips?)\b/i;

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

function buildNights(sleep, rhrSeries, rhrTarget, medBed, days = 90) {
  const rhrByDate = {};
  for (const d of rhrSeries || []) if (d.value != null) rhrByDate[d.date] = d.value;
  const sleepByDate = {};
  for (const s of sleep || []) sleepByDate[s.date] = s;
  // One entry per calendar day for the last `days` (ending today), so nights
  // with no recorded sleep render as real "no data" gaps and the weekday columns
  // stay aligned — the grid always lands on today.
  const out = [];
  const end = todayISO();
  for (let day = shiftDate(end, -(days - 1)); day <= end; day = shiftDate(day, 1)) {
    const s = sleepByDate[day];
    if (!s) {
      out.push({ date: day }); // no sleep recorded -> "no data" / "pending" (today)
      continue;
    }
    const bed = minutesFromNoon(s.start_time);
    const onRoutine = bed != null && medBed != null && Math.abs(bed - medBed) <= BEDTIME_WINDOW;
    const rhr = rhrByDate[day] ?? null;
    const recovered = rhr != null && rhrTarget != null && rhr <= rhrTarget;
    out.push({ date: day, bed, wake: minutesFromNoon(s.end_time), rhr, onRoutine, recovered });
  }
  return out;
}

function computeStreak(nights, haveSleepByDate, travelDays) {
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
    if (travelDays.has(n.date)) {
      // Night before a travel day: a free pass — neither extends nor breaks.
      n.mark = "travel";
      continue;
    }
    if (n.recovered) {
      streak += 1;
      n.mark = "recovered";
    } else if (n.onRoutine) {
      streak += 1;
      n.mark = "routine";
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
  // A "travel day" is any calendar date with a flight/airport/trip event (matched
  // whole-word from the event text — see TRAVEL_RE). HealthOS dates a night by the
  // morning it ends, so the night dated that day is the one right before you set
  // out — that's the night skipped.
  const travelDays = new Set(
    (calendar || [])
      .filter((c) => TRAVEL_RE.test(`${c.title || ""} ${c.location || ""}`))
      .map((c) => c.date)
  );
  const nights = buildNights(sleep, rhr?.series, rhrTarget, medBed);
  const { streak, longest } = computeStreak(nights, haveSleep, travelDays);
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
