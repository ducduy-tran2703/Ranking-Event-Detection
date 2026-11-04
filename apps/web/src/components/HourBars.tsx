import type { EventPoint } from "../api/client";
import { fmtDec, vnClock } from "../lib/format";

/** Biểu đồ cột theo giờ vẽ bằng div (thiết kế EventDetail): độ nóng hoặc số bài của một sự kiện. */
export function HourBars({ points, kind }: { points: EventPoint[]; kind: "diem" | "so_bai" }) {
  const vals = points.map((p) => (kind === "diem" ? p.diem : p.so_bai));
  const max = Math.max(...vals, 0);
  if (!points.length || max <= 0) {
    return <p className="muted small">Chưa có {kind === "diem" ? "điểm độ nóng" : "bài"} nào trong khoảng này.</p>;
  }
  const fmt = (v: number) => (kind === "diem" ? `điểm ${fmtDec(v)}` : `${v} bài`);
  const peaks = points.filter((_, i) => vals[i] >= max - 1e-9).map((p) => vnClock(p.t));
  const first = vnClock(points[0].t);
  const last = vnClock(points[points.length - 1].t);
  const peakText = `Cao nhất ${kind === "diem" ? fmtDec(max) : `${max} bài`} lúc ${peaks.slice(0, 3).map((c) => c.hhmm).join(", ")}`
    + `${peaks.length > 3 ? "…" : ""} ngày ${peaks[0].ddmm}`;
  const n = points.length;
  return (
    <figure style={{ margin: 0 }}>
      <figcaption className="row-between" style={{ alignItems: "baseline", gap: 10 }}>
        <span className="small muted">
          Từ {first.hhmm} ngày {first.ddmm} đến {last.hhmm} ngày {last.ddmm}.
          {kind === "diem" && " Cột trống: không có bài mới trong 3 giờ trước đó."}
        </span>
        <span className="small" style={{ fontWeight: 600, color: "var(--accent-dark)" }} data-testid="chart-peak">{peakText}</span>
      </figcaption>
      <div className="vchart-scroll" style={{ marginTop: 12 }}>
        <div style={{ minWidth: Math.max(560, n * 9) }}>
          <div className={`vchart${n > 80 ? " thin" : ""}`} role="img"
               aria-label={`Biểu đồ cột ${kind === "diem" ? "điểm độ nóng" : "số bài"} theo giờ. ${peakText}.`}>
            {points.map((p, i) => {
              const c = vnClock(p.t);
              const v = vals[i];
              return (
                <div key={p.t} className={`bar growy${v >= max * .9 ? " hot" : ""}`} title={`${c.ddmm} ${c.hhmm} · ${fmt(v)}`}
                     style={{ height: v ? Math.max(5, Math.round((v / max) * 150)) : 0,
                              animationDelay: `${Math.min(i, 60) * .02}s` }} />
              );
            })}
          </div>
          <div className={`vchart-ticks${n > 80 ? " thin" : ""}`} aria-hidden="true">
            {points.map((p) => {
              const c = vnClock(p.t);
              const every = n > 120 ? 24 : n > 48 ? 12 : 6;
              return <span key={p.t}>{c.hour % every === 0 ? (c.hour === 0 ? c.ddmm : `${c.hour}h`) : ""}</span>;
            })}
          </div>
        </div>
      </div>
    </figure>
  );
}
