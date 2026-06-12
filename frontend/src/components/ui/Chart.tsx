"use client";

import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  Brush,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { chartPalette, color, font } from "../../theme/tokens";

type Series = { key: string; label?: string; color?: string };

const axisStyle = { fontSize: 10, fill: color.faint, fontFamily: font.mono };
const tooltipStyle = {
  background: color.surface2,
  border: `1px solid ${color.borderStrong}`,
  borderRadius: 8,
  fontSize: 12,
};

/** Line chart — one or more series, token-styled grid/axes/tooltip.
 *  `brush` adds a drag-to-zoom sliding window (client-side only);
 *  `brushStart` sets how many trailing points are shown initially. */
export function LineChartView({
  data,
  series,
  xKey = "x",
  height = 160,
  showAxes = false,
  brush = false,
  brushStart,
}: {
  data: Record<string, number | string>[];
  series: Series[];
  xKey?: string;
  height?: number;
  showAxes?: boolean;
  brush?: boolean;
  brushStart?: number;
}): React.JSX.Element {
  const startIndex = brush && brushStart ? Math.max(0, data.length - brushStart) : undefined;
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
        {showAxes && <CartesianGrid stroke={color.border} strokeDasharray="2 4" vertical={false} />}
        <XAxis dataKey={xKey} hide={!showAxes} tick={axisStyle} stroke={color.border} />
        <YAxis hide={!showAxes} tick={axisStyle} stroke={color.border} domain={["auto", "auto"]} />
        <Tooltip contentStyle={tooltipStyle} labelStyle={{ color: color.muted }} />
        {series.map((s, i) => (
          <Line
            key={s.key}
            type="monotone"
            dataKey={s.key}
            name={s.label ?? s.key}
            stroke={s.color ?? chartPalette[i % chartPalette.length]}
            strokeWidth={1.6}
            dot={false}
          />
        ))}
        {brush && (
          <Brush
            dataKey={xKey}
            height={20}
            travellerWidth={8}
            startIndex={startIndex}
            stroke={color.borderStrong}
            fill={color.surface2}
            tickFormatter={() => ""}
          />
        )}
      </LineChart>
    </ResponsiveContainer>
  );
}

/** Filled area sparkline — single series, minimal chrome. */
export function Sparkline({
  data,
  dataKey = "v",
  height = 120,
  stroke = color.hue,
}: {
  data: Record<string, number | string>[];
  dataKey?: string;
  height?: number;
  stroke?: string;
}): React.JSX.Element {
  const gid = `sl-${dataKey}-${stroke.replace("#", "")}`;
  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={data} margin={{ top: 4, right: 0, bottom: 0, left: 0 }}>
        <defs>
          <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={stroke} stopOpacity={0.25} />
            <stop offset="100%" stopColor={stroke} stopOpacity={0} />
          </linearGradient>
        </defs>
        <Tooltip contentStyle={tooltipStyle} labelStyle={{ color: color.muted }} />
        <Area
          type="monotone"
          dataKey={dataKey}
          stroke={stroke}
          strokeWidth={1.6}
          fill={`url(#${gid})`}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}

/** Bar chart — one or more series. */
export function BarChartView({
  data,
  series,
  xKey = "x",
  height = 200,
}: {
  data: Record<string, number | string>[];
  series: Series[];
  xKey?: string;
  height?: number;
}): React.JSX.Element {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
        <CartesianGrid stroke={color.border} strokeDasharray="2 4" vertical={false} />
        <XAxis dataKey={xKey} tick={axisStyle} stroke={color.border} />
        <YAxis tick={axisStyle} stroke={color.border} />
        <Tooltip
          contentStyle={tooltipStyle}
          labelStyle={{ color: color.muted }}
          cursor={{ fill: color.surface2 }}
        />
        {series.map((s, i) => (
          <Bar
            key={s.key}
            dataKey={s.key}
            name={s.label ?? s.key}
            fill={s.color ?? chartPalette[i % chartPalette.length]}
            radius={[2, 2, 0, 0]}
          />
        ))}
      </BarChart>
    </ResponsiveContainer>
  );
}
