"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "../../context/AuthContext";
import { apiFetch } from "../../lib/api";
import { Badge, Button, Card, PageShell, SectionTitle } from "../../components/ui";
import { color, font, space } from "../../theme/tokens";

type Pillars = {
  value: number | null;
  quality: number | null;
  growth: number | null;
  momentum: number | null;
  analyst: number | null;
  macro_fit: number | null;
};
type Item = {
  symbol: string;
  name: string | null;
  sector: string | null;
  composite: number | null;
  pillars: Pillars;
  coverage: number;
  candidate: string;
  rank: number | null;
  price: number | null;
  reasons: string[];
};
type Page = { as_of: string | null; total: number; items: Item[]; disclaimer: string };
type Status = {
  last_score_date: string | null;
  scored: number;
  universe_count: number;
  running: boolean;
};

const SECTORS = [
  "Information Technology",
  "Financials",
  "Health Care",
  "Consumer Discretionary",
  "Communication Services",
  "Industrials",
  "Consumer Staples",
  "Energy",
  "Utilities",
  "Real Estate",
  "Materials",
];
const CANDIDATES = ["strong_buy", "buy", "hold", "sell", "strong_sell"];
const PILLAR_KEYS: (keyof Pillars)[] = [
  "value",
  "quality",
  "growth",
  "momentum",
  "analyst",
  "macro_fit",
];
const PILLAR_LABEL: Record<string, string> = {
  value: "VAL",
  quality: "QLT",
  growth: "GRW",
  momentum: "MOM",
  analyst: "ANL",
  macro_fit: "MAC",
};

function candidateTone(c: string): string {
  if (c === "strong_buy") return color.up;
  if (c === "buy") return color.hue;
  if (c === "sell") return color.warn;
  if (c === "strong_sell") return color.down;
  return color.muted;
}

function Bar({ v }: { v: number | null }): React.JSX.Element {
  return (
    <div style={{ width: 46 }}>
      <div style={{ height: 4, background: color.surface2, borderRadius: 2 }}>
        <div
          style={{
            height: 4,
            width: `${v ?? 0}%`,
            maxWidth: "100%",
            background:
              v == null ? "transparent" : v >= 60 ? color.up : v < 40 ? color.down : color.muted,
            borderRadius: 2,
          }}
        />
      </div>
    </div>
  );
}

export default function DiscoverPage(): React.JSX.Element {
  const router = useRouter();
  const { user, loading: authLoading } = useAuth();
  const [page, setPage] = useState<Page | null>(null);
  const [status, setStatus] = useState<Status | null>(null);
  const [sector, setSector] = useState("");
  const [candidate, setCandidate] = useState("");
  const [offset, setOffset] = useState(0);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const limit = 50;

  useEffect(() => {
    if (!authLoading && !user) router.replace("/login");
  }, [authLoading, user, router]);

  const load = useCallback(async (): Promise<void> => {
    try {
      const qs = new URLSearchParams({
        limit: String(limit),
        offset: String(offset),
        sort: "rank",
        dir: "asc",
      });
      if (sector) qs.set("sector", sector);
      if (candidate) qs.set("candidate", candidate);
      const [sRes, stRes] = await Promise.all([
        apiFetch(`/screener/scores?${qs}`),
        apiFetch("/screener/status"),
      ]);
      setPage(sRes.ok ? ((await sRes.json()) as Page) : null);
      setStatus(stRes.ok ? ((await stRes.json()) as Status) : null);
      if (!sRes.ok) setError(`Failed to load scores (${sRes.status}).`);
    } catch {
      setError("Failed to load screener data.");
    }
  }, [sector, candidate, offset]);

  useEffect(() => {
    void load();
  }, [load]);

  async function runScreener(): Promise<void> {
    setBusy(true);
    setError(null);
    try {
      const res = await apiFetch("/screener/run?budget=200", { method: "POST" });
      if (!res.ok) {
        const body = (await res.json().catch(() => ({}))) as { detail?: string };
        throw new Error(body.detail ?? "Run failed");
      }
      setError("Screener started — scores appear as the run completes (a few minutes).");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Run failed.");
    } finally {
      setBusy(false);
    }
  }

  if (authLoading || !user) return <main style={{ background: color.bg, minHeight: "100vh" }} />;

  const selStyle: React.CSSProperties = {
    background: color.surface2,
    border: `1px solid ${color.border}`,
    borderRadius: 6,
    color: color.fg,
    padding: "7px 10px",
    fontSize: 12,
    fontFamily: font.mono,
  };

  return (
    <PageShell
      title="Discover"
      maxWidth={1100}
      right={
        <Button
          variant="ghost"
          disabled={busy || status?.running}
          onClick={() => void runScreener()}
        >
          {status?.running ? "Running…" : "Run screener"}
        </Button>
      }
      subtitle="Ranked buy/sell candidates over the S&P 500 + Nasdaq-100 — nightly composite of value, quality, growth, momentum, analyst and macro fit. Heuristic, educational — not financial advice."
    >
      {error && <div style={{ color: color.warn, fontSize: 13, marginBottom: 12 }}>{error}</div>}

      <Card pad={space[3]} style={{ marginBottom: space[4] }}>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
          <select
            value={sector}
            onChange={(e) => {
              setSector(e.target.value);
              setOffset(0);
            }}
            style={selStyle}
          >
            <option value="">all sectors</option>
            {SECTORS.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
          <select
            value={candidate}
            onChange={(e) => {
              setCandidate(e.target.value);
              setOffset(0);
            }}
            style={selStyle}
          >
            <option value="">all candidates</option>
            {CANDIDATES.map((c) => (
              <option key={c} value={c}>
                {c.replace("_", " ")}
              </option>
            ))}
          </select>
          <span style={{ fontSize: 11, color: color.faint, fontFamily: font.mono }}>
            {status
              ? `${status.universe_count} names · scored ${status.scored} on ${status.last_score_date ?? "—"}`
              : "…"}
          </span>
        </div>
      </Card>

      {!page || page.items.length === 0 ? (
        <Card pad={space[5]}>
          <SectionTitle>No scores yet</SectionTitle>
          <div style={{ color: color.muted, fontSize: 13 }}>
            The screener hasn’t produced scores{sector || candidate ? " for these filters" : ""}{" "}
            yet.
            {!sector && !candidate && " Hit “Run screener” to score the universe now (admin)."}
          </div>
        </Card>
      ) : (
        <Card pad={space[4]}>
          <div style={{ overflowX: "auto" }}>
            <table
              style={{
                width: "100%",
                borderCollapse: "collapse",
                fontSize: 12,
                fontFamily: font.mono,
              }}
            >
              <thead>
                <tr style={{ color: color.muted, textAlign: "left" }}>
                  <th style={{ padding: 6 }}>#</th>
                  <th style={{ padding: 6 }}>Symbol</th>
                  <th style={{ padding: 6, textAlign: "right" }}>Comp</th>
                  {PILLAR_KEYS.map((k) => (
                    <th key={k} style={{ padding: 6, fontSize: 10 }}>
                      {PILLAR_LABEL[k]}
                    </th>
                  ))}
                  <th style={{ padding: 6 }}>Candidate</th>
                  <th style={{ padding: 6, textAlign: "right" }}>Cov</th>
                  <th style={{ padding: 6, textAlign: "right" }}>Price</th>
                </tr>
              </thead>
              <tbody>
                {page.items.map((it) => (
                  <>
                    <tr
                      key={it.symbol}
                      onClick={() => setExpanded(expanded === it.symbol ? null : it.symbol)}
                      style={{ borderTop: `1px solid ${color.border}`, cursor: "pointer" }}
                    >
                      <td style={{ padding: 6, color: color.faint }}>{it.rank ?? "—"}</td>
                      <td style={{ padding: 6 }}>
                        <span style={{ fontWeight: 700 }}>{it.symbol}</span>
                        <span style={{ color: color.faint, marginLeft: 8, fontSize: 10 }}>
                          {it.sector ?? ""}
                        </span>
                      </td>
                      <td style={{ padding: 6, textAlign: "right", fontWeight: 700 }}>
                        {it.composite ?? "—"}
                      </td>
                      {PILLAR_KEYS.map((k) => (
                        <td key={k} style={{ padding: 6 }}>
                          <Bar v={it.pillars[k]} />
                        </td>
                      ))}
                      <td style={{ padding: 6 }}>
                        <Badge
                          tone={candidateTone(it.candidate)}
                          filled={it.candidate.startsWith("strong")}
                        >
                          {it.candidate.replace("_", " ")}
                        </Badge>
                      </td>
                      <td style={{ padding: 6, textAlign: "right", color: color.faint }}>
                        {Math.round(it.coverage * 100)}%
                      </td>
                      <td style={{ padding: 6, textAlign: "right" }}>
                        {it.price ? `$${it.price.toFixed(2)}` : "—"}
                      </td>
                    </tr>
                    {expanded === it.symbol && (
                      <tr key={`${it.symbol}-x`} style={{ background: color.surface2 }}>
                        <td colSpan={11} style={{ padding: "8px 12px" }}>
                          {it.reasons.length ? (
                            it.reasons.map((r, i) => (
                              <div
                                key={i}
                                style={{ fontSize: 11, color: color.muted, lineHeight: 1.7 }}
                              >
                                · {r}
                              </div>
                            ))
                          ) : (
                            <span style={{ fontSize: 11, color: color.faint }}>
                              no reasons recorded
                            </span>
                          )}
                        </td>
                      </tr>
                    )}
                  </>
                ))}
              </tbody>
            </table>
          </div>
          <div style={{ display: "flex", gap: 8, marginTop: space[3], alignItems: "center" }}>
            <Button
              variant="ghost"
              disabled={offset === 0}
              onClick={() => setOffset(Math.max(0, offset - limit))}
            >
              ← Prev
            </Button>
            <span style={{ fontSize: 11, color: color.faint, fontFamily: font.mono }}>
              {offset + 1}–{Math.min(offset + limit, page.total)} of {page.total}
            </span>
            <Button
              variant="ghost"
              disabled={offset + limit >= page.total}
              onClick={() => setOffset(offset + limit)}
            >
              Next →
            </Button>
          </div>
        </Card>
      )}
      <div style={{ color: color.faint, fontSize: 10, marginTop: space[4] }}>
        {page?.disclaimer}
      </div>
    </PageShell>
  );
}
