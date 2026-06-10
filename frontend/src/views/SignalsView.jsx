import { useMemo, useState } from "react";
import {
  Brush,
  CartesianGrid,
  ComposedChart,
  Line,
  LineChart,
  ResponsiveContainer,
  Scatter,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api } from "../api.js";
import { useHealthData } from "../hooks/useHealthData.js";

// HRV and resting HR as two stacked, date-aligned panels (clearer than a
// dual-axis chart), with calendar events as dots ON the HRV line, colored by
// type. A navigator strip at the bottom pans/zooms both panels together.
// Event titles stay local-only.
const CAT_COLOR = {
  alcohol: "#f59e0b",
  travel: "#38bdf8",
  exercise: "#a855f7",
  health: "#ef4444",
  social: "#4ade80",
  work: "#8a8a8a",
  other: "#52525b",
};
// Noisy categories start hidden so the meaningful dots stand out.
const DEFAULT_ON = new Set(["alcohol", "travel", "exercise", "health", "social"]);
const AXIS = { stroke: "#3f3f46", fontSize: 11, fontFamily: "IBM Plex Mono" };
const RANGES = [30, 60, 90];

function category(keywords) {
  return (keywords && keywords[0]) || "other";
}

function EventDot(props) {
  const { cx, cy, payload } = props;
  if (cx == null || cy == null || !payload?.evt) return null;
  return (
    <circle
      cx={cx}
      cy={cy}
      r={5}
      fill={CAT_COLOR[payload.evt] || CAT_COLOR.other}
      stroke="#0a0a0a"
      strokeWidth={1.5}
    />
  );
}

function PanelTooltip({ active, payload, label, unit, color }) {
  if (!active || !payload?.length) return null;
  const row = payload[0].payload;
  const smooth = row[`${unit}Smooth`];
  const raw = row[unit];
  return (
    <div
      style={{
        background: "#181818",
        border: "1px solid #262626",
        padding: "0.4rem 0.6rem",
        fontFamily: "IBM Plex Mono",
        fontSize: 12,
      }}
    >
      <div style={{ color: "#8a8a8a" }}>{label}</div>
      <div style={{ color }}>
        {unit === "hrv" ? "HRV" : "RHR"}: {raw == null ? "—" : raw.toFixed(1)}
        {smooth != null ? ` · 7d avg ${smooth.toFixed(1)}` : ""}
      </div>
      {row.evt && (
        <div style={{ color: CAT_COLOR[row.evt] || CAT_COLOR.other, marginTop: "0.2rem" }}>
          ● {row.evt}
          {row.evtTitle ? ` · ${row.evtTitle}` : ""}
        </div>
      )}
    </div>
  );
}

function Panel({ data, unit, color, height, smooth, children }) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <ComposedChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: -8 }} syncId="signals">
        <CartesianGrid stroke="#1f1f1f" vertical={false} />
        <XAxis dataKey="date" tick={AXIS} minTickGap={28} tickLine={false} axisLine={AXIS} />
        <YAxis tick={AXIS} width={42} tickLine={false} axisLine={AXIS} domain={["auto", "auto"]} />
        <Tooltip content={<PanelTooltip unit={unit} color={color} />} />
        {/* raw trace: faint when smoothing, prominent when not */}
        <Line
          type="monotone"
          dataKey={unit}
          stroke={color}
          strokeWidth={smooth ? 1 : 2}
          strokeOpacity={smooth ? 0.3 : 1}
          dot={false}
          connectNulls
          isAnimationActive={false}
        />
        {smooth && (
          <Line
            type="monotone"
            dataKey={`${unit}Smooth`}
            stroke={color}
            strokeWidth={2}
            dot={false}
            connectNulls
            isAnimationActive={false}
          />
        )}
        {children}
      </ComposedChart>
    </ResponsiveContainer>
  );
}

export default function SignalsView() {
  const [days, setDays] = useState(60);
  const [smooth, setSmooth] = useState(true);
  const [cats, setCats] = useState(DEFAULT_ON);
  const [win, setWin] = useState(null); // {s, e} indices from the navigator

  const { data: hrv, loading, error } = useHealthData(() => api.trend("hrv_rmssd", days, 7), [days]);
  const { data: rhr } = useHealthData(() => api.trend("resting_hr", days, 7), [days]);
  const { data: cal } = useHealthData(() => api.calendar(days), [days]);

  const merged = useMemo(() => {
    const hrvS = Object.fromEntries((hrv?.series || []).map((d) => [d.date, d]));
    const rhrS = Object.fromEntries((rhr?.series || []).map((d) => [d.date, d]));
    const events = (cal || []).filter((e) => !e.all_day);
    const evtByDate = {};
    for (const e of events) {
      const c = category(e.keywords);
      // First event of an enabled category wins the day's marker.
      if (!(e.date in evtByDate) && cats.has(c)) evtByDate[e.date] = { evt: c, title: e.title };
    }
    const dates = Array.from(
      new Set([...Object.keys(hrvS), ...Object.keys(evtByDate)])
    ).sort();
    const hrvVals = dates.map((d) => hrvS[d]?.value).filter((v) => v != null);
    const floor = hrvVals.length ? Math.min(...hrvVals) : 0;
    return dates.map((date) => {
      const ev = evtByDate[date];
      const h = hrvS[date];
      const r = rhrS[date];
      return {
        date,
        hrv: h?.value ?? null,
        hrvSmooth: h?.rolling ?? null,
        rhr: r?.value ?? null,
        rhrSmooth: r?.rolling ?? null,
        evt: ev ? ev.evt : null,
        evtTitle: ev ? ev.title : null,
        evtY: ev ? (h?.value ?? floor) : null,
      };
    });
  }, [hrv, rhr, cal, cats]);

  if (loading) return <div className="muted mono">loading…</div>;
  if (error) return <div className="error">error: {error}</div>;

  const hasData = merged.some((d) => d.hrv != null || d.rhr != null);
  if (!hasData) {
    return (
      <div className="panel">
        <div className="muted mono">No HRV or resting-HR data in the last {days} days yet.</div>
      </div>
    );
  }

  const s = win ? Math.max(0, Math.min(win.s, merged.length - 1)) : 0;
  const e = win ? Math.max(s, Math.min(win.e, merged.length - 1)) : merged.length - 1;
  const visible = merged.slice(s, e + 1);

  const toggleCat = (c) => {
    const next = new Set(cats);
    if (next.has(c)) next.delete(c);
    else next.add(c);
    setCats(next);
  };

  return (
    <>
      <div className="statusline" style={{ marginBottom: "0.6rem" }}>
        each dot = a calendar event that day, sitting on the HRV line — the effect of an evening
        event shows in the NEXT morning's reading · drag the strip below to scroll time
      </div>

      <div style={{ display: "flex", gap: "0.6rem", alignItems: "center", marginBottom: "0.8rem", flexWrap: "wrap" }}>
        <div className="toggle">
          {RANGES.map((r) => (
            <button
              key={r}
              className={days === r ? "active" : ""}
              onClick={() => {
                setDays(r);
                setWin(null);
              }}
            >
              {r}d
            </button>
          ))}
        </div>
        <div className="toggle">
          <button className={smooth ? "active" : ""} onClick={() => setSmooth(true)}>
            7d avg
          </button>
          <button className={!smooth ? "active" : ""} onClick={() => setSmooth(false)}>
            raw
          </button>
        </div>
        <div className="legend" style={{ marginLeft: "auto" }}>
          {Object.entries(CAT_COLOR).map(([c, col]) => (
            <button
              key={c}
              onClick={() => toggleCat(c)}
              style={{
                background: "none",
                border: "none",
                padding: 0,
                cursor: "pointer",
                font: "inherit",
                color: "inherit",
                opacity: cats.has(c) ? 1 : 0.3,
              }}
              title={cats.has(c) ? `hide ${c} events` : `show ${c} events`}
            >
              <i style={{ background: col }} />
              {c}
            </button>
          ))}
        </div>
      </div>

      <div className="panel">
        <div className="label">HRV (ms)</div>
        <Panel data={visible} unit="hrv" color="#f59e0b" height={240} smooth={smooth}>
          <Scatter dataKey="evtY" shape={<EventDot />} isAnimationActive={false} legendType="none" />
        </Panel>

        <div className="label" style={{ marginTop: "0.6rem" }}>
          Resting HR (bpm)
        </div>
        <Panel data={visible} unit="rhr" color="#38bdf8" height={160} smooth={smooth} />

        {/* Navigator: full range, drag the handles / slide the window to pan both panels. */}
        <ResponsiveContainer width="100%" height={64}>
          <LineChart data={merged} margin={{ top: 8, right: 12, bottom: 0, left: -8 }}>
            <XAxis dataKey="date" hide />
            <YAxis hide domain={["auto", "auto"]} />
            <Line
              type="monotone"
              dataKey={smooth ? "hrvSmooth" : "hrv"}
              stroke="#f59e0b"
              strokeWidth={1}
              strokeOpacity={0.6}
              dot={false}
              connectNulls
              isAnimationActive={false}
            />
            <Brush
              dataKey="date"
              height={22}
              travellerWidth={8}
              stroke="#3f3f46"
              fill="#111111"
              tickFormatter={() => ""}
              startIndex={s}
              endIndex={e}
              onChange={({ startIndex, endIndex }) => setWin({ s: startIndex, e: endIndex })}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </>
  );
}
