const BASE = window.COC_API_BASE || "";

async function req(method, path, body, isForm) {
  const opts = { method, headers: {} };
  if (body !== undefined) {
    if (isForm) opts.body = body;
    else {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(body);
    }
  }
  const r = await fetch(BASE + path, opts);
  const text = await r.text();
  const data = text ? JSON.parse(text) : null;
  if (!r.ok) throw new Error((data && data.detail && (typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail))) || r.statusText);
  return data;
}

export const api = {
  get: (p) => req("GET", p),
  post: (p, b = {}) => req("POST", p, b),
  patch: (p, b) => req("PATCH", p, b),
  put: (p, b) => req("PUT", p, b),
  del: (p) => req("DELETE", p),
  form: (p, fd) => req("POST", p, fd, true),
  url: (p) => BASE + p,
};

export const fmt = (n) => (n == null ? "–" : Number(n).toLocaleString("en-US"));
export const short = (n) => {
  if (n == null) return "–";
  const a = Math.abs(n);
  if (a >= 1e6) return (n / 1e6).toFixed(a >= 1e7 ? 1 : 2).replace(/\.?0+$/, "") + "M";
  if (a >= 1e3) return (n / 1e3).toFixed(a >= 1e5 ? 0 : 1).replace(/\.0$/, "") + "K";
  return String(n);
};
export const dur = (s) => {
  if (s == null) return "–";
  const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
  return d ? `${d}d ${h}h` : h ? `${h}h ${m}m` : `${m}m`;
};
export const RES = [
  { key: "gold", bal: "gold", max: "max_gold", cost: "cost_gold", min: "min_gold", prio: "priority_gold", label: "Gold", color: "text-gold", bg: "bg-gold" },
  { key: "elixir", bal: "elixir", max: "max_elixir", cost: "cost_elixir", min: "min_elixir", prio: "priority_elixir", label: "Elixir", color: "text-elixir", bg: "bg-elixir" },
  { key: "dark", bal: "dark_elixir", max: "max_dark", cost: "cost_dark", min: "min_dark", prio: "priority_dark", label: "Dark Elixir", color: "text-dark", bg: "bg-dark" },
];
export const STATUS_STYLE = {
  upgrade_ready: "text-emerald-300 border-emerald-500/50 bg-emerald-500/10",
  farming_required: "text-amber-300 border-amber-500/50 bg-amber-500/10",
  resource_target_reached: "text-sky-300 border-sky-500/50 bg-sky-500/10",
  target_completed: "text-violet-300 border-violet-500/50 bg-violet-500/10",
  builder_busy: "text-orange-300 border-orange-500/50 bg-orange-500/10",
  storage_full: "text-red-300 border-red-500/50 bg-red-500/10",
  all_completed: "text-emerald-200 border-emerald-400/50 bg-emerald-400/10",
  filling_storage: "text-sky-300 border-sky-500/50 bg-sky-500/10",
  idle: "text-muted border-line bg-panel2",
};
