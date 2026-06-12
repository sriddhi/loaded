"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "../../context/AuthContext";
import { apiFetch } from "../../lib/api";
import { Badge, Button, Card, PageShell, SectionTitle, Stat } from "../../components/ui";
import { color, font, space } from "../../theme/tokens";

type Portfolio = {
  id: number;
  name: string;
  kind: string;
  cash: number;
  holdings_count: number;
  equity_value: number | null;
  total_value: number | null;
  unrealized_pnl: number | null;
  realized_pnl: number | null;
  last_synced_at: string | null;
};

const usd = (v: number | null | undefined): string =>
  v == null ? "—" : v.toLocaleString("en-US", { style: "currency", currency: "USD" });

export default function PortfolioListPage(): React.JSX.Element {
  const router = useRouter();
  const { user, loading: authLoading } = useAuth();
  const [items, setItems] = useState<Portfolio[] | null>(null);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!authLoading && !user) router.replace("/login");
  }, [authLoading, user, router]);

  const load = useCallback(async (): Promise<void> => {
    try {
      const res = await apiFetch("/portfolio");
      setItems(res.ok ? ((await res.json()) as Portfolio[]) : []);
    } catch {
      setItems([]);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function create(e: React.FormEvent): Promise<void> {
    e.preventDefault();
    if (!name.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const res = await apiFetch("/portfolio", {
        method: "POST",
        body: JSON.stringify({ name: name.trim() }),
      });
      if (!res.ok) {
        const body = (await res.json().catch(() => ({}))) as { detail?: string };
        throw new Error(body.detail ?? "Could not create portfolio");
      }
      setName("");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Create failed.");
    } finally {
      setBusy(false);
    }
  }

  async function syncAlpaca(): Promise<void> {
    setBusy(true);
    setError(null);
    try {
      const res = await apiFetch("/portfolio/sync/alpaca", { method: "POST" });
      if (!res.ok) {
        const body = (await res.json().catch(() => ({}))) as { detail?: string };
        throw new Error(body.detail ?? "Sync failed");
      }
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sync failed.");
    } finally {
      setBusy(false);
    }
  }

  if (authLoading || !user) return <main style={{ background: color.bg, minHeight: "100vh" }} />;

  const totals = (items ?? []).reduce(
    (acc, p) => ({
      value: acc.value + (p.total_value ?? 0),
      unreal: acc.unreal + (p.unrealized_pnl ?? 0),
      real: acc.real + (p.realized_pnl ?? 0),
    }),
    { value: 0, unreal: 0, real: 0 }
  );

  return (
    <PageShell
      title="Portfolio"
      maxWidth={1100}
      right={
        <Button variant="ghost" disabled={busy} onClick={() => void syncAlpaca()}>
          {busy ? "Working…" : "Sync Alpaca Paper"}
        </Button>
      }
      subtitle="Your portfolios — manual books or synced from the Alpaca paper account. Heuristic, educational — not financial advice."
    >
      {error && <div style={{ color: color.down, fontSize: 13, marginBottom: 12 }}>{error}</div>}

      {/* Aggregate strip */}
      <Card pad={space[4]} style={{ marginBottom: space[5] }}>
        <div style={{ display: "flex", gap: space[6], flexWrap: "wrap" }}>
          <Stat label="Total value" value={usd(totals.value)} />
          <Stat
            label="Unrealized P&L"
            value={usd(totals.unreal)}
            tone={totals.unreal >= 0 ? color.up : color.down}
          />
          <Stat
            label="Realized P&L"
            value={usd(totals.real)}
            tone={totals.real >= 0 ? color.up : color.down}
          />
          <Stat label="Portfolios" value={items?.length ?? "…"} />
        </div>
      </Card>

      {/* Create form */}
      <Card pad={space[4]} style={{ marginBottom: space[5] }}>
        <SectionTitle>New portfolio</SectionTitle>
        <form onSubmit={(e) => void create(e)} style={{ display: "flex", gap: 10 }}>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. Long-term growth"
            style={{
              flex: "0 1 320px",
              background: color.surface2,
              border: `1px solid ${color.border}`,
              borderRadius: 6,
              color: color.fg,
              padding: "8px 12px",
              fontSize: 13,
              fontFamily: "inherit",
            }}
          />
          <Button variant="primary" disabled={busy || !name.trim()}>
            Create
          </Button>
        </form>
      </Card>

      {/* Portfolio cards */}
      {items === null ? (
        <div style={{ color: color.muted, fontSize: 13 }}>Loading…</div>
      ) : items.length === 0 ? (
        <div style={{ color: color.muted, fontSize: 13 }}>
          No portfolios yet — create one above or sync your Alpaca paper account.
        </div>
      ) : (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))",
            gap: space[4],
          }}
        >
          {items.map((p) => (
            <div
              key={p.id}
              onClick={() => router.push(`/portfolio/${p.id}`)}
              style={{ cursor: "pointer" }}
            >
              <Card pad={space[4]}>
                <SectionTitle
                  right={
                    p.kind === "alpaca_paper" ? (
                      <Badge tone={color.hue}>synced</Badge>
                    ) : (
                      <Badge>manual</Badge>
                    )
                  }
                >
                  {p.name}
                </SectionTitle>
                <div style={{ display: "flex", gap: space[5], flexWrap: "wrap" }}>
                  <Stat label="Value" value={usd(p.total_value)} />
                  <Stat
                    label="Unrealized"
                    value={usd(p.unrealized_pnl)}
                    tone={(p.unrealized_pnl ?? 0) >= 0 ? color.up : color.down}
                  />
                  <Stat label="Holdings" value={p.holdings_count} />
                </div>
                {p.last_synced_at && (
                  <div
                    style={{
                      color: color.faint,
                      fontSize: 10,
                      marginTop: 8,
                      fontFamily: font.mono,
                    }}
                  >
                    synced {new Date(p.last_synced_at).toLocaleString()}
                  </div>
                )}
              </Card>
            </div>
          ))}
        </div>
      )}
    </PageShell>
  );
}
