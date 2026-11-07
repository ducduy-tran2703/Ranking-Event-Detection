const PALETTE = ["#2563eb", "#dc2626", "#16a34a", "#d97706", "#7c3aed", "#0891b2", "#db2777", "#65a30d"];

/** Mỗi nguồn luôn một màu cố định, ở mọi trang. */
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
