"use client";

import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { apiFetch } from "../lib/api";

export type UserSettings = Record<string, unknown>;
export type User = {
  id: number;
  email: string;
  role: string;
  is_active: boolean;
  auth_provider?: string | null;
  settings?: UserSettings;
};

type AuthState = {
  user: User | null;
  loading: boolean;
  refresh: () => Promise<void>;
  logout: () => Promise<void>;
  settings: UserSettings;
  updateSettings: (patch: UserSettings) => Promise<void>;
};

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }): React.JSX.Element {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const res = await apiFetch("/auth/me");
      setUser(res.ok ? ((await res.json()) as User) : null);
    } catch {
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, []);

  const logout = useCallback(async () => {
    await apiFetch("/auth/logout", { method: "POST" });
    setUser(null);
  }, []);

  const updateSettings = useCallback(async (patch: UserSettings): Promise<void> => {
    // Optimistic, then persist; the response is the authoritative merged user.
    setUser((u) => (u ? { ...u, settings: { ...(u.settings ?? {}), ...patch } } : u));
    const res = await apiFetch("/auth/settings", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ settings: patch }),
    });
    if (res.ok) setUser((await res.json()) as User);
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return (
    <AuthContext.Provider
      value={{ user, loading, refresh, logout, settings: user?.settings ?? {}, updateSettings }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
