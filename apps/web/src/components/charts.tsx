// Biểu đồ dùng chung. Mọi biểu đồ nhận dữ liệu "rộng" từ lib/pivot.ts và tô màu theo nguồn.
import {
  Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { sourceColor } from "./SourceBadge";

type Row = Record<string, string | number>;
const AXIS = { fontSize: 12, fill: "#8b949e" };
const GRID = "#8b949e33";
const TOOLTIP = {
  contentStyle: { background: "var(--card)", border: "1px solid var(--border)", borderRadius: 8 },
  labelStyle: { color: "var(--text)", fontWeight: 600 },
};

export function StackedBars({ data, xKey, sources, height = 300 }: {
  data: Row[]; xKey: string; sources: string[]; height?: number;
}) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data}>
        <CartesianGrid stroke={GRID} vertical={false} />
        <XAxis dataKey={xKey} tick={AXIS} minTickGap={24} />
        <YAxis tick={AXIS} allowDecimals={false} />
        <Tooltip {...TOOLTIP} />
        <Legend />
        {sources.map((s) => <Bar key={s} dataKey={s} stackId="a" fill={sourceColor(s)} />)}
      </BarChart>
    </ResponsiveContainer>
  );
}

export function GroupedBars({ data, xKey, sources, height = 300 }: {
  data: Row[]; xKey: string; sources: string[]; height?: number;
}) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data}>
        <CartesianGrid stroke={GRID} vertical={false} />
        <XAxis dataKey={xKey} tick={AXIS} />
        <YAxis tick={AXIS} allowDecimals={false} />
        <Tooltip {...TOOLTIP} />
        <Legend />
        {sources.map((s) => <Bar key={s} dataKey={s} fill={sourceColor(s)} />)}
      </BarChart>
    </ResponsiveContainer>
  );
}

export function Lines({ data, xKey, sources, height = 320 }: {
  data: Row[]; xKey: string; sources: string[]; height?: number;
}) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data}>
        <CartesianGrid stroke={GRID} vertical={false} />
        <XAxis dataKey={xKey} tick={AXIS} minTickGap={24} />
        <YAxis tick={AXIS} allowDecimals={false} />
        <Tooltip {...TOOLTIP} />
        <Legend />
        {sources.map((s) => (
          <Line key={s} dataKey={s} stroke={sourceColor(s)} dot={false} strokeWidth={2} />
        ))}
      </LineChart>
    </ResponsiveContainer>
  );
}

export function HorizontalStackedBars({ data, yKey, sources }: {
  data: Row[]; yKey: string; sources: string[];
}) {
  return (
    <ResponsiveContainer width="100%" height={Math.max(240, data.length * 28 + 60)}>
      <BarChart data={data} layout="vertical" margin={{ left: 20 }}>
        <CartesianGrid stroke={GRID} horizontal={false} />
        <XAxis type="number" tick={AXIS} allowDecimals={false} />
        <YAxis type="category" dataKey={yKey} tick={AXIS} width={140} />
        <Tooltip {...TOOLTIP} />
        <Legend />
        {sources.map((s) => <Bar key={s} dataKey={s} stackId="a" fill={sourceColor(s)} />)}
      </BarChart>
    </ResponsiveContainer>
  );
}
