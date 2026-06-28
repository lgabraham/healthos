import { useEffect, useState } from "react";
import { api } from "../api.js";

// Jot food / meds / supplements as plain text; the API parses it into coarse
// exposure tags (nsaid, alcohol, dairy, …) to later correlate against your
// inflammation biomarkers (HRV, resting HR, respiratory rate, skin temp).

function TagChip({ tag }) {
  return (
    <span
      className="mono"
      style={{
        fontSize: "0.68rem",
        background: "#16302e",
        color: "#2dd4bf",
        borderRadius: 4,
        padding: "1px 6px",
      }}
    >
      {tag}
    </span>
  );
}

function todayISO() {
  return new Date().toLocaleDateString("en-CA");
}
function yesterdayISO() {
  const d = new Date();
  d.setDate(d.getDate() - 1);
  return d.toLocaleDateString("en-CA");
}

export default function JournalView() {
  const [entries, setEntries] = useState(null);
  const [text, setText] = useState("");
  const [logDate, setLogDate] = useState(yesterdayISO()); // default to the day prior
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [addingFor, setAddingFor] = useState(null); // entry id whose add-tag input is open
  const [newTag, setNewTag] = useState("");

  const load = () =>
    api
      .journal(60)
      .then(setEntries)
      .catch((e) => setError(String(e)));
  useEffect(() => {
    load();
  }, []);

  const submit = async (e) => {
    e.preventDefault();
    const t = text.trim();
    if (!t || busy) return;
    setBusy(true);
    setError(null);
    try {
      const created = await api.addJournal(t, logDate);
      setEntries((prev) => [created, ...(prev || [])]);
      setText("");
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  };

  const remove = async (id) => {
    setEntries((prev) => (prev || []).filter((x) => x.id !== id));
    await api.deleteJournal(id).catch(() => load());
  };

  const persistTags = async (entry, tags) => {
    setEntries((prev) => (prev || []).map((x) => (x.id === entry.id ? { ...x, tags } : x)));
    await api.updateJournalTags(entry.id, tags).catch(() => load());
  };
  const removeTag = (entry, tag) =>
    persistTags(entry, (entry.tags || []).filter((t) => t !== tag));
  const addTag = (entry, raw) => {
    const norm = (raw || "").trim().toLowerCase().replace(/\s+/g, "_");
    setAddingFor(null);
    setNewTag("");
    if (!norm || (entry.tags || []).includes(norm)) return;
    persistTags(entry, [...(entry.tags || []), norm]);
  };

  return (
    <>
      <div className="statusline" style={{ marginBottom: "0.8rem" }}>
        log food, meds &amp; supplements as plain text — auto-tagged to correlate against your biomarkers
      </div>

      <form className="panel" onSubmit={submit} style={{ marginBottom: "0.85rem" }}>
        <div className="label">New entry</div>
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) submit(e);
          }}
          placeholder="e.g. 2 Advil, glass of red wine, 400mg magnesium, late espresso"
          rows={3}
          style={{
            width: "100%",
            marginTop: "0.4rem",
            background: "var(--bg)",
            color: "var(--text)",
            border: "1px solid var(--border)",
            borderRadius: 6,
            padding: "0.6rem",
            fontFamily: "var(--mono)",
            fontSize: "0.85rem",
            resize: "vertical",
            boxSizing: "border-box",
          }}
        />
        <div style={{ display: "flex", alignItems: "center", gap: "0.7rem", marginTop: "0.5rem", flexWrap: "wrap" }}>
          <label style={{ display: "flex", alignItems: "center", gap: "0.4rem" }}>
            <span className="muted mono" style={{ fontSize: "0.7rem" }}>for</span>
            <input
              type="date"
              value={logDate}
              max={todayISO()}
              onChange={(e) => setLogDate(e.target.value)}
              style={{
                background: "var(--bg)",
                color: "var(--text)",
                border: "1px solid var(--border)",
                borderRadius: 6,
                padding: "0.3rem 0.45rem",
                fontFamily: "var(--mono)",
                fontSize: "0.78rem",
              }}
            />
          </label>
          <button className="refresh" type="submit" disabled={busy || !text.trim()}>
            {busy ? "saving…" : "log it"}
          </button>
          <span className="muted mono" style={{ fontSize: "0.7rem" }}>
            ⌘↵ to save
          </span>
        </div>
        {error && (
          <div className="error" style={{ marginTop: "0.5rem" }}>
            error: {error}
          </div>
        )}
      </form>

      <div className="panel">
        <div className="label">Recent entries</div>
        {entries == null ? (
          <div className="muted mono" style={{ marginTop: "0.5rem" }}>
            loading…
          </div>
        ) : entries.length === 0 ? (
          <div className="muted mono" style={{ marginTop: "0.5rem" }}>
            nothing logged yet — add your first entry above.
          </div>
        ) : (
          <div style={{ marginTop: "0.5rem", display: "flex", flexDirection: "column", gap: "0.6rem" }}>
            {entries.map((e) => (
              <div key={e.id} style={{ borderTop: "1px solid var(--border)", paddingTop: "0.55rem" }}>
                <div style={{ display: "flex", justifyContent: "space-between", gap: "0.7rem" }}>
                  <span className="mono" style={{ fontSize: "0.85rem", color: "var(--text)" }}>
                    {e.text}
                  </span>
                  <button
                    onClick={() => remove(e.id)}
                    title="delete entry"
                    style={{
                      background: "none",
                      border: "none",
                      cursor: "pointer",
                      color: "var(--muted)",
                      fontSize: "1rem",
                      lineHeight: 1,
                    }}
                  >
                    ×
                  </button>
                </div>
                <div
                  style={{
                    display: "flex",
                    flexWrap: "wrap",
                    gap: "0.35rem",
                    marginTop: "0.35rem",
                    alignItems: "center",
                  }}
                >
                  <span className="muted mono" style={{ fontSize: "0.68rem" }}>
                    {e.date}
                  </span>
                  {(e.tags || []).map((t) => (
                    <span
                      key={t}
                      className="mono"
                      style={{
                        display: "inline-flex",
                        alignItems: "center",
                        gap: "0.2rem",
                        fontSize: "0.62rem",
                        background: "#16302e",
                        color: "#2dd4bf",
                        borderRadius: 4,
                        padding: "1px 4px 1px 6px",
                      }}
                    >
                      {t}
                      <button
                        onClick={() => removeTag(e, t)}
                        title="remove tag"
                        style={{ background: "none", border: "none", cursor: "pointer", color: "#2dd4bf", fontSize: "0.8rem", lineHeight: 1, padding: 0 }}
                      >
                        ×
                      </button>
                    </span>
                  ))}
                  {addingFor === e.id ? (
                    <input
                      autoFocus
                      value={newTag}
                      onChange={(ev) => setNewTag(ev.target.value)}
                      onKeyDown={(ev) => {
                        if (ev.key === "Enter") addTag(e, newTag);
                        else if (ev.key === "Escape") {
                          setAddingFor(null);
                          setNewTag("");
                        }
                      }}
                      onBlur={() => addTag(e, newTag)}
                      placeholder="tag…"
                      style={{ width: "5.5rem", background: "var(--bg)", color: "var(--text)", border: "1px solid var(--border)", borderRadius: 4, padding: "1px 5px", fontFamily: "var(--mono)", fontSize: "0.62rem" }}
                    />
                  ) : (
                    <button
                      onClick={() => {
                        setAddingFor(e.id);
                        setNewTag("");
                      }}
                      title="add tag"
                      style={{ background: "none", border: "1px dashed var(--border)", cursor: "pointer", color: "var(--muted)", fontSize: "0.62rem", borderRadius: 4, padding: "1px 6px", fontFamily: "var(--mono)" }}
                    >
                      + tag
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </>
  );
}
