import { sourceMeta } from "../lib/sources";

const PALETTE = ["#2563eb", "#dc2626", "#16a34a", "#d97706", "#7c3aed", "#0891b2", "#db2777", "#65a30d"];

/** Mỗi nguồn luôn một màu cố định, ở mọi biểu đồ của Kho dữ liệu. */
export function sourceColor(source: string): string {
  let h = 0;
  for (const ch of source) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return PALETTE[h % PALETTE.length];
}

export function SourceBadge({ source }: { source: string }) {
  return (
    <span className="source">
      <span className="dot" style={{ background: sourceColor(source) }} />
      {source}
    </span>
  );
}

/** Ô chữ viết tắt của báo (thiết kế EventDetail) + tên + số bài. */
export function SourceChip({ source, n }: { source: string; n?: number }) {
  const m = sourceMeta(source);
  return (
    <span className="src-chip">
      <span className="src-ini" style={{ background: m.bg, color: m.fg }} aria-hidden="true">{m.ini}</span>
      {m.name}{n != null && <b className="tnum">{n}</b>}
    </span>
  );
}
