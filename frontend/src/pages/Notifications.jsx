import React, { useEffect, useState } from "react";
import { api } from "../api.js";
import { Empty } from "../components/ui.jsx";

export default function Notifications() {
  const [items, setItems] = useState([]);
  const load = () => api.get("/api/notifications").then(setItems);
  useEffect(() => { load(); const t = setInterval(load, 15000); return () => clearInterval(t); }, []);
  return (
    <div className="p-6 max-w-3xl space-y-3">
      <div className="flex items-center">
        <h1 className="text-2xl font-semibold">Notifications</h1>
        <button className="btn ml-auto" onClick={() => api.post("/api/notifications/read-all").then(load)}>Mark all read</button>
      </div>
      <div className="card divide-y divide-line">
        {!items.length && <Empty>No notifications yet.</Empty>}
        {items.map((n) => (
          <div key={n.id} className={`py-2 flex gap-3 text-sm ${n.read ? "text-muted" : ""}`}>
            <span className="text-xs text-muted w-36 shrink-0">{new Date(n.created_at).toLocaleString()}</span>
            <span>{n.message}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
