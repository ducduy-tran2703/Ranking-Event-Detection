import { useState } from "react";
import { Link } from "react-router";
import { useMeta, useOverview, useTimeline } from "../api/queries";
import { Card, Kpi, Pct } from "../components/Card";
import { StackedBars } from "../components/charts";
import { SourceBadge } from "../components/SourceBadge";
import { ErrorBox, Loading } from "../components/Status";
import { fmtInt } from "../lib/format";
import { pivot } from "../lib/pivot";

function daysBefore(isoDate: string, days: number): string {
  const d = new Date(`${isoDate}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() - days);
  return d.toISOString().slice(0, 10);
}

const median = (xs: number[]) => {
  if (!xs.length) return 0;
  const s = [...xs].sort((a, b) => a - b);
  const m = Math.floor(s.length / 2);
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
};

export function OverviewPage() {
  const [window, setWindow] = useState<"90" | "all">("90");
  const overview = useOverview();
  const meta = useMeta();
  const maxDate = meta.data?.date_range.max_date;
  const chartFilter = window === "90" && maxDate ? { date_from: daysBefore(maxDate, 89) } : {};
  const chart = useTimeline(chartFilter, "day");
  const allDays = useTimeline({}, "day");

  if (overview.isPending) return <Loading />;
  if (overview.error) return <ErrorBox error={overview.error} />;
  const t = overview.data.total;

  // Độ dày dữ liệu: trung vị số bài mỗi ngày (chỉ tính ngày có bài) của từng nguồn
  const perDay = new Map<string, number[]>();
  for (const r of allDays.data ?? []) perDay.set(r.source, [...(perDay.get(r.source) ?? []), r.n]);

  const { data, sources } = pivot(chart.data ?? [], "bucket");

  return (
    <>
      <h1>Tổng quan</h1>
      <div className="kpis">
        <Kpi label="Tổng số bài" value={fmtInt(t.articles)} />
        <Kpi label="Số nguồn" value={fmtInt(t.sources)} />
        <Kpi label="Số chuyên mục" value={fmtInt(t.categories)} note="tên khác nhau giữa các báo" />
        <Kpi label="Số ngày có dữ liệu" value={fmtInt(t.days)} />
        <Kpi label="Trung vị số từ / bài" value={fmtInt(t.median_words)} />
      </div>

      <Card
        title="Số bài mỗi ngày, theo nguồn"
        hint="Ngày theo giờ Việt Nam. Một cột thấp bất thường có thể là crawler ngừng chạy hôm đó."
        actions={
          <div className="seg">
            <button className={window === "90" ? "active" : ""} onClick={() => setWindow("90")}>90 ngày gần nhất</button>
            <button className={window === "all" ? "active" : ""} onClick={() => setWindow("all")}>Toàn bộ</button>
          </div>
        }
      >
        {chart.error ? <ErrorBox error={chart.error} /> : <StackedBars data={data} xKey="bucket" sources={sources} />}
      </Card>

      <Card title="Theo nguồn" hint="Bấm tên nguồn để xem bài của nguồn đó.">
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Nguồn</th><th className="num">Số bài</th><th>Từ</th><th>Đến</th>
                <th className="num">Số ngày</th>
                <th className="num" title="Chỉ tính những ngày có bài">Trung vị bài/ngày</th>
                <th className="num">Trung vị số từ</th><th className="num">Thiếu tác giả</th>
                <th className="num">Thân bài rỗng</th><th className="num">Quá ngắn</th>
              </tr>
            </thead>
            <tbody>
              {overview.data.per_source.map((s) => {
                const md = median(perDay.get(s.source) ?? []);
                return (
                  <tr key={s.source}>
                    <td><Link to={`/articles?source=${s.source}`}><SourceBadge source={s.source} /></Link></td>
                    <td className="num">{fmtInt(s.articles)}</td>
                    <td>{s.first_published?.slice(0, 10) ?? "—"}</td>
                    <td>{s.last_published?.slice(0, 10) ?? "—"}</td>
                    <td className="num">{fmtInt(s.active_days)}</td>
                    <td className="num">
                      {md < 50 ? <span className="badge bad" title="Báo lớn đăng 200–300 bài/ngày">{md}</span> : md}
                    </td>
                    <td className="num">{fmtInt(s.median_words)}</td>
                    <td className="num"><Pct value={s.pct_missing_author} /></td>
                    <td className="num"><Pct value={s.pct_empty_content} /></td>
                    <td className="num"><Pct value={s.pct_short_content} /></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <p className="muted hint">
          Ô <span className="badge bad">đỏ</span> ở cột "Trung vị bài/ngày": dữ liệu quá thưa để gom sự kiện đa nguồn —
          báo lớn thường đăng 200–300 bài mỗi ngày.
        </p>
      </Card>
    </>
  );
}
