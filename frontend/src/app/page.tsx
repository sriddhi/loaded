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

      {/* Heartbeat status dot — bottom center */}
      <HeartbeatDot />
    </main>
  );
}
