"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "../../context/AuthContext";
import { apiFetch } from "../../lib/api";

const ERROR_MESSAGES: Record<string, string> = {
  oauth_denied: "Google sign-in was cancelled.",
  invalid_state: "Sign-in expired — please try again.",
  email_unverified: "Your Google email is not verified.",
  oauth_failed: "Google sign-in failed — please try again.",
  oauth_unconfigured: "Google sign-in isn’t set up yet — use email and password.",
  inactive: "This account is inactive.",
};

export default function LoginPage(): React.JSX.Element {
  const router = useRouter();
  const { user, refresh } = useAuth();
  const [mode, setMode] = useState<"login" | "signup">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [googleEnabled, setGoogleEnabled] = useState(false);

  // Already authenticated → leave the login page.
  useEffect(() => {
    if (user) router.replace("/");
  }, [user, router]);

  // Surface an ?error= code from the OAuth redirect.
  useEffect(() => {
    const code = new URLSearchParams(window.location.search).get("error");
    if (code) setError(ERROR_MESSAGES[code] ?? "Sign-in failed.");
  }, []);

  // Only show the Google button if the backend has OAuth configured.
  useEffect(() => {
    void (async (): Promise<void> => {
      try {
        const res = await apiFetch("/auth/config");
        if (res.ok)
          setGoogleEnabled(
            ((await res.json()) as { google_enabled?: boolean }).google_enabled ?? false
          );
      } catch {
        setGoogleEnabled(false);
      }
    })();
  }, []);

  async function handleSubmit(e: React.FormEvent): Promise<void> {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      if (mode === "signup") {
        const res = await apiFetch("/auth/register", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email, password }),
        });
        if (!res.ok) {
          const body = await res.json().catch(() => ({}));
          throw new Error(body.detail ?? "Registration failed.");
        }
      }
      // Log in (also runs immediately after a successful signup).
      const form = new URLSearchParams({ username: email, password });
      const res = await apiFetch("/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: form.toString(),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail ?? "Invalid credentials.");
      }
      await refresh();
      router.replace("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main
      style={{
        minHeight: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: "#0a0a0a",
        color: "#f5f5f5",
        padding: 24,
      }}
    >
      <div style={{ width: "100%", maxWidth: 380 }}>
        <h1
          style={{
            fontSize: 28,
            fontWeight: 700,
            letterSpacing: "-0.02em",
            marginBottom: 4,
          }}
        >
          Loaded
        </h1>
        <p style={{ color: "#555", marginBottom: 28, fontSize: 14 }}>
          {mode === "login" ? "Sign in to continue" : "Create your account"}
        </p>

        {googleEnabled && (
          <>
            <a
              href="/api/auth/google/login"
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                gap: 10,
                width: "100%",
                padding: "12px 16px",
                background: "#f5f5f5",
                color: "#0a0a0a",
                borderRadius: 8,
                fontWeight: 600,
                fontSize: 14,
                textDecoration: "none",
                boxSizing: "border-box",
              }}
            >
              <GoogleIcon /> Continue with Google
            </a>

            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 12,
                margin: "20px 0",
                color: "#555",
                fontSize: 12,
              }}
            >
              <span style={{ flex: 1, height: 1, background: "#222" }} /> OR{" "}
              <span style={{ flex: 1, height: 1, background: "#222" }} />
            </div>
          </>
        )}

        <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <input
            type="email"
            required
            placeholder="you@example.com"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            style={inputStyle}
          />
          <input
            type="password"
            required
            minLength={8}
            placeholder="Password (8+ characters)"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            style={inputStyle}
          />
          {error && <div style={{ color: "#ef4444", fontSize: 13 }}>{error}</div>}
          <button
            type="submit"
            disabled={busy}
            style={{
              padding: "12px 16px",
              background: "#e8ff47",
              color: "#0a0a0a",
              border: "none",
              borderRadius: 8,
              fontWeight: 700,
              fontSize: 14,
              cursor: busy ? "default" : "pointer",
              opacity: busy ? 0.6 : 1,
            }}
          >
            {busy ? "…" : mode === "login" ? "Sign in" : "Sign up"}
          </button>
        </form>

        <p style={{ marginTop: 20, fontSize: 13, color: "#555" }}>
          {mode === "login" ? "No account? " : "Have an account? "}
          <button
            type="button"
            onClick={() => {
              setMode(mode === "login" ? "signup" : "login");
              setError(null);
            }}
            style={{
              background: "none",
              border: "none",
              color: "#e8ff47",
              cursor: "pointer",
              padding: 0,
              fontSize: 13,
            }}
          >
            {mode === "login" ? "Sign up" : "Sign in"}
          </button>
        </p>
      </div>
    </main>
  );
}

const inputStyle: React.CSSProperties = {
  width: "100%",
  background: "#111",
  border: "1px solid #222",
  borderRadius: 8,
  color: "#f5f5f5",
  padding: "12px 14px",
  fontSize: 14,
  outline: "none",
  boxSizing: "border-box",
};

function GoogleIcon(): React.JSX.Element {
  return (
    <svg width="18" height="18" viewBox="0 0 48 48" aria-hidden="true">
      <path
        fill="#EA4335"
        d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"
      />
      <path
        fill="#4285F4"
        d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"
      />
      <path
        fill="#FBBC05"
        d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"
      />
      <path
        fill="#34A853"
        d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"
      />
    </svg>
  );
}
