import { useOverview } from "../api/queries";
import { SourceBadge } from "../components/SourceBadge";
import { ErrorBox, Loading } from "../components/Status";

const fmt = (n: number | null | undefined) => (n ?? 0).toLocaleString("vi-VN");

export function OverviewPage() {
  const { data, isPending, error } = useOverview();
  if (isPending) return <Loading />;
  if (error) return <ErrorBox error={error} />;

  const t = data.total;
  const kpis: [string, string][] = [
    ["Tổng số bài", fmt(t.articles)],
    ["Số nguồn", fmt(t.sources)],
    ["Số chuyên mục", fmt(t.categories)],
    ["Số ngày có dữ liệu", fmt(t.days)],
    ["Trung vị số từ / bài", fmt(t.median_words)],
  ];

  return (
    <>
      <h1>Tổng quan</h1>
      <div className="kpis">
        {kpis.map(([label, value]) => (
          <div className="kpi" key={label}>
            <div className="value">{value}</div>
            <div className="label">{label}</div>
          </div>
        ))}
      </div>
      <div className="card">
        <table>
          <thead>
            <tr>
              <th>Nguồn</th><th className="num">Số bài</th><th>Bài đầu tiên</th><th>Bài mới nhất</th>
              <th className="num">Trung vị số từ</th><th className="num">Thiếu tác giả</th>
            </tr>
          </thead>
          <tbody>
            {data.per_source.map((s) => (
              <tr key={s.source}>
                <td><SourceBadge source={s.source} /></td>
                <td className="num">{fmt(s.articles)}</td>
                <td>{s.first_published ?? "—"}</td>
                <td>{s.last_published ?? "—"}</td>
                <td className="num">{fmt(s.median_words)}</td>
                <td className="num">{s.pct_missing_author}%</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
