import React, { useCallback, useEffect, useState } from "react";
import { api } from "./api.js";
import Dashboard from "./pages/Dashboard.jsx";
import AccountPage from "./pages/AccountPage.jsx";
import Vision from "./pages/Vision.jsx";
import Simulation from "./pages/Simulation.jsx";
import Settings from "./pages/Settings.jsx";
import Notifications from "./pages/Notifications.jsx";

function useDesktopNotifications(enabled) {
  useEffect(() => {
    if ("Notification" in window && Notification.permission === "default") Notification.requestPermission();
    const poll = async () => {
      try {
        const items = await api.get("/api/notifications?undelivered=true");
        if (!items.length) return;
        if (enabled && "Notification" in window && Notification.permission === "granted") {
          items.slice(0, 5).reverse().forEach((n) => new Notification("COC Manager", { body: n.message }));
        }
        await api.post("/api/notifications/delivered", { ids: items.map((n) => n.id) });
      } catch (_) {}
    };
    poll();
    const t = setInterval(poll, 15000);
    return () => clearInterval(t);
  }, [enabled]);
}

export default function App() {
  const [page, setPage] = useState({ name: "dashboard" });
  const [dash, setDash] = useState(null);
  const [error, setError] = useState(null);
  const [notifyOn, setNotifyOn] = useState(true);

  const refresh = useCallback(async () => {
    try {
      setDash(await api.get("/api/dashboard"));
      setError(null);
    } catch (e) {
      setError(e.message);
    }
  }, []);

  useEffect(() => {
    refresh();
    api.get("/api/settings").then((s) => setNotifyOn(s.notifications_enabled)).catch(() => {});
    const t = setInterval(refresh, 20000);
    return () => clearInterval(t);
  }, [refresh]);
  useDesktopNotifications(notifyOn);

  const nav = [
    { name: "dashboard", label: "Dashboard" },
    ...(dash?.accounts || []).map((v) => ({
      name: "account",
      id: v.account.id,
      label: v.account.name,
      sub: v.status_label,
      current: dash.current_account_id === v.account.id,
    })),
    { name: "vision", label: "AI Vision" },
    { name: "simulation", label: "Simulation" },
    { name: "notifications", label: "Notifications" },
    { name: "settings", label: "Settings" },
  ];
  const isActive = (n) => n.name === page.name && (n.id === undefined || n.id === page.id);

  return (
    <div className="flex h-screen">
      <aside className="w-56 shrink-0 border-r border-line bg-panel flex flex-col">
        <div className="px-4 py-4 border-b border-line">
          <div className="font-semibold">COC Farming Manager</div>
          <div className="text-xs text-muted">Farm → Upgrade → Next account</div>
        </div>
        <nav className="flex-1 overflow-y-auto p-2 space-y-0.5">
          {nav.map((n, i) => (
            <React.Fragment key={n.name + (n.id || "")}>
              {n.name === "account" && nav[i - 1]?.name !== "account" && (
                <div className="px-3 pt-3 pb-1 text-[11px] uppercase tracking-wide text-muted">Accounts</div>
              )}
              {n.name === "vision" && <div className="px-3 pt-3 pb-1 text-[11px] uppercase tracking-wide text-muted">Tools</div>}
              <button
                onClick={() => setPage({ name: n.name, id: n.id })}
                className={`w-full text-left rounded-lg px-3 py-2 text-sm ${isActive(n) ? "bg-panel2 text-ink" : "text-muted hover:text-ink"}`}
              >
                <div className="flex items-center gap-2">
                  {n.label}
                  {n.current && <span className="text-[10px] text-emerald-400">● active</span>}
                </div>
                {n.sub && <div className="text-[11px] text-muted">{n.sub}</div>}
              </button>
            </React.Fragment>
          ))}
        </nav>
        <AddAccount onAdded={(id) => { refresh(); setPage({ name: "account", id }); }} />
      </aside>
      <main className="flex-1 overflow-y-auto">
        {error && (
          <div className="m-4 card border-red-500/50 text-red-300 text-sm">
            Can't reach the backend: {error}. It starts with the app; if this persists, check Settings → Logs.
          </div>
        )}
        {!dash ? (
          <div className="p-8 text-muted">Loading…</div>
        ) : page.name === "dashboard" ? (
          <Dashboard dash={dash} refresh={refresh} open={(id) => setPage({ name: "account", id })} />
        ) : page.name === "account" ? (
          <AccountPage key={page.id} id={page.id} refresh={refresh} onDeleted={() => { refresh(); setPage({ name: "dashboard" }); }} />
        ) : page.name === "vision" ? (
          <Vision dash={dash} refresh={refresh} />
        ) : page.name === "simulation" ? (
          <Simulation />
        ) : page.name === "notifications" ? (
          <Notifications />
        ) : (
          <Settings refresh={refresh} onNotify={setNotifyOn} />
        )}
      </main>
    </div>
  );
}

function AddAccount({ onAdded }) {
  const [name, setName] = useState("");
  const add = async (e) => {
    e.preventDefault();
    if (!name.trim()) return;
    const v = await api.post("/api/accounts", { name: name.trim() });
    setName("");
    onAdded(v.account.id);
  };
  return (
    <form className="p-3 border-t border-line flex gap-1.5" onSubmit={add}>
      <input className="input" placeholder="New account name" value={name} onChange={(e) => setName(e.target.value)} />
      <button className="btn" disabled={!name.trim()} title="Add account">+</button>
    </form>
  );
}
