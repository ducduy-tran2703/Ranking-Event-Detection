import { Link } from "react-router";
import { useCategories } from "../api/queries";
import { Card } from "../components/Card";
import { HorizontalStackedBars } from "../components/charts";
import { FilterBar, useUrlFilter } from "../components/FilterBar";
import { SourceBadge } from "../components/SourceBadge";
import { ErrorBox, Loading } from "../components/Status";
import { fmtInt } from "../lib/format";
import { pivot } from "../lib/pivot";
import { kho } from "../lib/routes";

export function CategoriesPage() {
  const { filter } = useUrlFilter();
  const stats = { source: filter.source, date_from: filter.date_from, date_to: filter.date_to };
  const cats = useCategories(stats);
  if (cats.isPending) return <Loading />;
  if (cats.error) return <ErrorBox error={cats.error} />;

  const rows = cats.data.map((r) => ({ ...r, category: r.category ?? "(trống)" }));
  const totals = new Map<string, number>();
  for (const r of rows) totals.set(r.category, (totals.get(r.category) ?? 0) + r.n);
  const ordered = [...totals.entries()].sort((a, b) => b[1] - a[1]).map(([c]) => c);
  const { data, sources } = pivot(rows, "category", ordered);

  return (
    <>
      <h1>Chuyên mục</h1>
      <FilterBar />
      <Card title="Số bài theo chuyên mục"
            hint="Mỗi báo đặt tên chuyên mục khác nhau — cần bảng ánh xạ trước khi so sánh giữa các báo.">
        <HorizontalStackedBars data={data} yKey="category" sources={sources} />
      </Card>
      <Card title="Bảng chuyên mục × nguồn" hint="Bấm một con số để xem đúng những bài đó.">
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Chuyên mục</th>
                {sources.map((s) => <th key={s} className="num"><SourceBadge source={s} /></th>)}
                <th className="num">Tổng</th>
              </tr>
            </thead>
            <tbody>
              {data.map((row) => (
                <tr key={String(row.category)}>
                  <td>{row.category}</td>
                  {sources.map((s) => (
                    <td key={s} className="num">
                      {Number(row[s]) > 0 ? (
                        <Link to={`${kho.articles}?source=${s}&category=${encodeURIComponent(String(row.category))}`}>
                          {fmtInt(Number(row[s]))}
                        </Link>
                      ) : <span className="muted">—</span>}
                    </td>
                  ))}
                  <td className="num"><strong>{fmtInt(totals.get(String(row.category)))}</strong></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </>
  );
}
