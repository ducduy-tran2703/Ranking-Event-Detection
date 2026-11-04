import { Link } from "react-router";
import type { IssueCounts, RawSourceValue } from "../api/client";
import { useQuality } from "../api/queries";
import { Card } from "../components/Card";
import { GroupedBars } from "../components/charts";
import { SourceBadge } from "../components/SourceBadge";
import { ErrorBox, Loading } from "../components/Status";
import { fmtInt } from "../lib/format";
import { pivot } from "../lib/pivot";
import { kho } from "../lib/routes";

const ISSUES: { key: keyof Omit<IssueCounts, "source" | "articles">; label: string; rule: string }[] = [
  { key: "missing_author", label: "Thiếu tác giả", rule: "author rỗng hoặc null" },
  { key: "missing_sapo", label: "Thiếu sapo", rule: "sapo rỗng hoặc null" },
  { key: "empty_content", label: "Thân bài rỗng", rule: "content_text rỗng" },
  { key: "short_content", label: "Quá ngắn", rule: "1–79 từ" },
  { key: "bad_date", label: "Ngày hỏng", rule: "published_at không đọc được" },
  { key: "future_date", label: "Ngày tương lai", rule: "muộn hơn hiện tại quá 1 giờ" },
  { key: "duplicate_url", label: "URL trùng", rule: "một URL xuất hiện nhiều lần" },
  { key: "duplicate_id", label: "article_id trùng", rule: "một article_id xuất hiện nhiều lần" },
];

/** Quy ước tên nguồn: chữ thường, không dấu, và TRÙNG tên thư mục trên kho. */
function viPhamQuyUoc(r: RawSourceValue): { nhan: string; nang: boolean; giaiThich: string }[] {
  const raw = r.source_raw ?? "";
  const loi: { nhan: string; nang: boolean; giaiThich: string }[] = [];
  if (raw !== raw.trim()) {
    loi.push({ nhan: "thừa khoảng trắng", nang: false,
      giaiThich: `Giá trị có khoảng trắng ở đầu hoặc cuối, dễ tạo ra hai nguồn khác nhau chỉ vì một dấu cách.` });
  }
  if (raw !== raw.toLowerCase()) {
    loi.push({ nhan: "viết hoa", nang: false,
      giaiThich: `Crawler ghi "${raw}" nhưng quy ước là chữ thường "${raw.toLowerCase()}". Chưa chuẩn hoá thì "${raw}" và "${raw.toLowerCase()}" bị đếm thành hai nguồn riêng.` });
  }
  if (/[^a-zA-Z0-9_-]/.test(raw.trim())) {
    loi.push({ nhan: "ký tự lạ", nang: false,
      giaiThich: `Chỉ nên dùng chữ cái không dấu, số và gạch nối. Dấu tiếng Việt hoặc khoảng trắng làm hỏng đường dẫn và bộ lọc.` });
  }
  if (r.folder && r.folder !== r.source) {
    loi.push({ nhan: "không khớp thư mục", nang: true,
      giaiThich: `Dữ liệu nằm trong thư mục "silver/${r.folder}/" nhưng trường source lại ghi "${r.source}". Ai lọc theo "${r.folder}" sẽ nhận về 0 bài, dù ${r.n.toLocaleString("vi-VN")} bài đó vẫn nằm trong kho.` });
  }
  return loi;
}

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
                        <Link to={`${kho.articles}?source=${r.source}&issue=${i.key}`}>{fmtInt(n)}</Link>{" "}
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
        <Card
          title="Tên nguồn có đúng quy ước không"
          hint="Quy ước: trường source phải viết thường, không dấu, và TRÙNG tên thư mục trên kho."
        >
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Crawler ghi</th><th>Thư mục trên kho</th><th>Trang hiển thị</th>
                  <th className="num">Số bài</th><th>Vấn đề</th>
                </tr>
              </thead>
              <tbody>
                {q.data.raw_source_values.map((r) => {
                  const loi = viPhamQuyUoc(r);
                  return (
                    <tr key={`${r.source_raw}-${r.folder}`}>
                      <td><code>{r.source_raw}</code></td>
                      <td>{r.folder ? <code>silver/{r.folder}/</code> : <span className="muted">—</span>}</td>
                      <td><SourceBadge source={r.source} /></td>
                      <td className="num">{fmtInt(r.n)}</td>
                      <td>
                        {loi.length === 0
                          ? <span className="badge ok">đúng quy ước</span>
                          : loi.map((l) => (
                              <span key={l.nhan} className={`badge ${l.nang ? "bad" : "warn"}`} title={l.giaiThich}>
                                {l.nhan}
                              </span>
                            ))}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {q.data.raw_source_values.flatMap(viPhamQuyUoc).length > 0 && (
            <div className="note">
              <strong>Các lỗi đang có nghĩa là gì</strong>
              <ul>
                {q.data.raw_source_values.map((r) => {
                  const loi = viPhamQuyUoc(r);
                  if (!loi.length) return null;
                  return (
                    <li key={`gt-${r.source_raw}-${r.folder}`}>
                      <code>{r.source_raw}</code>
                      {loi.map((l) => (
                        <div key={l.nhan}>
                          <span className={`badge ${l.nang ? "bad" : "warn"}`}>{l.nhan}</span> {l.giaiThich}
                        </div>
                      ))}
                    </li>
                  );
                })}
              </ul>
              <strong>Vì sao phải đúng quy ước</strong>
              <ul>
                <li>Bộ lọc theo nguồn trên trang này, và mọi truy vấn của nhóm, đều dùng đúng một tên.</li>
                <li>Bước gom cụm sự kiện đếm "có bao nhiêu báo cùng đưa tin". Một báo bị tách thành hai tên sẽ bị đếm thành hai, làm điểm xu hướng sai.</li>
                <li>Người mới nhìn thư mục trên kho sẽ đoán sai tên nguồn, rồi viết truy vấn không ra kết quả.</li>
              </ul>
              <strong>Sửa ở đâu</strong>
              <ul>
                <li><em>Viết hoa, ký tự lạ, thừa khoảng trắng</em>: sửa ở crawler, tại chỗ ghi trường <code>source</code>.</li>
                <li><em>Không khớp thư mục</em>: chốt một tên duy nhất, rồi đổi cho khớp cả ba chỗ — tên thư mục, tên file, và trường <code>source</code>.</li>
              </ul>
              <p className="muted">
                Trang này <strong>tự chuẩn hoá về chữ thường</strong> nên vẫn dùng được với dữ liệu sai quy ước —
                nhưng đó chỉ là lưới an toàn, không thay được việc sửa ở crawler. Chi tiết: <code>docs/tong-hop.md</code> mục 5.3.
              </p>
            </div>
          )}
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
