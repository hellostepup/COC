import React, { useEffect, useRef, useState } from "react";
import { api } from "../api.js";

const REGION_LABELS = { gold: "Gold counter", elixir: "Elixir counter", dark: "Dark Elixir counter", builders: "Builder counter", player_name: "Player name" };

export default function Settings({ refresh, onNotify }) {
  const [s, setS] = useState(null);
  const [logs, setLogs] = useState(null);
  const [msg, setMsg] = useState(null);
  const fileRef = useRef();

  useEffect(() => { api.get("/api/settings").then(setS); }, []);
  if (!s) return <div className="p-8 text-muted">Loading…</div>;

  const save = async (patch) => {
    const next = await api.put("/api/settings", patch);
    setS(next);
    if ("notifications_enabled" in patch) onNotify(patch.notifications_enabled);
    setMsg("Saved");
  };
  const setRegion = (k, i, v) => {
    const r = { ...s.ocr_regions, [k]: s.ocr_regions[k].map((x, j) => (j === i ? v : x)) };
    setS({ ...s, ocr_regions: r });
  };

  return (
    <div className="p-6 max-w-3xl space-y-4">
      <h1 className="text-2xl font-semibold">Settings</h1>
      {msg && <div className="text-sm text-emerald-300">{msg}</div>}

      <div className="card space-y-2">
        <div className="h2">Notifications</div>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={s.notifications_enabled} onChange={(e) => save({ notifications_enabled: e.target.checked })} />
          Show Windows desktop notifications
        </label>
      </div>

      <div className="card space-y-2">
        <div className="h2">OCR regions</div>
        <div className="text-xs text-muted">Where each counter sits on the home-village screenshot, as fractions of width/height (left, top, right, bottom). Adjust if readings come back empty.</div>
        {Object.entries(s.ocr_regions).map(([k, r]) => (
          <div key={k} className="flex items-center gap-2 text-sm">
            <span className="w-40">{REGION_LABELS[k] || k}</span>
            {r.map((x, i) => (
              <input key={i} className="input w-20" type="number" step="0.005" min="0" max="1" value={x} onChange={(e) => setRegion(k, i, parseFloat(e.target.value))} />
            ))}
          </div>
        ))}
        <button className="btn" onClick={() => save({ ocr_regions: s.ocr_regions })}>Save regions</button>
      </div>

      <div className="card space-y-2">
        <div className="h2">Backup & restore</div>
        <div className="text-xs text-muted">Data is stored locally in {s.data_dir}</div>
        <div className="flex gap-2">
          <a className="btn" href={api.url("/api/backup")} download>Download backup</a>
          <input ref={fileRef} type="file" accept=".db" className="hidden" onChange={async (e) => {
            const f = e.target.files[0]; if (!f) return;
            if (!confirm("Replace all current data with this backup? Your current data is saved first.")) return;
            const fd = new FormData(); fd.append("file", f);
            try { const r = await api.form("/api/restore", fd); setMsg(`Restored. Previous data saved to ${r.previous_data_saved_to}`); refresh(); }
            catch (err) { setMsg(`Restore failed: ${err.message}`); }
          }} />
          <button className="btn" onClick={() => fileRef.current.click()}>Restore from backup…</button>
        </div>
      </div>

      <div className="card space-y-2">
        <div className="h2">AI training data</div>
        <div className="text-xs text-muted">Every battle screenshot you correct is a labelled sample. Export them as a YOLO dataset and train a model (see README).</div>
        <button className="btn" onClick={async () => { const r = await api.post("/api/vision/export-dataset"); setMsg(`Exported ${r.images} images to ${r.path}`); }}>Export YOLO dataset</button>
      </div>

      <div className="card space-y-2">
        <div className="flex items-center"><div className="h2">Error logs</div>
          <button className="btn ml-auto" onClick={() => api.get("/api/logs").then((r) => setLogs(r.lines))}>Load</button></div>
        {logs && <pre className="text-[11px] max-h-80 overflow-auto bg-[#0e121a] rounded-lg p-2">{logs.join("") || "Empty"}</pre>}
      </div>
    </div>
  );
}
