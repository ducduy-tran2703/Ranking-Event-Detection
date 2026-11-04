// Biểu đồ dùng chung. Mọi biểu đồ nhận dữ liệu "rộng" từ lib/pivot.ts và tô màu theo nguồn.
import {
  Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { sourceColor } from "./SourceBadge";

type Row = Record<string, string | number>;
const AXIS = { fontSize: 12, fill: "var(--muted)" };
const GRID = "var(--border)";
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

/**
 * Một chuỗi theo giờ (trang chi tiết sự kiện). Hai đại lượng khác thang đo (số bài, điểm) vẽ HAI biểu đồ
 * chung trục thời gian và chung `syncId` (di chuột ở biểu đồ này hiện cả mốc ở biểu đồ kia) — không dùng hai trục y.
 */
export function HourlySeries({ data, xKey, yKey, label, kind, syncId, height = 200, decimals = 0 }: {
  data: Row[]; xKey: string; yKey: string; label: string; kind: "bar" | "line"; syncId?: string;
  height?: number; decimals?: number;
}) {
  const fmt = (v: unknown) =>
    typeof v === "number" ? v.toLocaleString("vi-VN", { maximumFractionDigits: decimals }) : String(v);
  const common = (
    <>
      <CartesianGrid stroke={GRID} vertical={false} />
      <XAxis dataKey={xKey} tick={AXIS} minTickGap={28} />
      <YAxis tick={AXIS} allowDecimals={decimals > 0} width={40} />
      <Tooltip {...TOOLTIP} formatter={(v) => [fmt(v), label]} />
    </>
  );
  return (
    <ResponsiveContainer width="100%" height={height}>
      {kind === "bar" ? (
        <BarChart data={data} syncId={syncId}>
          {common}
          <Bar dataKey={yKey} name={label} fill="var(--accent)" radius={[3, 3, 0, 0]} maxBarSize={18} />
        </BarChart>
      ) : (
        <LineChart data={data} syncId={syncId}>
          {common}
          <Line dataKey={yKey} name={label} stroke="var(--accent)" dot={false} strokeWidth={2}
                type="linear" isAnimationActive={false} />
        </LineChart>
      )}
    </ResponsiveContainer>
  );
}
