"use client";

import { useAuth } from "./AuthProvider";

export default function UserBadge() {
  const { user, logout } = useAuth();

  if (!user) return null;

  return (
    <div
      style={{
        position: "fixed",
        top: "1.25rem",
        right: "1.25rem",
        display: "flex",
        alignItems: "center",
        gap: "0.75rem",
        zIndex: 50,
      }}
    >
      <span
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: "0.7rem",
          color: "var(--muted)",
          letterSpacing: "0.08em",
        }}
      >
        {user.email}
        <span
          style={{
            marginLeft: "0.5rem",
            color: "#333",
            padding: "0.15rem 0.45rem",
            border: "1px solid #222",
            borderRadius: 4,
            fontSize: "0.6rem",
            letterSpacing: "0.12em",
            textTransform: "uppercase",
          }}
        >
          {user.role}
        </span>
      </span>
      <button
        onClick={logout}
        style={{
          background: "transparent",
          border: "1px solid #222",
          borderRadius: 5,
          color: "var(--muted)",
          fontFamily: "var(--font-mono)",
          fontSize: "0.65rem",
          letterSpacing: "0.1em",
          textTransform: "uppercase",
          padding: "0.3rem 0.65rem",
          cursor: "pointer",
          transition: "border-color 0.15s, color 0.15s",
        }}
        onMouseEnter={(e) => {
          (e.target as HTMLButtonElement).style.borderColor = "#ef4444";
          (e.target as HTMLButtonElement).style.color = "#ef4444";
        }}
        onMouseLeave={(e) => {
          (e.target as HTMLButtonElement).style.borderColor = "#222";
          (e.target as HTMLButtonElement).style.color = "var(--muted)";
        }}
      >
        sign out
      </button>
    </div>
  );
}
