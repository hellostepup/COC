import React from "react";
import { api, RES, dur, short } from "../api.js";
import { Bar, ResourceLine, StatusChip } from "../components/ui.jsx";

export default function Dashboard({ dash, refresh, open }) {
  const o = dash.overview;
  const cards = [
    ["Total Accounts", o.total_accounts],
    ["Accounts Needing Resources", o.accounts_needing_resources],
    ["Upgrades Ready", o.upgrades_ready, "text-emerald-300"],
    ["Builders Available", o.builders_available],
    ["Upgrades In Progress", o.upgrades_in_progress],
    ["Completed Upgrade Tasks", o.completed_upgrades],
  ];

  if (!dash.accounts.length) {
    return (
      <div className="p-8 max-w-xl">
        <h1 className="text-2xl font-semibold mb-2">Welcome</h1>
        <p className="text-muted mb-4">
          Add your accounts from the sidebar, or load the four starter accounts from the requirements (Gold/Defense,
          Elixir/Army, Dark/Heroes, Balanced). Starter costs are placeholders, so edit them to match the game.
        </p>
        <button className="btn btn-primary" onClick={async () => { await api.post("/api/seed-demo"); refresh(); }}>
          Load 4 starter accounts
        </button>
      </div>
    );
  }

  const next = dash.next_recommended;
  return (
    <div className="p-6 space-y-6">
      <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-3">
        {cards.map(([label, value, cls]) => (
          <div key={label} className="card">
            <div className="text-xs text-muted">{label}</div>
            <div className={`text-2xl font-semibold mt-1 ${cls || ""}`}>{value}</div>
          </div>
        ))}
      </div>

      <div className="grid xl:grid-cols-3 gap-4">
        <div className="card xl:col-span-1">
          <div className="h2 mb-1">Account Rotation</div>
          <div className="text-xs text-muted mb-3">You switch accounts in BlueStacks; this shows which one to open next.</div>
          {next ? (
            <div className="rounded-lg border border-emerald-500/40 bg-emerald-500/10 p-3 mb-3">
              <div className="text-xs text-emerald-300">Next recommended</div>
              <div className="font-semibold">{next.name}</div>
              <div className="text-sm text-muted">{next.reason}</div>
              {!next.is_current && (
                <button
                  className="btn btn-primary mt-2"
                  onClick={async () => { await api.post(`/api/accounts/${next.account_id}/select`); refresh(); }}
                >
                  I switched to {next.name}
                </button>
              )}
            </div>
          ) : (
            <div className="text-sm text-muted mb-3">No account has useful work right now. All builders are busy.</div>
          )}
          <ol className="space-y-1.5">
            {dash.rotation.map((r, i) => (
              <li key={r.account_id} className="flex items-center gap-2 text-sm">
                <span className="w-5 text-muted">{i + 1}.</span>
                <button className="hover:underline" onClick={() => open(r.account_id)}>{r.name}</button>
                {r.is_current && <span className="text-[10px] text-emerald-400">active</span>}
                <span className="ml-auto text-xs text-muted truncate max-w-[55%] text-right">{r.reason}</span>
              </li>
            ))}
          </ol>
        </div>

        <div className="xl:col-span-2 grid md:grid-cols-2 gap-4">
          {dash.accounts.map((v) => (
            <AccountCard key={v.account.id} v={v} open={() => open(v.account.id)} current={dash.current_account_id === v.account.id} />
          ))}
        </div>
      </div>
    </div>
  );
}

function AccountCard({ v, open, current }) {
  const a = v.account;
  const p = v.plan;
  const active = p.tasks.filter((t) => t.status !== "completed");
  return (
    <div className={`card cursor-pointer hover:border-muted ${current ? "border-emerald-600/60" : ""}`} onClick={open}>
      <div className="flex items-start justify-between gap-2">
        <div>
          <div className="font-semibold">{a.name} <span className="text-muted font-normal text-sm">TH{a.town_hall}</span></div>
          <div className="text-xs text-muted">{a.focus || a.objective}</div>
        </div>
        <StatusChip status={v.flags.primary} label={v.status_label} />
      </div>
      <div className="space-y-2 mt-3">
        {RES.map((r) => (
          <ResourceLine key={r.key} res={r} have={a[r.bal]} max={a[r.max]} target={p.targets[r.key].target} />
        ))}
      </div>
      <div className="flex items-center justify-between text-xs text-muted mt-3">
        <span>Builders {p.builders.free}/{p.builders.total} free</span>
        <span>{p.completed_count} done · {p.in_progress_count} running · {p.planned_count} planned</span>
      </div>
      <div className="mt-2 space-y-1.5">
        {active.slice(0, 3).map((t) => (
          <div key={t.id} className="text-xs">
            <div className="flex justify-between">
              <span className={t.ready ? "text-emerald-300" : ""}>{t.priority}. {t.building}</span>
              <span className="text-muted">
                {t.either ? `${t.either.done}/${t.either.total} · ${t.either.can_do_now} doable now`
                  : t.status === "in_progress" ? dur(t.progress?.seconds_left) + " left"
                  : t.ready ? "ready" : RES.filter((r) => t.remaining[r.key]).map((r) => `${short(t.remaining[r.key])} ${r.label}`).join(", ") || t.blockers[0]}
              </span>
            </div>
            {t.status === "in_progress" && <Bar pct={t.progress?.percent} color="bg-sky-500" className="mt-0.5" />}
          </div>
        ))}
      </div>
    </div>
  );
}
