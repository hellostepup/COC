import React from "react";
import { STATUS_STYLE, short, fmt } from "../api.js";

export function StatusChip({ status, label }) {
  return <span className={`chip ${STATUS_STYLE[status] || STATUS_STYLE.idle}`}>{label}</span>;
}

export function Bar({ pct, color = "bg-sky-500", className = "" }) {
  const p = Math.max(0, Math.min(100, pct || 0));
  return (
    <div className={`h-1.5 w-full rounded-full bg-[#0e121a] overflow-hidden ${className}`}>
      <div className={`h-full ${color} transition-all`} style={{ width: `${p}%` }} />
    </div>
  );
}

export function ResourceLine({ res, have, max, target }) {
  const pct = max ? (100 * have) / max : 0;
  return (
    <div>
      <div className="flex justify-between text-xs">
        <span className={res.color}>{res.label}</span>
        <span className="text-ink" title={fmt(have)}>
          {short(have)}
          <span className="text-muted"> / {short(max)}</span>
        </span>
      </div>
      <Bar pct={pct} color={res.bg} className="mt-1" />
      {target > 0 && (
        <div className="text-[11px] text-muted mt-0.5">
          Target {short(target)} · {have >= target ? <span className="text-emerald-400">reached</span> : <>need {short(target - have)}</>}
        </div>
      )}
    </div>
  );
}

export function Field({ label, children, className = "" }) {
  return (
    <label className={`block ${className}`}>
      <span className="label">{label}</span>
      {children}
    </label>
  );
}

export function NumInput({ value, onChange, ...rest }) {
  return (
    <input
      className="input"
      inputMode="numeric"
      value={value ?? ""}
      onChange={(e) => {
        const v = e.target.value.replace(/[^0-9]/g, "");
        onChange(v === "" ? 0 : parseInt(v, 10));
      }}
      {...rest}
    />
  );
}

export function Empty({ children }) {
  return <div className="text-muted text-sm py-6 text-center">{children}</div>;
}
