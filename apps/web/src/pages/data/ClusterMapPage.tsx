import { useMemo, useState, type CSSProperties } from "react";
import { Link, useSearchParams } from "react-router";
import { ApiError, type EventMap } from "../../api/client";
import { useEventMap, useEventStats, useMapDates, useRunInfo } from "../../api/queries";
import { EventErrorBox } from "../../components/EventBits";
import { Loading } from "../../components/Status";
import { ddmm, ddmmyyyy, fmtInt } from "../../lib/format";
import { eventHref } from "../../lib/routes";
import { useTitle } from "../../lib/useTitle";
import { DataNav } from "./DataNav";

const COLORS = ["#0369A1", "#EA580C", "#059669", "#9333EA", "#38BDF8", "#DB2777", "#CA8A04", "#DC2626"];
const delay = (s: number): CSSProperties => ({ animationDelay: `${s}s` });

/**
 * Trực quan gom cụm (thiết kế ClusterViz): bản đồ t-SNE các bài của một ngày (/api/events/map, sinh trước bằng
 * `python -m eventrank.evaluation.event_map --date …`) + phân bố kích thước sự kiện và số báo (/api/events/stats).
 * Ngày nằm trong cửa sổ ẩn tên không có bản đồ (API trả 403). Ngày đang xem nằm trên URL (?ngay=YYYY-MM-DD).
 */
export function ClusterMapPage() {
  useTitle("Trực quan gom cụm");
  const [params, setParams] = useSearchParams();
  const dates = useMapDates();
  const date = params.get("ngay") ?? dates.data?.mac_dinh ?? undefined;
  const run = useRunInfo();
  const win = run.data?.cua_so_an_ten;
  // ngày thuộc cửa sổ ẩn tên: không gọi API (server sẽ trả 403), báo ngay
  const hidden = !!(date && win && date >= win.tu_ngay && date <= win.den_ngay);
  const map = useEventMap(date, !hidden && !run.isPending);
  const stats = useEventStats();
  const data = map.data;

  return (
    <div className="page">
      <DataNav />
      <div className="page-head rise">
        <div className="row-between" style={{ alignItems: "flex-end" }}>
          <h1>Bản đồ bài báo{data && !hidden ? <> ngày {ddmmyyyy(data.date)}</> : ""}</h1>
          {dates.data && dates.data.dates.length > 0 && (
            <label className="filters" style={{ flexDirection: "column", alignItems: "stretch", gap: 4, fontSize: 13, fontWeight: 600, color: "var(--muted)" }}>
              Ngày có bản đồ
              <select className="field" value={data?.date ?? date ?? ""} onChange={(e) => setParams({ ngay: e.target.value }, { replace: true })}>
                {dates.data.dates.map((d) => <option key={d} value={d}>{ddmmyyyy(d)}</option>)}
              </select>
            </label>
          )}
        </div>
        {data && (
          <p>Mỗi chấm là một bài trong {fmtInt(data.n_bai)} bài đăng hôm đó. Hai chấm càng gần thì nội dung càng giống nhau theo
            mô hình embedding. Chấm màu thuộc {data.su_kien.length} sự kiện lớn nhất trong ngày; bấm vào chú thích để làm nổi một sự kiện.</p>
        )}
      </div>

      {hidden && <HiddenDate />}
      {!hidden && (dates.isPending || map.isPending) && !map.error && <Loading lines={4} h={60} label="Đang tải bản đồ…" />}
      {dates.error && <EventErrorBox error={dates.error} onRetry={() => dates.refetch()} />}
      {map.error && <MapError error={map.error} />}
      {data && !hidden && <MapView key={data.date} data={data} stale={map.isPlaceholderData} />}

      <div className="grid-2">
        <section aria-labelledby="h-size" className="card pad-sm rise" style={delay(.25)}>
          <h2 id="h-size" style={{ fontSize: 16 }}>
            Kích thước sự kiện{stats.data ? `, toàn bộ ${fmtInt(stats.data.n_su_kien)} sự kiện` : ""}
          </h2>
          <p className="hint" style={{ marginBottom: 12 }}>Số bài trong mỗi sự kiện. Phần lớn bài chỉ một báo đưa nên đứng một mình.</p>
          {stats.isPending && <Loading lines={4} />}
          {stats.error && <EventErrorBox error={stats.error} onRetry={() => stats.refetch()} />}
          {stats.data && <Dist rows={stats.data.kich_thuoc.map((b) => [b.nhan, b.n])} label="sự kiện" />}
        </section>
        <section aria-labelledby="h-srcs" className="card pad-sm rise" style={delay(.3)}>
          <h2 id="h-srcs" style={{ fontSize: 16 }}>Số báo cùng đưa tin</h2>
          <p className="hint" style={{ marginBottom: 12 }}>
            Trong {stats.data ? fmtInt(stats.data.n_su_kien_nhieu_bai) : "các"} sự kiện có từ 2 bài trở lên. Sự kiện nhiều báo đưa
            là ứng viên hàng đầu cho bảng xu hướng.
          </p>
          {stats.isPending && <Loading lines={4} />}
          {stats.data && <Dist rows={stats.data.so_bao.map((b) => [`${b.so_bao}${b.so_bao === 6 ? "+" : ""} báo`, b.n])} label="sự kiện" />}
        </section>
      </div>
    </div>
  );
}

function NoMap() {
  return (
    <div className="error-box info" role="status">
      <strong>Chưa có bản đồ nào cho lần chạy đang phục vụ.</strong>
      <span className="detail">
        Người quản trị chạy <code>uv run --group embed python -m eventrank.evaluation.event_map --date 2026-09-10</code> (cần
        vector đệm trong <code>data/events/cache/</code>), rồi tải lại trang.
      </span>
    </div>
  );
}

const HIDDEN_HINT = "Ngày thuộc cửa sổ của tập test đặt tên — tên sự kiện đang được giữ kín. Chọn ngày khác trong danh sách.";

function HiddenDate() {
  return (
    <div className="error-box" role="alert" data-testid="map-hidden">
      <strong>Ngày này không có bản đồ.</strong>
      <span className="detail">{HIDDEN_HINT}</span>
    </div>
  );
}

function MapError({ error }: { error: unknown }) {
  if (error instanceof ApiError && error.status === 403) return <HiddenDate />;
  if (error instanceof ApiError && error.status === 404) return <NoMap />;
  return <EventErrorBox error={error} />;
}

function MapView({ data, stale }: { data: EventMap; stale: boolean }) {
  const [focus, setFocus] = useState<number | null>(null);
  // chấm xám vẽ trước, chấm màu sau để nằm trên
  const pts = useMemo(() => [...data.diem].sort((a, b) => Number(a[2] >= 0) - Number(b[2] >= 0)), [data.diem]);
  const names = new Map(data.su_kien.map((e) => [e.k, e.ten]));
  return (
    <div className="split" style={{ opacity: stale ? .6 : 1 }}>
      <section aria-labelledby="h-map" className="card pad-sm rise main" style={{ ...delay(.1), display: "block" }}>
        <h2 id="h-map" className="sr-only">Bản đồ hai chiều</h2>
        <div className="map-box" role="img" data-testid="cluster-map"
             aria-label={`Bản đồ t-SNE ${data.n_bai} bài ngày ${ddmm(data.date)}; các bài cùng sự kiện tụ thành cụm nhỏ. `
               + `${data.su_kien.length} sự kiện lớn nhất được tô màu.`}>
          {pts.map(([x, y, k], i) => {
            const colored = k >= 0;
            const dim = focus !== null && k !== focus;
            const s = colored ? 9 : 6;
            return (
              <span key={i} className="pt pop" title={colored ? names.get(k) : undefined}
                    style={{ left: `${3 + x * .94}%`, top: `${3 + y * .94}%`, width: s, height: s,
                             background: colored ? COLORS[k % COLORS.length] : "#CBD5E1",
                             opacity: dim ? (colored ? .15 : .25) : (colored ? .95 : .7),
                             animationDelay: `${(Math.min(i, 800) * .0012).toFixed(3)}s` }} />
            );
          })}
        </div>
        <p className="hint" style={{ marginTop: 10 }}>
          Chiếu 768 chiều xuống 2 chiều bằng t-SNE (perplexity {String(data.tsne.perplexity ?? 25)}, cosine), chỉ để nhìn: khoảng cách
          giữa các cụm xa nhau không có nghĩa chính xác. Vector từ <code>{data.model_version}</code>, nhóm sự kiện từ lần chạy{" "}
          <code>{data.run_id}</code>.{data.khac_run && " Bản đồ sinh từ một lần chạy khác lần đang phục vụ — màu có thể thiếu."}
        </p>
      </section>

      <aside className="side" style={{ gap: 12 }}>
        <section aria-labelledby="h-leg" className="card rise" style={{ ...delay(.15), padding: 14 }}>
          <div className="row-between" style={{ marginBottom: 8, gap: 8 }}>
            <h2 id="h-leg" style={{ fontSize: 15 }}>{data.su_kien.length} sự kiện lớn nhất trong ngày</h2>
            <button type="button" className="link-btn" onClick={() => setFocus(null)} disabled={focus === null}>Hiện tất cả</button>
          </div>
          <ul className="stack" style={{ listStyle: "none", margin: 0, padding: 0, gap: 6 }} data-testid="map-legend">
            {data.su_kien.map((e) => (
              <li key={e.event_id}>
                <button type="button" className="legend-btn" aria-pressed={focus === e.k}
                        onClick={() => setFocus(focus === e.k ? null : e.k)}>
                  <span className="legend-dot" aria-hidden="true" style={{ background: COLORS[e.k % COLORS.length] }} />
                  <span style={{ flex: "1 1 auto" }}>{e.ten}</span>
                  <span className="tnum muted" style={{ fontWeight: 600 }} aria-label={`${e.n} bài trong ngày`}>{e.n}</span>
                </button>
              </li>
            ))}
          </ul>
          {focus !== null && (
            <p className="small" style={{ marginTop: 8 }}>
              <Link to={eventHref(data.su_kien.find((e) => e.k === focus)!.event_id)}>Mở sự kiện đang làm nổi →</Link>
            </p>
          )}
        </section>
        <section aria-labelledby="h-read" className="info-box rise" style={delay(.2)}>
          <h2 id="h-read" style={{ fontSize: 15 }}>Nhìn thấy gì</h2>
          <ul>
            <li>Ngày {ddmm(data.date)} có {fmtInt(data.n_su_kien)} sự kiện; {fmtInt(data.n_su_kien_nhieu_bai)} sự kiện có từ 2 bài
              trở lên trong ngày.</li>
            <li>Các bài cùng sự kiện tụ thành cụm nhỏ; nhiều chấm xám đứng lẻ là bài chỉ một báo đưa.</li>
            <li>Hai cụm màu nằm sát nhau có thể là hai sự kiện của cùng một câu chuyện (đúng định nghĩa sự kiện của đồ án), hoặc
              một sự kiện bị tách đôi.</li>
          </ul>
        </section>
      </aside>
    </div>
  );
}

function Dist({ rows, label }: { rows: [string, number][]; label: string }) {
  const max = Math.max(1, ...rows.map(([, n]) => n));
  return (
    <ul className="hbars compact">
      {rows.map(([l, n]) => (
        <li key={l}>
          <span>{l}</span>
          <span className="track" aria-hidden="true"><span className="grow" style={{ width: `${Math.max(1, Math.round((n / max) * 100))}%` }} /></span>
          <span className="val" aria-label={`${fmtInt(n)} ${label}`}>{fmtInt(n)}</span>
        </li>
      ))}
    </ul>
  );
}
