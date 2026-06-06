"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { useRouter, usePathname } from "next/navigation";
import { clearTokens, fetchMe, getToken } from "@/lib/auth";

interface User {
  id: number;
  email: string;
  role: string;
}

interface AuthCtx {
  user: User | null;
  token: string | null;
  loading: boolean;
  logout: () => void;
  refresh: () => void;
}

const Ctx = createContext<AuthCtx>({
  user: null,
  token: null,
  loading: true,
  logout: () => {},
  refresh: () => {},
});

export function useAuth() {
  return useContext(Ctx);
}

const PUBLIC = ["/login"];

export default function AuthProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [user, setUser] = useState<User | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const logout = useCallback(() => {
    clearTokens();
    setUser(null);
    setToken(null);
    router.push("/login");
  }, [router]);

  const loadUser = useCallback(async () => {
    const t = getToken();
    if (!t) {
      setLoading(false);
      if (!PUBLIC.includes(pathname)) router.push("/login");
      return;
    }
    try {
      const me = await fetchMe(t);
      setUser(me);
      setToken(t);
    } catch {
      clearTokens();
      router.push("/login");
    } finally {
      setLoading(false);
    }
  }, [pathname, router]);

  useEffect(() => {
    loadUser();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // If on public page, always render (no flicker)
  if (PUBLIC.includes(pathname)) {
    return (
      <Ctx.Provider value={{ user, token, loading, logout, refresh: loadUser }}>
        {children}
      </Ctx.Provider>
    );
  }

  // Protected page: show nothing until auth resolves
  if (loading) {
    return (
      <div
        style={{
          height: "100vh",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: "var(--bg)",
          color: "var(--muted)",
          fontFamily: "var(--font-mono)",
          fontSize: "0.75rem",
          letterSpacing: "0.15em",
        }}
      >
        authenticating...
      </div>
    );
  }

  return (
    <Ctx.Provider value={{ user, token, loading, logout, refresh: loadUser }}>
      {children}
    </Ctx.Provider>
  );
}
