import React, { useEffect, useRef, useState } from "react";
import { api, fmt } from "../api.js";
import { Field, NumInput } from "../components/ui.jsx";

const COLORS = {
  gold_mine: "#f2c14e", gold_storage: "#f2c14e", elixir_collector: "#d65ce6", elixir_storage: "#d65ce6",
  dark_elixir_drill: "#9b8ac4", dark_elixir_storage: "#9b8ac4", town_hall: "#38bdf8", clan_castle: "#38bdf8",
};
const isResource = (l) => /mine|storage|collector|drill/.test(l);
const pretty = (l) => l.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

export default function Vision({ dash, refresh }) {
  const [status, setStatus] = useState(null);
  const [mode, setMode] = useState("battle");
  const [accountId, setAccountId] = useState(dash.current_account_id || dash.accounts[0]?.account.id || null);
  const [det, setDet] = useState(null);
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);
  const fileRef = useRef();

  useEffect(() => { api.get("/api/vision/status").then(setStatus).catch((e) => setErr(e.message)); }, []);

  const submit = async (file) => {
    setBusy(true); setErr(null);
    try {
      if (mode === "verify") {
        const fd = new FormData(); fd.append("file", file);
        if (accountId) fd.append("expected_account_id", accountId);
        setDet({ verify: await api.form("/api/vision/verify-account", fd) });
      } else {
        const fd = new FormData(); fd.append("file", file); fd.append("kind", mode);
        if (accountId) fd.append("account_id", accountId);
        setDet(await api.form("/api/vision/upload", fd));
      }
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  };
  const captureNow = async () => {
    setBusy(true); setErr(null);
    try { setDet(await api.post("/api/vision/capture", { kind: mode, account_id: accountId })); }
    catch (e) { setErr(e.message); } finally { setBusy(false); }
  };

  return (
    <div className="p-6 space-y-4">
      <div className="flex flex-wrap items-end gap-3">
        <div>
          <h1 className="text-2xl font-semibold">AI Vision</h1>
          <div className="text-xs text-muted">Read-only: analyzes screenshots and suggests. You search, deploy and end battles yourself.</div>
        </div>
        <div className="ml-auto flex gap-2 items-end">
          <Field label="Mode">
            <select className="input" value={mode} onChange={(e) => { setMode(e.target.value); setDet(null); }}>
              <option value="battle">Battle layout → attack suggestion</option>
              <option value="home">Home village → read resources & builders</option>
              <option value="verify">Verify which account is open</option>
            </select>
          </Field>
          <Field label="Account">
            <select className="input" value={accountId || ""} onChange={(e) => setAccountId(+e.target.value)}>
              {dash.accounts.map((v) => <option key={v.account.id} value={v.account.id}>{v.account.name}</option>)}
            </select>
          </Field>
          <input ref={fileRef} type="file" accept="image/*" className="hidden" onChange={(e) => e.target.files[0] && submit(e.target.files[0])} />
          <button className="btn" disabled={busy} onClick={() => fileRef.current.click()}>Upload screenshot</button>
          <button className="btn btn-primary" disabled={busy || !status?.capture_supported}
            title={status?.capture_supported ? "" : "Window capture works on Windows"} onClick={captureNow}>Capture BlueStacks</button>
        </div>
      </div>
      {status && (
        <div className="text-xs text-muted flex gap-4 flex-wrap">
          <span>Detector: <b className="text-ink">{status.backend}</b>{status.backend === "manual" && " (no model or templates yet; mark buildings by hand)"}</span>
          <span>OCR: <b className={status.ocr_available ? "text-emerald-300" : "text-amber-300"}>{status.ocr_available ? "ready" : "Tesseract not installed"}</b></span>
          <span>Templates: {Object.keys(status.templates).length ? Object.entries(status.templates).map(([k, n]) => `${k}×${n}`).join(", ") : "none"}</span>
        </div>
      )}
      {err && <div className="card border-red-500/50 text-red-300 text-sm">{err}</div>}
      {busy && <div className="text-muted text-sm">Analyzing…</div>}
      {det?.verify && <VerifyResult r={det.verify} dash={dash} refresh={refresh} />}
      {det && det.kind === "battle" && <BattleEditor key={det.id} det={det} labels={status?.labels || []} accountId={accountId} />}
      {det && det.kind === "home" && <CounterConfirm key={det.id} det={det} accountId={accountId} refresh={refresh} />}
      {!det && !busy && (
        <div className="card text-sm text-muted">
          {mode === "battle" && "Take a screenshot of the scouting screen before you attack, then upload or capture it. Check the boxes, fix any wrong ones, and press Analyze."}
          {mode === "home" && "Screenshot your home village. The counters at the top right and the builder count are read and shown for you to confirm."}
          {mode === "verify" && "After switching accounts in BlueStacks, screenshot the home village to check the right account is open. Set each account's player name in its Farming Strategy panel."}
        </div>
      )}
    </div>
  );
}

function BattleEditor({ det, labels, accountId }) {
  const W = det.image_width, H = det.image_height;
  const [boxes, setBoxes] = useState((det.corrected || det.result).detections || []);
  const [sel, setSel] = useState(null);
  const [addLabel, setAddLabel] = useState("");
  const [analysis, setAnalysis] = useState(null);
  const [saved, setSaved] = useState(!!det.verified);
  const [err, setErr] = useState(null);
  const svgRef = useRef();

  const toImage = (e) => {
    const pt = svgRef.current.createSVGPoint();
    pt.x = e.clientX; pt.y = e.clientY;
    const p = pt.matrixTransform(svgRef.current.getScreenCTM().inverse());
    return { x: p.x, y: p.y };
  };
  const onClick = (e) => {
    if (!addLabel) { setSel(null); return; }
    const { x, y } = toImage(e);
    const s = W * 0.035;
    setBoxes([...boxes, { label: addLabel, x, y, w: s, h: s, confidence: 1, source: "manual" }]);
    setSaved(false); setAnalysis(null);
  };
  const update = (i, patch) => { setBoxes(boxes.map((b, j) => (j === i ? { ...b, ...patch } : b))); setSaved(false); setAnalysis(null); };
  const remove = (i) => { setBoxes(boxes.filter((_, j) => j !== i)); setSel(null); setSaved(false); setAnalysis(null); };

  const analyze = async () => {
    setErr(null);
    try {
      if (!saved) { await api.post(`/api/vision/detections/${det.id}/correct`, { detections: boxes }); setSaved(true); }
      setAnalysis(await api.post(`/api/vision/detections/${det.id}/analyze`, { account_id: accountId }));
    } catch (e) { setErr(e.message); }
  };

  const rec = analysis?.ok ? analysis.recommendation : null;
  const uncertain = boxes.filter((b) => (b.confidence ?? 1) < 0.5).length;
  return (
    <div className="grid xl:grid-cols-[1fr_340px] gap-4">
      <div className="card p-2">
        <svg ref={svgRef} viewBox={`0 0 ${W} ${H}`} className={`w-full rounded-lg ${addLabel ? "cursor-crosshair" : ""}`} onClick={onClick}>
          <image href={api.url(`/api/vision/detections/${det.id}/image`)} width={W} height={H} />
          {analysis?.ok && <circle cx={analysis.base_center.x} cy={analysis.base_center.y} r={W * 0.006} fill="#fff" opacity="0.6" />}
          {rec && (
            <>
              <circle cx={rec.target_cluster.center.x} cy={rec.target_cluster.center.y} r={W * 0.07} fill="#10b981" fillOpacity="0.15" stroke="#10b981" strokeWidth={W * 0.002} />
              {rec.deploy_points.map((p, i) => (
                <g key={i}>
                  <line x1={p.x} y1={p.y} x2={rec.target_cluster.center.x} y2={rec.target_cluster.center.y} stroke="#10b981" strokeWidth={W * 0.0015} strokeDasharray="8 6" />
                  <circle cx={p.x} cy={p.y} r={W * 0.01} fill="#10b981" stroke="#fff" strokeWidth={W * 0.0015} />
                </g>
              ))}
            </>
          )}
          {boxes.map((b, i) => {
            const c = COLORS[b.label] || "#f87171";
            const low = (b.confidence ?? 1) < 0.5;
            return (
              <g key={i} onClick={(e) => { e.stopPropagation(); setSel(i); }} className="cursor-pointer">
                <rect x={b.x - b.w / 2} y={b.y - b.h / 2} width={b.w} height={b.h} fill={c} fillOpacity={sel === i ? 0.35 : 0.08}
                  stroke={c} strokeWidth={W * (sel === i ? 0.003 : 0.0018)} strokeDasharray={low ? "6 4" : ""} />
              </g>
            );
          })}
        </svg>
        <div className="flex flex-wrap gap-3 text-xs text-muted mt-2 px-1">
          <span><span className="text-gold">■</span> Gold</span><span><span className="text-elixir">■</span> Elixir</span>
          <span><span className="text-dark">■</span> Dark Elixir</span><span><span className="text-red-400">■</span> Defense</span>
          <span>dashed = low confidence, check it</span><span className="text-emerald-400">● deploy points</span>
        </div>
      </div>

      <div className="space-y-3">
        <div className="card space-y-2">
          <div className="h2">Detections ({boxes.length})</div>
          {det.result.message && <div className="text-xs text-amber-300">{det.result.message}</div>}
          {uncertain > 0 && <div className="text-xs text-amber-300">{uncertain} low-confidence detection(s). Check them before you analyze.</div>}
          <Field label="Click on the image to add">
            <select className="input" value={addLabel} onChange={(e) => setAddLabel(e.target.value)}>
              <option value="">Off (click a box to select it)</option>
              {labels.map((l) => <option key={l} value={l}>{pretty(l)}</option>)}
            </select>
          </Field>
          {sel != null && boxes[sel] && (
            <div className="rounded-lg border border-line p-2 space-y-2">
              <div className="text-xs text-muted">Selected · confidence {Math.round((boxes[sel].confidence ?? 1) * 100)}% · {boxes[sel].source || "model"}</div>
              <select className="input" value={boxes[sel].label} onChange={(e) => update(sel, { label: e.target.value, confidence: 1 })}>
                {labels.map((l) => <option key={l} value={l}>{pretty(l)}</option>)}
              </select>
              <div className="flex gap-2">
                <button className="btn" onClick={() => update(sel, { confidence: 1 })}>Confirm</button>
                <button className="btn btn-danger" onClick={() => remove(sel)}>Delete</button>
              </div>
            </div>
          )}
          <div className="text-xs text-muted">
            {Object.entries(boxes.reduce((m, b) => ({ ...m, [b.label]: (m[b.label] || 0) + 1 }), {}))
              .sort((a, b) => isResource(b[0]) - isResource(a[0])).map(([l, n]) => `${pretty(l)} ×${n}`).join(" · ") || "none yet"}
          </div>
          <button className="btn btn-primary w-full justify-center" disabled={!boxes.length} onClick={analyze}>
            {saved ? "Analyze" : "Save corrections & analyze"}
          </button>
          {err && <div className="text-xs text-red-300">{err}</div>}
        </div>

        {analysis && (
          <div className="card space-y-2 text-sm">
            <div className="h2">Suggested Strategy</div>
            {!analysis.ok ? <div className="text-amber-300">{analysis.message}</div> : (
              <>
                <div className="rounded-lg bg-emerald-500/10 border border-emerald-500/40 p-2">
                  <div className="text-xs text-emerald-300">Deploy from</div>
                  <div className="font-semibold">{rec.side} side</div>
                  <div className="text-xs mt-1">{rec.objective}</div>
                </div>
                <div className="text-muted text-xs">{rec.summary}</div>
                <div className="text-xs">Least defended side: <b>{analysis.least_defended_side}</b> · Richest side: <b>{rec.richest_side}</b></div>
                <table className="w-full text-xs">
                  <thead className="text-muted"><tr><th className="text-left">Side</th><th>Gold</th><th>Elix</th><th>Dark</th><th>Def</th><th>Score</th></tr></thead>
                  <tbody>
                    {[...analysis.sectors].sort((a, b) => b.net_score - a.net_score).map((s) => (
                      <tr key={s.name} className={s.name === rec.side ? "text-emerald-300" : ""}>
                        <td>{s.name}</td><td className="text-center">{s.counts.gold}</td><td className="text-center">{s.counts.elixir}</td>
                        <td className="text-center">{s.counts.dark}</td><td className="text-center">{s.defenses}</td><td className="text-center">{s.net_score}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <div className="text-[11px] text-muted">Weights from account priority: Gold {Math.round(analysis.weights.gold * 100)}% · Elixir {Math.round(analysis.weights.elixir * 100)}% · Dark {Math.round(analysis.weights.dark * 100)}%</div>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function CounterConfirm({ det, accountId, refresh }) {
  const fields = det.result.fields || {};
  const [vals, setVals] = useState({
    gold: fields.gold?.value ?? null, elixir: fields.elixir?.value ?? null, dark_elixir: fields.dark?.value ?? null,
    builders_free: fields.builders?.value?.free ?? null, builders_total: fields.builders?.value?.total ?? null,
  });
  const [done, setDone] = useState(false);
  const rows = [
    ["gold", "Gold", fields.gold], ["elixir", "Elixir", fields.elixir], ["dark_elixir", "Dark Elixir", fields.dark],
    ["builders_free", "Free builders", fields.builders], ["builders_total", "Total builders", fields.builders],
  ];
  return (
    <div className="grid lg:grid-cols-2 gap-4">
      <div className="card p-2"><img src={api.url(`/api/vision/detections/${det.id}/image`)} className="rounded-lg w-full" /></div>
      <div className="card space-y-3">
        <div className="h2">Confirm values</div>
        {!det.result.ok && <div className="text-xs text-amber-300">{det.result.message}</div>}
        <div className="text-xs text-muted">Nothing is saved until you confirm. Fix any value that looks wrong.</div>
        {rows.map(([k, label, f]) => (
          <div key={k} className="flex items-center gap-3">
            <span className="w-32 text-sm">{label}</span>
            <NumInput value={vals[k]} onChange={(x) => setVals({ ...vals, [k]: x })} />
            <span className={`text-xs w-28 ${f?.needs_review ? "text-amber-300" : "text-muted"}`}>
              {f ? `${Math.round(f.confidence * 100)}%${f.needs_review ? " · check" : ""}` : "not read"}
            </span>
          </div>
        ))}
        <button className="btn btn-primary" disabled={done} onClick={async () => {
          const body = { account_id: accountId };
          Object.entries(vals).forEach(([k, v]) => { if (v !== null && v !== undefined) body[k] = v; });
          await api.post(`/api/vision/detections/${det.id}/apply-counters`, body);
          setDone(true); refresh();
        }}>{done ? "Saved to account" : "Confirm & update account"}</button>
      </div>
    </div>
  );
}

function VerifyResult({ r, dash, refresh }) {
  return (
    <div className="card text-sm space-y-2 max-w-xl">
      <div className="h2">Account check</div>
      {!r.ocr_available && <div className="text-amber-300 text-xs">Tesseract OCR is not installed, so the name can't be read. Confirm the account yourself.</div>}
      <div>Read on screen: <b>{r.read_text || "(nothing)"}</b> ({Math.round((r.ocr_confidence || 0) * 100)}%)</div>
      <div>Best match: <b>{r.account_name || "none"}</b> · similarity {Math.round(r.score * 100)}%</div>
      {r.matches_expected === true && <div className="text-emerald-300">✓ This is the selected account.</div>}
      {r.matches_expected === false && <div className="text-amber-300">This doesn't look like the selected account. Check BlueStacks before you continue.</div>}
      <div className="flex gap-2 flex-wrap">
        {dash.accounts.map((v) => (
          <button key={v.account.id} className="btn" onClick={async () => { await api.post(`/api/accounts/${v.account.id}/select`); refresh(); }}>
            It's {v.account.name}
          </button>
        ))}
      </div>
    </div>
  );
}
