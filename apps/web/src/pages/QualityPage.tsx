import { Link } from "react-router";
import type { IssueCounts } from "../api/client";
import { useQuality } from "../api/queries";
import { Card } from "../components/Card";
import { GroupedBars } from "../components/charts";
import { SourceBadge } from "../components/SourceBadge";
import { ErrorBox, Loading } from "../components/Status";
import { fmtInt } from "../lib/format";
import { pivot } from "../lib/pivot";

const ISSUES: { key: keyof Omit<IssueCounts, "source" | "articles">; label: string; rule: string }[] = [
  { key: "missing_author", label: "Thiếu tác giả", rule: "author rỗng hoặc null" },
  { key: "empty_content", label: "Thân bài rỗng", rule: "content_text rỗng" },
  { key: "short_content", label: "Quá ngắn", rule: "1–79 từ" },
  { key: "bad_date", label: "Ngày hỏng", rule: "published_at không đọc được" },
  { key: "future_date", label: "Ngày tương lai", rule: "muộn hơn hiện tại quá 1 giờ" },
  { key: "duplicate_url", label: "URL trùng", rule: "một URL xuất hiện nhiều lần" },
  { key: "duplicate_id", label: "article_id trùng", rule: "một article_id xuất hiện nhiều lần" },
];

export function QualityPage() {
  const q = useQuality();
  if (q.isPending) return <Loading />;
  if (q.error) return <ErrorBox error={q.error} />;

  const words = pivot(q.data.words_histogram, "bin");
  const wordsData = words.data.map((r) => ({ ...r, bin: Number(r.bin) >= 2000 ? "≥2000" : `${r.bin}–${Number(r.bin) + 99}` }));
  const titleOrder = Array.from({ length: 40 }, (_, i) => i + 1);
  const titles = pivot(q.data.title_words_histogram, "words", titleOrder);
  const crossSource = q.data.duplicate_titles.filter((d) => d.sources > 1);

  return (
    <>
      <h1>Chất lượng dữ liệu</h1>
      <Card title="Lỗi theo nguồn" hint="Bấm một con số để xem đúng những bài bị lỗi đó. Di chuột lên tên cột để xem định nghĩa.">
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Nguồn</th><th className="num">Số bài</th>
                {ISSUES.map((i) => <th key={i.key} className="num" title={i.rule}>{i.label}</th>)}
              </tr>
            </thead>
            <tbody>
              {q.data.issues_per_source.map((r) => (
                <tr key={r.source}>
                  <td><SourceBadge source={r.source} /></td>
                  <td className="num">{fmtInt(r.articles)}</td>
                  {ISSUES.map((i) => {
                    const n = r[i.key];
                    if (!n) return <td key={i.key} className="num muted">0</td>;
                    const pct = Math.round((n / r.articles) * 1000) / 10;
                    const cls = pct >= 20 ? "bad" : pct >= 5 ? "warn" : "";
                    return (
                      <td key={i.key} className="num">
                        <Link to={`/articles?source=${r.source}&issue=${i.key}`}>{fmtInt(n)}</Link>{" "}
                        <span className={`badge ${cls}`}>{pct}%</span>
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <div className="grid2">
        <Card title="Giá trị gốc của cột source" hint="Crawler phải ghi chữ thường; trang tự chuẩn hoá để vẫn dùng được.">
          <table>
            <thead><tr><th>Giá trị gốc</th><th>Sau chuẩn hoá</th><th className="num">Số bài</th><th /></tr></thead>
            <tbody>
              {q.data.raw_source_values.map((r) => (
                <tr key={`${r.source_raw}`}>
                  <td><code>{r.source_raw}</code></td>
                  <td><SourceBadge source={r.source} /></td>
                  <td className="num">{fmtInt(r.n)}</td>
                  <td>{r.source_raw === r.source ? <span className="badge ok">khớp</span> : <span className="badge warn">sai quy ước</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
        <Card title="Tiêu đề trùng giữa các báo"
              hint={`${crossSource.length} tiêu đề giống hệt nhau ở ≥ 2 báo — dấu hiệu tốt: cùng một sự kiện được nhiều báo đưa.`}>
          <table>
            <thead><tr><th>Tiêu đề</th><th>Nguồn</th></tr></thead>
            <tbody>
              {crossSource.map((d) => (
                <tr key={d.title ?? ""}>
                  <td>{d.title}</td>
                  <td>{d.source_list.map((s) => <div key={s}><SourceBadge source={s} /></div>)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      </div>

      <Card title="Độ dài thân bài (số từ)" hint="Cột đầu tiên cao bất thường = nhiều bài thân rỗng hoặc chỉ có video.">
        <GroupedBars data={wordsData} xKey="bin" sources={words.sources} />
      </Card>
      <Card title="Độ dài tiêu đề (số từ)" hint="Dùng để quyết định nhãn huấn luyện cho bài toán đặt tên sự kiện 5–10 từ.">
        <GroupedBars data={titles.data} xKey="words" sources={titles.sources} />
      </Card>
    </>
  );
}
