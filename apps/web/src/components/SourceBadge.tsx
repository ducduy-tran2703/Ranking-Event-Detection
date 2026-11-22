import { sourceMeta } from "../lib/sources";

const PALETTE = ["#22397a", "#8c2a22", "#2f5d3d", "#7a3b12", "#5a3f78", "#2f5a63", "#9a6b12", "#4a4036"];

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
