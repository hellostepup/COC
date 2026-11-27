import React, { useEffect, useState } from "react";
import { api, RES, dur, fmt, short } from "../api.js";
import { Bar, Empty, Field, NumInput, ResourceLine, StatusChip } from "../components/ui.jsx";

export default function AccountPage({ id, refresh, onDeleted }) {
  const [v, setV] = useState(null);
  const [err, setErr] = useState(null);

  const load = async () => {
    try { setV(await api.get(`/api/accounts/${id}`)); } catch (e) { setErr(e.message); }
  };
  useEffect(() => { load(); const t = setInterval(load, 20000); return () => clearInterval(t); }, [id]);

  const run = async (fn) => {
    try { const res = await fn(); if (res?.account) setV(res); else await load(); setErr(null); refresh(); }
    catch (e) { setErr(e.message); }
  };

  if (!v) return <div className="p-8 text-muted">{err || "Loading…"}</div>;
  const a = v.account;
  return (
    <div className="p-6 space-y-4 max-w-6xl">
      <div className="flex items-center gap-3 flex-wrap">
        <h1 className="text-2xl font-semibold">{a.name}</h1>
        <span className="text-muted">TH{a.town_hall}</span>
        <StatusChip status={v.flags.primary} label={v.status_label} />
        <div className="ml-auto flex gap-2">
          <button className="btn" onClick={() => run(() => api.post(`/api/accounts/${id}/select`))}>Set as active account</button>
          <button className="btn btn-danger" onClick={() => {
            if (confirm(`Delete ${a.name} and its upgrade queue?`)) api.del(`/api/accounts/${id}`).then(onDeleted);
          }}>Delete</button>
        </div>
      </div>
      {err && <div className="card border-red-500/50 text-red-300 text-sm">{err}</div>}

      <div className="grid lg:grid-cols-2 gap-4">
        <Resources v={v} run={run} />
        <Strategy a={a} run={run} />
      </div>
      <Queue v={v} run={run} />
    </div>
  );
}

function Resources({ v, run }) {
  const a = v.account;
  const p = v.plan;
  const [form, setForm] = useState(a);
  const [loot, setLoot] = useState({ gold: 0, elixir: 0, dark: 0 });
  useEffect(() => setForm(a), [a.updated_at]);
  const set = (k) => (val) => setForm({ ...form, [k]: val });

  return (
    <div className="card space-y-3">
      <div className="h2">Resources & Builders</div>
      <div className="space-y-2">
        {RES.map((r) => <ResourceLine key={r.key} res={r} have={a[r.bal]} max={a[r.max]} target={p.targets[r.key].target} />)}
      </div>
      <div className="grid grid-cols-3 gap-2">
        {RES.map((r) => <Field key={r.key} label={`Current ${r.label}`}><NumInput value={form[r.bal]} onChange={set(r.bal)} /></Field>)}
        {RES.map((r) => <Field key={r.key} label={`Max ${r.label} storage`}><NumInput value={form[r.max]} onChange={set(r.max)} /></Field>)}
        <Field label="Total builders"><NumInput value={form.builders_total} onChange={set("builders_total")} /></Field>
        <Field label="Busy on untracked work"><NumInput value={form.builders_busy_untracked} onChange={set("builders_busy_untracked")} /></Field>
        <div className="flex items-end">
          <button className="btn btn-primary w-full justify-center" onClick={() => run(() => api.patch(`/api/accounts/${a.id}`, {
            gold: form.gold, elixir: form.elixir, dark_elixir: form.dark_elixir, max_gold: form.max_gold, max_elixir: form.max_elixir,
            max_dark: form.max_dark, builders_total: form.builders_total, builders_busy_untracked: form.builders_busy_untracked,
          }))}>Save</button>
        </div>
      </div>
      <div className="text-xs text-muted">
        Builders: {p.builders.busy} busy, {p.builders.free} free. Remaining for whole queue:{" "}
        {RES.map((r) => <span key={r.key} className={`${r.color} mr-2`}>{short(p.total_remaining[r.key])} {r.label}</span>)}
      </div>
      <div className="border-t border-line pt-3">
        <div className="label">Add battle loot</div>
        <div className="flex gap-2">
          {RES.map((r) => <NumInput key={r.key} placeholder={r.label} value={loot[r.key] || ""} onChange={(x) => setLoot({ ...loot, [r.key]: x })} />)}
          <button className="btn" onClick={() => { run(() => api.post(`/api/accounts/${a.id}/loot`, loot)); setLoot({ gold: 0, elixir: 0, dark: 0 }); }}>Add</button>
        </div>
      </div>
    </div>
  );
}

function Strategy({ a, run }) {
  const [f, setF] = useState(a);
  useEffect(() => setF(a), [a.updated_at]);
  const set = (k) => (val) => setF({ ...f, [k]: val });
  const total = f.priority_gold + f.priority_elixir + f.priority_dark;

  return (
    <div className="card space-y-3">
      <div className="h2">Farming Strategy</div>
      <div className="grid grid-cols-2 gap-2">
        <Field label="Name"><input className="input" value={f.name} onChange={(e) => set("name")(e.target.value)} /></Field>
        <Field label="Player name / tag (for account check)"><input className="input" value={f.player_tag || ""} onChange={(e) => set("player_tag")(e.target.value)} /></Field>
        <Field label="Town Hall"><NumInput value={f.town_hall} onChange={set("town_hall")} /></Field>
        <Field label="Focus"><input className="input" value={f.focus || ""} onChange={(e) => set("focus")(e.target.value)} /></Field>
        <Field label="Attack objective">
          <select className="input" value={f.objective} onChange={(e) => set("objective")(e.target.value)}>
            <option value="gold">Maximum Gold</option><option value="elixir">Maximum Elixir</option>
            <option value="dark">Maximum Dark Elixir</option><option value="balanced">Balanced Farming</option>
          </select>
        </Field>
        <Field label="Defense avoidance">
          <select className="input" value={f.defense_avoidance} onChange={(e) => set("defense_avoidance")(e.target.value)}>
            <option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option>
          </select>
        </Field>
      </div>
      <div>
        <div className="label">Resource priority {total !== 100 && <span className="text-amber-300">(sums to {total}%, used as ratio)</span>}</div>
        {RES.map((r) => (
          <div key={r.key} className="flex items-center gap-3 text-sm">
            <span className={`w-24 ${r.color}`}>{r.label}</span>
            <input type="range" min="0" max="100" className="flex-1" value={f[r.prio]} onChange={(e) => set(r.prio)(+e.target.value)} />
            <span className="w-10 text-right">{f[r.prio]}%</span>
          </div>
        ))}
      </div>
      <div className="grid grid-cols-3 gap-2">
        {RES.map((r) => <Field key={r.key} label={`Minimum ${r.label} target`}><NumInput value={f[r.min]} onChange={set(r.min)} /></Field>)}
      </div>
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={!!f.fill_storage_when_done} onChange={(e) => set("fill_storage_when_done")(e.target.checked)} />
        When every upgrade is done, keep farming until storage is full (resources with priority above 0)
      </label>
      <Field label="Preferred troop composition"><input className="input" placeholder="e.g. 8 Giants, 20 Goblins, 40 Archers" value={f.troop_composition || ""} onChange={(e) => set("troop_composition")(e.target.value)} /></Field>
      <button className="btn btn-primary" onClick={() => run(() => api.patch(`/api/accounts/${a.id}`, {
        name: f.name, player_tag: f.player_tag, town_hall: f.town_hall, focus: f.focus, objective: f.objective,
        defense_avoidance: f.defense_avoidance, priority_gold: f.priority_gold, priority_elixir: f.priority_elixir,
        priority_dark: f.priority_dark, min_gold: f.min_gold, min_elixir: f.min_elixir, min_dark: f.min_dark,
        troop_composition: f.troop_composition, fill_storage_when_done: !!f.fill_storage_when_done,
      }))}>Save strategy</button>
    </div>
  );
}

const BLANK = { building: "", category: "defense", current_level: 1, target_level: 2, cost_gold: 0, cost_elixir: 0, cost_dark: 0, duration_days: 0, duration_hours: 0, builders_required: 1, quantity: 1, done_count: 0, cost_either: 0 };

function Queue({ v, run }) {
  const a = v.account;
  const byId = Object.fromEntries(v.upgrades.map((u) => [u.id, u]));
  const [editing, setEditing] = useState(null); // upgrade id or "new"
  const [starting, setStarting] = useState(null);
  const tasks = v.plan.tasks;
  const open = tasks.filter((t) => t.status !== "completed");
  const done = tasks.filter((t) => t.status === "completed");

  const move = (tid, dir) => {
    const ids = open.map((t) => t.id);
    const i = ids.indexOf(tid), j = i + dir;
    if (j < 0 || j >= ids.length) return;
    [ids[i], ids[j]] = [ids[j], ids[i]];
    run(() => api.post(`/api/accounts/${a.id}/upgrades/reorder`, { ids }));
  };

  return (
    <div className="card">
      <div className="flex items-center mb-3">
        <div className="h2">Upgrade Queue</div>
        <span className="text-xs text-muted ml-3">Gems are never spent for you. Start upgrades in the game, then confirm here.</span>
        <button className="btn ml-auto" onClick={() => setEditing("new")}>+ Add upgrade</button>
      </div>
      {editing === "new" && <UpgradeForm initial={BLANK} onCancel={() => setEditing(null)}
        onSave={(d) => { setEditing(null); run(() => api.post(`/api/accounts/${a.id}/upgrades`, d)); }} />}
      {!open.length && editing !== "new" && <Empty>No upgrades planned. Add the buildings you want to upgrade, in priority order.</Empty>}
      <div className="space-y-2">
        {open.map((t, i) => {
          const u = byId[t.id];
          if (editing === t.id) {
            return <UpgradeForm key={t.id} initial={{ ...u, duration_days: Math.floor(u.duration_minutes / 1440), duration_hours: Math.floor((u.duration_minutes % 1440) / 60) }}
              onCancel={() => setEditing(null)} onSave={(d) => { setEditing(null); run(() => api.patch(`/api/upgrades/${t.id}`, d)); }} />;
          }
          return (
            <div key={t.id} className={`rounded-lg border p-3 ${t.ready ? "border-emerald-500/60 bg-emerald-500/5" : "border-line bg-panel2/40"}`}>
              <div className="flex items-center gap-3 flex-wrap">
                <div className="flex flex-col">
                  <button className="text-muted hover:text-ink text-xs leading-none" disabled={i === 0} onClick={() => move(t.id, -1)}>▲</button>
                  <button className="text-muted hover:text-ink text-xs leading-none" disabled={i === open.length - 1} onClick={() => move(t.id, 1)}>▼</button>
                </div>
                <div className="w-6 text-muted text-sm">#{i + 1}</div>
                <div className="min-w-[180px]">
                  <div className="font-medium">{u.building} <span className="text-muted text-sm">Lv {u.current_level} → {u.target_level}</span></div>
                  <div className="text-xs text-muted">{u.category} · {dur(u.duration_minutes * 60)} · {u.builders_required} builder{u.builders_required > 1 ? "s" : ""}</div>
                </div>
                <div className="text-sm flex gap-3">
                  {t.either && <span title="per wall, Gold or Elixir"><span className="text-gold">{short(t.either.unit_cost)}</span> <span className="text-muted">or</span> <span className="text-elixir">{short(t.either.unit_cost)}</span> <span className="text-muted text-xs">each</span></span>}
                  {RES.filter((r) => t.cost[r.key]).map((r) => (
                    <span key={r.key} className={r.color} title={fmt(t.cost[r.key])}>{short(t.cost[r.key])}</span>
                  ))}
                </div>
                <div className="flex-1 min-w-[200px] text-xs">
                  {t.either ? (
                    <div>
                      <div className="flex justify-between">
                        <span>{t.either.done} / {t.either.total} done · <b>{t.either.left} left</b></span>
                        <span className={t.ready ? "text-emerald-300" : "text-amber-200/80"}>
                          {t.either.can_do_now > 0 ? `${t.either.can_do_now} can be done now (${t.either.pay_with_gold} Gold, ${t.either.pay_with_elixir} Elixir)` : "none affordable now"}
                        </span>
                      </div>
                      <Bar pct={t.either.percent} color="bg-emerald-500" className="mt-1" />
                      {t.either.short_units > 0 && <div className="text-amber-200/80 mt-0.5">Farm about {fmt(t.either.loot_needed)} more Gold or Elixir for the other {t.either.short_units}</div>}
                      {!t.builder_ok && <div className="text-amber-300 mt-0.5">No free builder</div>}
                    </div>
                  ) : t.status === "in_progress" ? (
                    <div>
                      <div className="flex justify-between"><span className="text-sky-300">In Progress</span><span className="text-muted">{t.progress?.percent}% · {dur(t.progress?.seconds_left)} left</span></div>
                      <Bar pct={t.progress?.percent} className="mt-1" />
                    </div>
                  ) : t.ready ? (
                    <div className="text-emerald-300">
                      Upgrade Ready{t.delays?.length ? <span className="text-amber-300"> · starting now delays {t.delays.join(", ")}</span> : null}
                    </div>
                  ) : (
                    <div className="text-amber-200/80">{t.blockers.join(" · ")}</div>
                  )}
                </div>
                <div className="flex gap-1.5">
                  {t.status === "planned" && !t.either && <button className="btn btn-primary" disabled={!t.builder_ok} onClick={() => setStarting(t.id)}>I started it</button>}
                  {t.status === "planned" && t.either && <button className="btn btn-primary" disabled={!t.builder_ok} onClick={() => setStarting(t.id)}>I upgraded walls</button>}
                  {t.status === "in_progress" && <button className="btn" onClick={() => run(() => api.post(`/api/upgrades/${t.id}/complete`))}>Mark done</button>}
                  {t.status === "in_progress" && <button className="btn" onClick={() => run(() => api.post(`/api/upgrades/${t.id}/revert`))}>Undo start</button>}
                  <button className="btn" onClick={() => setEditing(t.id)}>Edit</button>
                  <button className="btn btn-danger" onClick={() => confirm(`Remove ${u.building}?`) && run(() => api.del(`/api/upgrades/${t.id}`))}>✕</button>
                </div>
              </div>
              {starting === t.id && t.either && <WallConfirm t={t} onCancel={() => setStarting(null)}
                onConfirm={(body) => { setStarting(null); run(() => api.post(`/api/upgrades/${t.id}/units`, body)); }} />}
              {starting === t.id && !t.either && <StartConfirm u={u} affordable={t.affordable} onCancel={() => setStarting(null)}
                onConfirm={(body) => { setStarting(null); run(() => api.post(`/api/upgrades/${t.id}/start`, body)); }} />}
            </div>
          );
        })}
      </div>
      {open.length > 0 && (
        <div className="text-xs text-muted mt-3">
          Total required for planned upgrades:{" "}
          {RES.map((r) => <span key={r.key} className={`${r.color} mr-3`}>{fmt(v.plan.total_required[r.key])} {r.label}</span>)}
        </div>
      )}
      {done.length > 0 && (
        <details className="mt-4">
          <summary className="text-sm text-muted cursor-pointer">Completed ({done.length})</summary>
          <ul className="mt-2 text-sm space-y-1">
            {done.map((t) => (
              <li key={t.id} className="flex gap-2 items-center">
                <span className="text-emerald-400">✓</span>{byId[t.id].building} Lv {byId[t.id].target_level}
                <button className="text-xs text-muted hover:text-ink ml-2" onClick={() => run(() => api.post(`/api/upgrades/${t.id}/revert`))}>reopen</button>
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

function WallConfirm({ t, onCancel, onConfirm }) {
  const [g, setG] = useState(t.either.pay_with_gold);
  const [e, setE] = useState(t.either.pay_with_elixir);
  const [deduct, setDeduct] = useState(true);
  const over = g + e > t.either.left;
  return (
    <div className="mt-3 border-t border-line pt-3 flex flex-wrap items-end gap-3 text-sm">
      <div className="text-muted w-full">How many walls did you upgrade in the game, and which resource did you pay with?</div>
      <Field label="Paid with Gold"><NumInput value={g} onChange={setG} /></Field>
      <Field label="Paid with Elixir"><NumInput value={e} onChange={setE} /></Field>
      <label className="flex items-center gap-1.5"><input type="checkbox" checked={deduct} onChange={(x) => setDeduct(x.target.checked)} /> Subtract cost from balance</label>
      <button className="btn btn-primary" disabled={!g && !e || over} onClick={() => onConfirm({ with_gold: g, with_elixir: e, deduct_cost: deduct })}>Save {g + e} walls</button>
      <button className="btn" onClick={onCancel}>Cancel</button>
      {over && <div className="text-amber-300 text-xs w-full">Only {t.either.left} left.</div>}
    </div>
  );
}

function StartConfirm({ u, affordable, onCancel, onConfirm }) {
  const [deduct, setDeduct] = useState(true);
  const [days, setDays] = useState(Math.floor(u.duration_minutes / 1440));
  const [hours, setHours] = useState(Math.floor((u.duration_minutes % 1440) / 60));
  return (
    <div className="mt-3 border-t border-line pt-3 flex flex-wrap items-end gap-3 text-sm">
      <div className="text-muted">Confirm you started <b className="text-ink">{u.building}</b> in the game.</div>
      {!affordable && <div className="text-amber-300 w-full text-xs">Tracked balance is lower than the cost. Update your balance first if it is out of date.</div>}
      <Field label="Duration days"><NumInput value={days} onChange={setDays} /></Field>
      <Field label="hours"><NumInput value={hours} onChange={setHours} /></Field>
      <label className="flex items-center gap-1.5"><input type="checkbox" checked={deduct} onChange={(e) => setDeduct(e.target.checked)} /> Subtract cost from balance</label>
      <button className="btn btn-primary" onClick={() => onConfirm({ deduct_cost: deduct, duration_minutes: days * 1440 + hours * 60 })}>Confirm: In Progress</button>
      <button className="btn" onClick={onCancel}>Cancel</button>
    </div>
  );
}

function UpgradeForm({ initial, onSave, onCancel }) {
  const [f, setF] = useState(initial);
  const set = (k) => (val) => setF({ ...f, [k]: val });
  const wall = f.category === "wall";
  const save = () => onSave(wall ? {
    building: f.building || "Wall", category: "wall", current_level: f.current_level, target_level: f.target_level,
    quantity: f.quantity || 1, done_count: f.done_count || 0, cost_either: f.cost_either || 0,
    cost_gold: 0, cost_elixir: 0, cost_dark: 0, builders_required: 1, duration_minutes: 0,
  } : {
    building: f.building, category: f.category, current_level: f.current_level, target_level: f.target_level,
    cost_gold: f.cost_gold, cost_elixir: f.cost_elixir, cost_dark: f.cost_dark, builders_required: f.builders_required || 1,
    duration_minutes: (f.duration_days || 0) * 1440 + (f.duration_hours || 0) * 60,
  });
  if (wall) {
    return (
      <div className="rounded-lg border border-sky-500/50 p-3 mb-2 grid grid-cols-2 md:grid-cols-6 gap-2">
        <Field label="Name" className="col-span-2"><input className="input" value={f.building} onChange={(e) => set("building")(e.target.value)} placeholder="Wall" /></Field>
        <Field label="Category">
          <select className="input" value={f.category} onChange={(e) => set("category")(e.target.value)}>
            {["defense", "army", "hero", "resource", "trap", "wall", "other"].map((c) => <option key={c}>{c}</option>)}
          </select>
        </Field>
        <Field label="Current level"><NumInput value={f.current_level} onChange={set("current_level")} /></Field>
        <Field label="Target level"><NumInput value={f.target_level} onChange={set("target_level")} /></Field>
        <Field label="Number of walls"><NumInput value={f.quantity} onChange={set("quantity")} /></Field>
        <Field label="Already done"><NumInput value={f.done_count} onChange={set("done_count")} /></Field>
        <Field label="Cost per wall (Gold or Elixir)" className="col-span-2"><NumInput value={f.cost_either} onChange={set("cost_either")} /></Field>
        <div className="flex items-end gap-2">
          <button className="btn btn-primary" disabled={!f.cost_either || !f.quantity} onClick={save}>Save</button>
          <button className="btn" onClick={onCancel}>Cancel</button>
        </div>
      </div>
    );
  }
  return (
    <div className="rounded-lg border border-sky-500/50 p-3 mb-2 grid grid-cols-2 md:grid-cols-6 gap-2">
      <Field label="Building" className="col-span-2"><input className="input" autoFocus value={f.building} onChange={(e) => set("building")(e.target.value)} placeholder="Cannon" /></Field>
      <Field label="Category">
        <select className="input" value={f.category} onChange={(e) => set("category")(e.target.value)}>
          {["defense", "army", "hero", "resource", "trap", "wall", "other"].map((c) => <option key={c}>{c}</option>)}
        </select>
      </Field>
      <Field label="Current level"><NumInput value={f.current_level} onChange={set("current_level")} /></Field>
      <Field label="Target level"><NumInput value={f.target_level} onChange={set("target_level")} /></Field>
      <Field label="Builders"><NumInput value={f.builders_required} onChange={set("builders_required")} /></Field>
      {RES.map((r) => <Field key={r.key} label={`${r.label} cost`}><NumInput value={f[r.cost]} onChange={set(r.cost)} /></Field>)}
      <Field label="Duration days"><NumInput value={f.duration_days} onChange={set("duration_days")} /></Field>
      <Field label="+ hours"><NumInput value={f.duration_hours} onChange={set("duration_hours")} /></Field>
      <div className="flex items-end gap-2">
        <button className="btn btn-primary" disabled={!f.building} onClick={save}>Save</button>
        <button className="btn" onClick={onCancel}>Cancel</button>
      </div>
    </div>
  );
}
