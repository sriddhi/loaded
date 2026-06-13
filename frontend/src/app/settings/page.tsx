"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "../../context/AuthContext";
import { Card, PageShell, SectionTitle } from "../../components/ui";
import { color, space } from "../../theme/tokens";

function Toggle({
  on,
  onChange,
}: {
  on: boolean;
  onChange: (v: boolean) => void;
}): React.JSX.Element {
  return (
    <button
      role="switch"
      aria-checked={on}
      onClick={() => onChange(!on)}
      style={{
        width: 44,
        height: 24,
        borderRadius: 999,
        border: `1px solid ${on ? color.hue : color.border}`,
        background: on ? color.hue : color.surface2,
        position: "relative",
        cursor: "pointer",
        transition: "background .15s, border-color .15s",
        flexShrink: 0,
      }}
    >
      <span
        style={{
          position: "absolute",
          top: 2,
          left: on ? 22 : 2,
          width: 18,
          height: 18,
          borderRadius: "50%",
          background: on ? color.bg : color.fg,
          transition: "left .15s",
        }}
      />
    </button>
  );
}

function Row({
  title,
  desc,
  on,
  onChange,
}: {
  title: string;
  desc: string;
  on: boolean;
  onChange: (v: boolean) => void;
}): React.JSX.Element {
  return (
    <div
      style={{ display: "flex", alignItems: "center", gap: space[4], padding: `${space[3]}px 0` }}
    >
      <div style={{ flex: 1 }}>
        <div style={{ fontSize: 14, fontWeight: 600 }}>{title}</div>
        <div style={{ fontSize: 12, color: color.muted, marginTop: 2 }}>{desc}</div>
      </div>
      <Toggle on={on} onChange={onChange} />
    </div>
  );
}

export default function SettingsPage(): React.JSX.Element {
  const router = useRouter();
  const { user, loading: authLoading, settings, updateSettings } = useAuth();
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!authLoading && !user) router.replace("/login");
  }, [authLoading, user, router]);

  if (authLoading || !user) return <main style={{ background: color.bg, minHeight: "100vh" }} />;

  const explain = settings.metric_explainers !== false;

  async function set(key: string, value: boolean): Promise<void> {
    setSaving(true);
    try {
      await updateSettings({ [key]: value });
    } finally {
      setSaving(false);
    }
  }

  return (
    <PageShell title="Settings" subtitle={`Signed in as ${user.email}`} maxWidth={680}>
      <SectionTitle
        right={
          saving ? <span style={{ fontSize: 11, color: color.muted }}>saving…</span> : undefined
        }
      >
        Display
      </SectionTitle>
      <Card pad={`${space[2]}px ${space[4]}px`}>
        <Row
          title="Metric explanations on hover"
          desc="Show a plain-English definition when you hover a metric (P/E, ROE, EV/EBITDA, …) on the Fundamentals page."
          on={explain}
          onChange={(v) => void set("metric_explainers", v)}
        />
      </Card>
    </PageShell>
  );
}
