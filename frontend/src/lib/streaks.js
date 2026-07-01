// Shared streak computations used by the Streak tab, the Sleep tab, and the
// Pulse headliners — so the number shown on Pulse always matches the detail
// tabs (single source of truth). View-specific rendering (colors, labels, grid
// layout, milestones) stays in the views; only the pure logic lives here.

export const BEDTIME_WINDOW = 60; // minutes around median bedtime that count as "on routine"

function todayISO() {
  return new Date().toLocaleDateString("en-CA");
}

function shiftDate(iso, days) {
  const d = new Date(`${iso}T00:00:00`);
  d.setDate(d.getDate() + days);
  return d.toLocaleDateString("en-CA");
}

// ---------------------------------------------------------------------------
// Activity streak: a day counts if you worked out OR hit the step goal. Up to
// `allowedSkips` weekday rest days in a row are forgiven; weekends are free.
// ---------------------------------------------------------------------------
export function buildActivityDays(stepsSeries, workouts, goal) {
  const workoutDays = new Set((workouts || []).map((w) => w.date));
  return (stepsSeries || []).map((d) => {
    const worked = workoutDays.has(d.date);
    const hitGoal = d.value != null && d.value >= goal;
    return { date: d.date, steps: d.value, worked, hitGoal, active: worked || hitGoal };
  });
}

export function computeActivityStreak(days, allowedSkips) {
  const today = todayISO();
  let streak = 0;
  let longest = 0;
  let restRun = 0; // consecutive weekday rest days (weekends don't count)
  for (const d of days) {
    const dow = new Date(`${d.date}T00:00:00`).getDay();
    const weekend = dow === 0 || dow === 6;
    if (d.date === today && !d.active) {
      d.mark = "pending";
      continue;
    }
    if (d.active) {
      streak += 1;
      restRun = 0;
      d.mark = d.worked ? "workout" : "steps";
    } else if (weekend) {
      streak += 1;
      d.mark = "weekend";
    } else if (++restRun > allowedSkips) {
      streak = 0;
      d.mark = "broken";
    } else {
      streak += 1;
      d.mark = "rest";
    }
    longest = Math.max(longest, streak);
  }
  return { streak, longest };
}

// High-level wrapper for callers that just want the streak from raw API data.
export function activityStreak(stepsSeries, workouts, goal, allowedSkips) {
  const days = buildActivityDays(stepsSeries, workouts, goal);
  return { ...computeActivityStreak(days, allowedSkips), days };
}

// ---------------------------------------------------------------------------
// Sleep streak: a night counts if resting HR came in at/under target (primary
// win) OR bedtime stayed within an hour of your median (fallback). Nights with
// no sleep are skipped; the night before a travel day is skipped.
// ---------------------------------------------------------------------------

// Whole-word travel match (substring matching historically mis-tagged
// "department" -> travel). "departure"/"departing" count; "department" doesn't.
export const TRAVEL_RE = /\b(flights?|airport|layover|depart(?:ure|ing)?|trips?)\b/i;

// Wall-clock minutes relative to noon: evening bedtimes land ~540–840, morning
// wakes ~1080–1140, so a normal night is monotonic and never wraps midnight.
export function minutesFromNoon(iso) {
  const m = (iso || "").match(/T(\d{2}):(\d{2})/);
  if (!m) return null;
  return ((+m[1] * 60 + +m[2]) - 720 + 1440) % 1440;
}

export function median(arr) {
  if (!arr.length) return null;
  const s = [...arr].sort((a, b) => a - b);
  const m = Math.floor(s.length / 2);
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
}

// Mean absolute deviation around the median — a robust "± how much it wanders".
export function spread(arr, med) {
  if (!arr.length || med == null) return null;
  return arr.reduce((a, v) => a + Math.abs(v - med), 0) / arr.length;
}

export function buildNights(sleep, rhrSeries, rhrTarget, medBed, days = 90) {
  const rhrByDate = {};
  for (const d of rhrSeries || []) if (d.value != null) rhrByDate[d.date] = d.value;
  const sleepByDate = {};
  for (const s of sleep || []) sleepByDate[s.date] = s;
  const out = [];
  const end = todayISO();
  for (let day = shiftDate(end, -(days - 1)); day <= end; day = shiftDate(day, 1)) {
    const s = sleepByDate[day];
    if (!s) {
      out.push({ date: day });
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

export function computeSleepStreak(nights, haveSleepByDate, travelDays) {
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

// High-level wrapper: derives the median bedtime / RHR target / travel days from
// raw API data, then returns the streak plus everything the Sleep tab renders.
export function sleepStreak({ sleep, rhrSeries, calendar, rhrOffset = 0 }) {
  const recent = (sleep || []).slice(-30);
  const bedtimes = recent.map((s) => minutesFromNoon(s.start_time)).filter((v) => v != null);
  const waketimes = recent.map((s) => minutesFromNoon(s.end_time)).filter((v) => v != null);
  const medBed = median(bedtimes);
  const medWake = median(waketimes);
  const bedSpread = spread(bedtimes, medBed);
  const wakeSpread = spread(waketimes, medWake);

  const rhrVals = (rhrSeries || []).map((d) => d.value).filter((v) => v != null);
  const rhrMedian = rhrVals.length ? Math.round(median(rhrVals)) : null;
  const rhrTarget = rhrMedian == null ? null : rhrMedian + rhrOffset;

  const haveSleep = new Set((sleep || []).map((s) => s.date));
  const travelDays = new Set(
    (calendar || [])
      .filter((c) => TRAVEL_RE.test(`${c.title || ""} ${c.location || ""}`))
      .map((c) => c.date),
  );
  const nights = buildNights(sleep, rhrSeries, rhrTarget, medBed);
  const { streak, longest } = computeSleepStreak(nights, haveSleep, travelDays);
  return {
    streak,
    longest,
    nights,
    haveSleep,
    travelDays,
    medBed,
    medWake,
    bedSpread,
    wakeSpread,
    rhrMedian,
    rhrTarget,
  };
}
