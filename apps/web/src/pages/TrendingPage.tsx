import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router";
import type { TrendTimes } from "../api/client";
import { useTrendTimes, useTrending } from "../api/queries";
import { EventErrorBox, EventNotice, NameSourceBadge } from "../components/EventBits";
import { Loading } from "../components/Status";
import { fmtInt } from "../lib/format";
import { fmtHourLong, fmtScore, fromVn, HOUR_MS, parseUrlTime, vnLocal, vnParts } from "../lib/vntime";

const PLAY_MS = 1200; // mỗi giờ dữ liệu hiển thị 1,2 giây khi phát tự động

/**
 * Bảng xu hướng "phát lại": dữ liệu Silver dừng ở 19/09/2026 nên người xem chọn một giờ trong quá khứ và xem
 * top-20 sự kiện nóng NHƯ TẠI GIỜ ĐÓ (đặc trưng chỉ dùng bài đã đăng trước giờ đó). Giờ đang xem nằm trên URL (?t=).
 */
export function TrendingPage() {
  const times = useTrendTimes();
  return (
    <>
      <h1>Xu hướng theo giờ</h1>
      <EventNotice />
      {times.isPending && <Loading />}
      {times.error && <EventErrorBox error={times.error} />}
      {times.data && <Replay times={times.data} />}
    </>
  );
}

function Replay({ times }: { times: TrendTimes }) {
  const [params, setParams] = useSearchParams();
  const [playing, setPlaying] = useState(false);
  const start = Date.parse(times.dau);
  const step = times.buoc_gio * HOUR_MS;
  const n = times.so_moc;
  const tParam = params.get("t");
  const parsed = tParam ? parseUrlTime(tParam) : NaN;
  const curMs = Number.isFinite(parsed) ? parsed : Date.parse(times.mac_dinh);   // không đọc được → mốc mặc định
  const idx = Math.min(n - 1, Math.max(0, Math.floor((curMs - start) / step + 1e-9)));   // làm tròn xuống như API
  const atMs = start + idx * step;
  const trending = useTrending(vnLocal(atMs));

  // replace: phát tự động không đẩy hàng trăm mục vào lịch sử trình duyệt
  const go = useCallback(
    (i: number) => setParams({ t: vnLocal(start + Math.min(n - 1, Math.max(0, i)) * step) }, { replace: true }),
    [setParams, start, step, n],
  );

  // Phát tự động: mỗi lần idx đổi (hoặc bấm Phát/Dừng) đặt MỘT hẹn giờ sang giờ kế tiếp; tới mốc cuối thì dừng.
  useEffect(() => {
    if (!playing) return;
    if (idx >= n - 1) { setPlaying(false); return; }
    const id = window.setTimeout(() => go(idx + 1), PLAY_MS);
    return () => window.clearTimeout(id);
  }, [playing, idx, n, go]);

  const { date, hour } = vnParts(atMs);
  const first = vnParts(start).date;
  const last = vnParts(start + (n - 1) * step).date;
  const data = trending.data;
  const stale = trending.isPlaceholderData;

  return (
    <>
      <section className="card replay">
        <div className="replay-row">
          <button onClick={() => go(idx - 24)} disabled={idx === 0} title="Lùi 24 giờ">« Ngày</button>
          <button onClick={() => go(idx - 1)} disabled={idx === 0}>‹ Giờ trước</button>
          <button className="primary" onClick={() => setPlaying(!playing)} disabled={!playing && idx >= n - 1}>
            {playing ? "❚❚ Dừng" : "▶ Phát"}
          </button>
          <button onClick={() => go(idx + 1)} disabled={idx >= n - 1}>Giờ sau ›</button>
          <button onClick={() => go(idx + 24)} disabled={idx >= n - 1} title="Tiến 24 giờ">Ngày »</button>
          <label>
            Ngày
            <input type="date" value={date} min={first} max={last}
                   onChange={(e) => e.target.value && go(Math.round((fromVn(e.target.value, hour) - start) / step))} />
          </label>
          <label>
            Giờ
            <select value={hour} onChange={(e) => go(Math.round((fromVn(date, Number(e.target.value)) - start) / step))}>
              {Array.from({ length: 24 }, (_, h) => <option key={h} value={h}>{String(h).padStart(2, "0")}:00</option>)}
            </select>
          </label>
          <button className="ghost" onClick={() => { setPlaying(false); setParams({}, { replace: true }); }}
                  title={`Mốc cuối có ít nhất 10 sự kiện: ${fmtHourLong(times.mac_dinh)}`}>
            Về mốc mới nhất
          </button>
        </div>
        <input className="slider" type="range" min={0} max={n - 1} value={idx}
               aria-label="Chọn giờ" onChange={(e) => go(Number(e.target.value))} />
        <ActivityStrip counts={times.so_su_kien} idx={idx} start={start} step={step} onPick={go} />
        <div className="replay-now">
          Đang xem bảng lúc <strong>{fmtHourLong(atMs)}</strong>
          {data && !stale && <> · {data.items.length} sự kiện trên bảng</>}
          {stale && <span className="muted"> · đang tải…</span>}
        </div>
      </section>

      {trending.error && <EventErrorBox error={trending.error} />}
      {trending.isPending && <Loading />}
      {data && data.items.length === 0 && (
        <p className="empty">
          Không có sự kiện nào đủ điều kiện ở giờ này (cần ≥ 2 bài, trong đó ≥ 1 bài trong 3 giờ qua) — thường là
          đêm khuya ít bài. Thử giờ khác hoặc bấm ▶ Phát.
        </p>
      )}
      {data && data.items.length > 0 && (
        <div className="card table-wrap">
          <table className={`trend ${stale ? "is-stale" : ""}`}>
            <thead>
              <tr>
                <th className="num">#</th>
                <th>Sự kiện</th>
                <th className="num" title="Số bài của sự kiện đã đăng tính đến giờ đang xem">Bài</th>
                <th className="num hide-sm" title="Số báo khác nhau đã đưa tin">Báo</th>
                <th className="num" title="Số bài đăng trong 3 giờ gần nhất">3 giờ</th>
                <th className="num" title="Điểm xu hướng t2 (chưa đánh giá)">Điểm</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((r) => (
                <tr key={r.event_id}>
                  <td className="num rank">{r.hang}</td>
                  <td>
                    <Link to={`/events/${r.event_id}`} className="event-name">{r.ten}</Link>{" "}
                    <NameSourceBadge source={r.nguon_ten} />
                    <div className="muted small show-sm">{r.so_bao} báo</div>
                  </td>
                  <td className="num">{fmtInt(r.so_bai_den_t)}</td>
                  <td className="num hide-sm">{r.so_bao}</td>
                  <td className="num">{r.so_bai_3h}</td>
                  <td className="num">{fmtScore(r.score)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

/** Số sự kiện trên bảng ở từng giờ của cả giai đoạn — bấm để nhảy tới giờ đó; vạch màu là giờ đang xem. */
function ActivityStrip({ counts, idx, start, step, onPick }: {
  counts: number[]; idx: number; start: number; step: number; onPick: (i: number) => void;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const max = useMemo(() => Math.max(1, ...counts), [counts]);
  const n = counts.length;
  const at = (e: React.MouseEvent<SVGSVGElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    return Math.min(n - 1, Math.max(0, Math.floor(((e.clientX - r.left) / r.width) * n)));
  };
  const path = counts.map((c, i) => `M${i + 0.5} 30V${30 - (c / max) * 28}`).join("");
  return (
    <div className="strip">
      <svg viewBox={`0 0 ${n} 30`} preserveAspectRatio="none" role="img"
           aria-label="Số sự kiện trên bảng theo từng giờ" onClick={(e) => onPick(at(e))}
           onMouseMove={(e) => setHover(at(e))} onMouseLeave={() => setHover(null)}>
        <path d={path} stroke="var(--muted)" strokeOpacity={0.55} strokeWidth={1} vectorEffect="non-scaling-stroke" />
        {hover != null && <rect x={hover} y={0} width={1} height={30} fill="var(--text)" opacity={0.15} />}
        <rect x={idx} y={0} width={1} height={30} fill="var(--accent)" />
      </svg>
      <div className="muted small strip-label">
        {hover != null
          ? <>{fmtHourLong(start + hover * step)} · {counts[hover]} sự kiện — bấm để xem</>
          : <>Số sự kiện trên bảng theo giờ, {fmtHourLong(start)} → {fmtHourLong(start + (n - 1) * step)}</>}
      </div>
    </div>
  );
}
