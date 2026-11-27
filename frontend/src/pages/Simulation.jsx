import React, { useState } from "react";
import { api, short } from "../api.js";
import { Field, NumInput } from "../components/ui.jsx";

export default function Simulation() {
  const [seed, setSeed] = useState(1);
  const [res, setRes] = useState(null);
  const [cmp, setCmp] = useState(null);
  const [busy, setBusy] = useState(false);

  const go = async () => {
    setBusy(true);
    try {
      const [a, b] = await Promise.all([
        api.post("/api/simulation/run", { seed, use_strategy: true }),
        api.post("/api/simulation/run", { seed, use_strategy: false }),
      ]);
      setRes(a); setCmp(b);
    } finally { setBusy(false); }
  };

  const avg = (r) => {
    const n = Math.max(1, r.stats.battles);
    return r.stats.loot.gold / n + r.stats.loot.elixir / n;
  };

  return (
    <div className="p-6 space-y-4 max-w-5xl">
      <div>
        <h1 className="text-2xl font-semibold">Workflow Simulation</h1>
        <p className="text-sm text-muted">
          A mock game environment with fake bases, noisy detections and a fake clock. It runs the full loop: account select → target check →
          base search → detection → resource attack → balance update → upgrade → rotation → repeat, on the four starter accounts.
          It never touches your real data or the real game.
        </p>
      </div>
      <div className="flex items-end gap-3">
        <Field label="Random seed"><NumInput value={seed} onChange={setSeed} /></Field>
        <button className="btn btn-primary" disabled={busy} onClick={go}>{busy ? "Running…" : "Run simulation"}</button>
      </div>
      {res && (
        <>
          <div className="grid md:grid-cols-4 gap-3">
            <Stat label="Result" value={res.all_completed ? "All upgrades done" : "Stopped at limit"} cls={res.all_completed ? "text-emerald-300" : "text-amber-300"} />
            <Stat label="Simulated time" value={`${res.sim_hours} h`} />
            <Stat label="Battles (with AI strategy)" value={res.stats.battles} sub={`vs ${cmp.stats.battles} with random deploy`} />
            <Stat label="Avg Gold+Elixir per battle" value={short(Math.round(avg(res)))} sub={`random: ${short(Math.round(avg(cmp)))} (${Math.round(100 * (avg(res) / avg(cmp) - 1))}% better)`} />
          </div>
          <div className="card">
            <div className="h2 mb-2">Accounts</div>
            <table className="w-full text-sm">
              <thead className="text-muted text-xs"><tr><th className="text-left">Account</th><th className="text-left">Status</th><th>Completed</th><th>Running</th><th>Planned</th></tr></thead>
              <tbody>{res.accounts.map((a) => (
                <tr key={a.name}><td>{a.name}</td><td>{a.status}</td><td className="text-center">{a.completed}</td><td className="text-center">{a.in_progress}</td><td className="text-center">{a.planned}</td></tr>
              ))}</tbody>
            </table>
            <div className="text-xs text-muted mt-2">
              {res.stats.upgrades_started} upgrades started · {res.stats.switches} account switches · {res.stats.searches} bases searched · {res.stats.waits} waits for builders
            </div>
          </div>
          <div className="card">
            <div className="h2 mb-2">Event log</div>
            <div className="text-xs font-mono max-h-96 overflow-y-auto space-y-0.5">
              {res.log.filter((e) => e.event !== "battle").map((e, i) => (
                <div key={i}><span className="text-muted">{e.t.slice(5, 16).replace("T", " ")}</span>{" "}
                  <span className="text-sky-300">{e.event}</span>{" "}
                  {e.account}{e.building ? ` · ${e.building}` : ""}{e.reason ? ` · ${e.reason}` : ""}{e.seconds ? ` · ${Math.round(e.seconds / 3600)}h` : ""}
                </div>
              ))}
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function Stat({ label, value, sub, cls = "" }) {
  return (
    <div className="card">
      <div className="text-xs text-muted">{label}</div>
      <div className={`text-xl font-semibold mt-1 ${cls}`}>{value}</div>
      {sub && <div className="text-xs text-muted mt-0.5">{sub}</div>}
    </div>
  );
}
