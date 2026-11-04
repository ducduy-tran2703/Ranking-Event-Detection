import { Link, useNavigate, useParams } from "react-router";
import { useEvent, useRunInfo } from "../api/queries";
import { Kpi } from "../components/Card";
import { HourlySeries } from "../components/charts";
import { EventErrorBox, EventNotice, NameSourceBadge } from "../components/EventBits";
import { SourceBadge } from "../components/SourceBadge";
import { Loading } from "../components/Status";
import { fmtDateTime, fmtInt } from "../lib/format";
import { fmtHourLong, fmtHourShort, fmtScore } from "../lib/vntime";

/** "2026-09-20T00:00:00+07:00" → "20/09" (ngày theo giờ VN, đúng chuỗi API trả). */
const fmtDay = (iso: string) => `${iso.slice(8, 10)}/${iso.slice(5, 7)}`;

export function EventDetailPage() {
  const { eventId = "" } = useParams();
  const navigate = useNavigate();
  const { data, isPending, error } = useEvent(eventId);

  return (
    <>
      <EventNotice />
      <button className="ghost" onClick={() => navigate(-1)}>‹ Quay lại</button>
      {isPending && <Loading />}
      {error && <EventErrorBox error={error} />}
      {data && <EventBody data={data} />}
    </>
  );
}

function EventBody({ data }: { data: NonNullable<ReturnType<typeof useEvent>["data"]> }) {
  const run = useRunInfo();
  const trendRange = run.data
    ? `${fmtDay(run.data.xu_huong_tu)}–${fmtDay(run.data.xu_huong_den)}`
    : "khoảng tính xu hướng";
  const series = data.chuoi.map((p) => ({ gio: fmtHourShort(p.t), so_bai: p.so_bai, diem: p.diem }));
  const top = data.chuoi.filter((p) => p.hang != null);
  const bestRank = top.length ? Math.min(...top.map((p) => p.hang!)) : null;

  return (
    <article className="event-detail">
      <h1>{data.ten} <NameSourceBadge source={data.nguon_ten} /></h1>
      {data.ten_bi_an && (
        <p className="badge-line warn-text">
          Tên mô hình của sự kiện này đang ẩn (cửa sổ tập test đặt tên) — đang hiển thị tiêu đề bài đại diện.
        </p>
      )}
      <div className="meta">
        {fmtDateTime(data.first_seen)} → {fmtDateTime(data.last_seen)} · <code>{data.event_id}</code>
      </div>

      <div className="kpis">
        <Kpi label="Bài báo" value={fmtInt(data.size)} />
        <Kpi label="Báo đưa tin" value={String(data.n_sources)} />
        <Kpi label="Tổng điểm xu hướng" value={fmtScore(data.tong_diem)} note={`Σ điểm theo giờ (${trendRange})`} />
        <Kpi label="Điểm cao nhất" value={fmtScore(data.diem_cao_nhat)}
             note={data.luc_cao_nhat ? `lúc ${fmtHourLong(data.luc_cao_nhat)}` : undefined} />
        <Kpi label="Giờ trong top 10" value={String(data.so_gio_trong_top10)}
             note={bestRank ? `hạng cao nhất: ${bestRank}` : "chưa vào bảng top 20"} />
      </div>

      <section className="card">
        <div className="card-head">
          <div>
            <h2>Số bài theo giờ</h2>
            <p className="muted hint">Số bài của sự kiện đăng trong mỗi giờ (giờ Việt Nam).</p>
          </div>
        </div>
        <HourlySeries data={series} xKey="gio" yKey="so_bai" label="Số bài" kind="bar" syncId="ev" />
      </section>
      <section className="card">
        <div className="card-head">
          <div>
            <h2>Điểm xu hướng theo giờ</h2>
            <p className="muted hint">
              Tính lại cho riêng sự kiện bằng đúng công thức và tham số của lần chạy (t2: số báo hiệu dụng × log(1 +
              vận tốc phân rã nửa đời 3 giờ / mức nền giờ)); bằng 0 khi không có bài nào trong 3 giờ gần nhất.
              Chưa được đánh giá.
            </p>
          </div>
        </div>
        <HourlySeries data={series} xKey="gio" yKey="diem" label="Điểm" kind="line" syncId="ev" decimals={2} />
        {data.chuoi_bi_cat && <p className="muted small">Sự kiện kéo dài — chỉ vẽ phần đầu.</p>}
      </section>

      <div className="grid2">
        <section className="card">
          <div className="card-head"><h2>Các báo</h2></div>
          <div className="chips">
            {data.sources.map((s) => (
              <span key={s.source} className="chip"><SourceBadge source={s.source} /> {s.n} bài</span>
            ))}
          </div>
          {data.chuyen_muc.length > 0 && (
            <p className="muted small">Chuyên mục: {data.chuyen_muc.map((c) => `${c.category} (${c.n})`).join(", ")}</p>
          )}
        </section>
        <section className="card">
          <div className="card-head"><h2>Bài đại diện (medoid)</h2></div>
          <p>{data.medoid_title}</p>
          <p className="muted small">Bài gần tâm cụm nhất; tên sự kiện rơi về tiêu đề này khi tên mô hình bị loại.</p>
        </section>
      </div>

      <section className="card">
        <div className="card-head"><h2>{fmtInt(data.bai.length)} bài trong sự kiện</h2></div>
        <ul className="event-articles">
          {data.bai.map((a) => {
            const safeUrl = a.url && /^https?:\/\//i.test(a.url) ? a.url : undefined;
            return (
              <li key={a.article_id}>
                <div className="meta">
                  {fmtDateTime(a.published_at)} · <SourceBadge source={a.source} />
                  {a.category && <> · {a.category}</>}
                  {a.is_medoid && <> · <span className="badge neutral">medoid</span></>}
                </div>
                <Link to={`/articles/${a.article_id}`}>{a.title || "(không có tiêu đề)"}</Link>
                {safeUrl && (
                  <> {" "}<a className="small" href={safeUrl} target="_blank" rel="noopener noreferrer">bài gốc ↗</a></>
                )}
              </li>
            );
          })}
        </ul>
      </section>
    </article>
  );
}
