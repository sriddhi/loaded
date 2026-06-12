import HeartbeatDot from "@/components/HeartbeatDot";

export default function Home(): React.JSX.Element {
  return (
    <main
      style={{
        height: "100vh",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: "12px",
        userSelect: "none",
      }}
    >
      {/* Wordmark */}
      <h1
        style={{
          fontSize: "clamp(2.5rem, 8vw, 6rem)",
          fontWeight: 700,
          letterSpacing: "-0.04em",
          lineHeight: 1,
          color: "var(--fg)",
        }}
      >
        Loaded
      </h1>

      {/* Tagline */}
      <p
        style={{
          fontSize: "clamp(0.75rem, 1.5vw, 0.9rem)",
          letterSpacing: "0.25em",
          textTransform: "uppercase",
          color: "var(--muted)",
          fontWeight: 400,
        }}
      >
        Trading intelligence
      </p>

      {/* Nav */}
      <nav style={{ display: "flex", gap: 20, marginTop: 24 }}>
        {[
          { href: "/fundamentals", label: "Fundamentals" },
          { href: "/signals", label: "Signals" },
          { href: "/strategies", label: "Strategy Lab" },
          { href: "/tools", label: "Tools" },
          { href: "/macro", label: "Macro" },
          { href: "/paper", label: "Paper Trading" },
          { href: "/settings", label: "Settings" },
        ].map((l) => (
          <a
            key={l.href}
            href={l.href}
            style={{
              color: "var(--accent, #e8ff47)",
              fontSize: 13,
              letterSpacing: "0.1em",
              textTransform: "uppercase",
              textDecoration: "none",
            }}
          >
            {l.label}
          </a>
        ))}
      </nav>

      {/* Heartbeat status dot — bottom center */}
      <HeartbeatDot />
    </main>
  );
}
