"use client";

import { useRouter } from "next/navigation";
import { useState, useEffect } from "react";
import { login, setTokens, getToken } from "@/lib/auth";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  // Already logged in → redirect home
  useEffect(() => {
    if (getToken()) router.replace("/");
  }, [router]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const data = await login(email, password);
      setTokens(data.access_token, data.refresh_token);
      router.push("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main style={styles.page}>
      <div style={styles.card}>
        {/* Wordmark */}
        <h1 style={styles.wordmark}>Loaded</h1>
        <p style={styles.tagline}>Trading intelligence</p>

        {/* Divider */}
        <div style={styles.divider} />

        {/* Form */}
        <form onSubmit={handleSubmit} style={styles.form} noValidate>
          <label style={styles.label} htmlFor="email">
            Email
          </label>
          <input
            id="email"
            type="email"
            autoComplete="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="you@example.com"
            style={styles.input}
            disabled={loading}
          />

          <label style={styles.label} htmlFor="password">
            Password
          </label>
          <input
            id="password"
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="••••••••"
            style={styles.input}
            disabled={loading}
          />

          {error && <p style={styles.error}>{error}</p>}

          <button
            type="submit"
            disabled={loading || !email || !password}
            style={{
              ...styles.button,
              opacity: loading || !email || !password ? 0.45 : 1,
              cursor: loading || !email || !password ? "not-allowed" : "pointer",
            }}
          >
            {loading ? "Signing in..." : "Sign in"}
          </button>
        </form>
      </div>
    </main>
  );
}

const styles: Record<string, React.CSSProperties> = {
  page: {
    height: "100vh",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    background: "var(--bg)",
    padding: "1rem",
  },
  card: {
    width: "100%",
    maxWidth: 380,
    background: "#111",
    border: "1px solid #1e1e1e",
    borderRadius: 12,
    padding: "2.5rem 2rem",
    display: "flex",
    flexDirection: "column",
    gap: 0,
  },
  wordmark: {
    fontSize: "2rem",
    fontWeight: 700,
    letterSpacing: "-0.04em",
    color: "var(--fg)",
    lineHeight: 1,
    marginBottom: "0.35rem",
  },
  tagline: {
    fontSize: "0.7rem",
    letterSpacing: "0.22em",
    textTransform: "uppercase",
    color: "var(--muted)",
    fontFamily: "var(--font-mono)",
    marginBottom: 0,
  },
  divider: {
    height: 1,
    background: "#1e1e1e",
    margin: "1.75rem 0",
  },
  form: {
    display: "flex",
    flexDirection: "column",
    gap: "0.5rem",
  },
  label: {
    fontSize: "0.7rem",
    letterSpacing: "0.12em",
    textTransform: "uppercase",
    color: "var(--muted)",
    fontFamily: "var(--font-mono)",
    marginBottom: "0.15rem",
    marginTop: "0.75rem",
  },
  input: {
    width: "100%",
    background: "#0a0a0a",
    border: "1px solid #2a2a2a",
    borderRadius: 6,
    padding: "0.65rem 0.85rem",
    color: "var(--fg)",
    fontSize: "0.9rem",
    fontFamily: "inherit",
    outline: "none",
    transition: "border-color 0.15s",
  },
  error: {
    marginTop: "0.5rem",
    fontSize: "0.78rem",
    color: "#ef4444",
    fontFamily: "var(--font-mono)",
    letterSpacing: "0.02em",
  },
  button: {
    marginTop: "1.5rem",
    width: "100%",
    padding: "0.75rem 1rem",
    background: "var(--accent)",
    color: "#0a0a0a",
    border: "none",
    borderRadius: 6,
    fontSize: "0.85rem",
    fontWeight: 700,
    letterSpacing: "0.06em",
    textTransform: "uppercase",
    fontFamily: "var(--font-mono)",
    transition: "opacity 0.15s, transform 0.1s",
  },
};
