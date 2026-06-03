"use client";

import { useEffect, useState, useCallback } from "react";

type Status = "online" | "offline" | "checking";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const INTERVAL_MS = 30_000;

export default function HeartbeatDot() {
  const [status, setStatus] = useState<Status>("checking");
  const [lastChecked, setLastChecked] = useState<string>("");

  const check = useCallback(async () => {
    try {
      const res = await fetch(`${API}/health`, {
        signal: AbortSignal.timeout(5000),
      });
      setStatus(res.ok ? "online" : "offline");
    } catch {
      setStatus("offline");
    }
    setLastChecked(new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }));
  }, []);

  useEffect(() => {
    check();
    const id = setInterval(check, INTERVAL_MS);
    return () => clearInterval(id);
  }, [check]);

  const color = {
    online: "var(--online)",
    offline: "var(--offline)",
    checking: "var(--checking)",
  }[status];

  const label = {
    online: "systems online",
    offline: "systems offline",
    checking: "checking…",
  }[status];

  return (
    <div style={{
      position: "fixed",
      bottom: "28px",
      left: "50%",
      transform: "translateX(-50%)",
      display: "flex",
      alignItems: "center",
      gap: "8px",
      opacity: 0.6,
    }}>
      {/* Pulsing dot */}
      <div style={{ position: "relative", width: "8px", height: "8px" }}>
        {/* Pulse ring — only when online */}
        {status === "online" && (
          <span style={{
            position: "absolute",
            inset: 0,
            borderRadius: "50%",
            background: color,
            opacity: 0.3,
            animation: "ping 2s ease-in-out infinite",
          }} />
        )}
        <span style={{
          position: "absolute",
          inset: 0,
          borderRadius: "50%",
          background: color,
        }} />
      </div>

      {/* Label */}
      <span style={{
        fontFamily: "var(--font-mono)",
        fontSize: "11px",
        letterSpacing: "0.08em",
        color: "var(--muted)",
        userSelect: "none",
      }}>
        {label}
        {lastChecked && (
          <span style={{ marginLeft: "6px", opacity: 0.5 }}>
            · {lastChecked}
          </span>
        )}
      </span>

      <style>{`
        @keyframes ping {
          0%, 100% { transform: scale(1); opacity: 0.3; }
          50%       { transform: scale(2.4); opacity: 0; }
        }
      `}</style>
    </div>
  );
}
