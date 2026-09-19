import { useFiles, useFreshness } from "../api/queries";
import { Card } from "../components/Card";
import { ErrorBox, Loading } from "../components/Status";
import { ageHours, fmtDateTime, fmtMB, timeAgo } from "../lib/format";

export function SourcesPage() {
  const files = useFiles();
  const fresh = useFreshness();
  if (files.isPending) return <Loading />;
  if (files.error) return <ErrorBox error={files.error} />;

  const newer = new Set(fresh.data?.newer_files ?? []);
  const real = files.data.filter((f) => f.size_bytes > 0);

  return (
    <>
      <h1>Nguồn dữ liệu</h1>
      <Card title="Dữ liệu đang hiển thị so với kho"
            hint="Backend giữ một bản sao trong bộ nhớ, nạp từ kho R2. Crawler ghi file mới lên kho thì bản sao cũ đi.">
        <dl className="fields">
          <dt>Nạp vào bộ nhớ lúc</dt><dd>{fmtDateTime(fresh.data?.loaded_at)} ({timeAgo(fresh.data?.loaded_at)})</dd>
          <dt>File trên kho sửa gần nhất</dt><dd>{fmtDateTime(fresh.data?.remote_latest_modified)}</dd>
          <dt>Tình trạng</dt>
          <dd>{fresh.data?.has_newer_data
            ? <span className="badge warn">Có dữ liệu mới hơn — bấm "Cập nhật dữ liệu" ở trên</span>
            : <span className="badge ok">Đang dùng bản mới nhất</span>}</dd>
        </dl>
      </Card>
      <Card title="File trên kho" hint="File lâu không được cập nhật nghĩa là crawler của báo đó có thể đã ngừng chạy.">
        <div className="table-wrap">
          <table>
            <thead><tr><th>File</th><th className="num">Dung lượng</th><th>Sửa lần cuối</th><th>Độ tươi</th><th /></tr></thead>
            <tbody>
              {real.map((f) => {
                const h = ageHours(f.last_modified);
                const cls = h > 72 ? "bad" : h > 24 ? "warn" : "ok";
                return (
                  <tr key={f.key}>
                    <td><code>{f.key}</code></td>
                    <td className="num">{fmtMB(f.size_bytes)}</td>
                    <td>{fmtDateTime(f.last_modified)}</td>
                    <td><span className={`badge ${cls}`}>{timeAgo(f.last_modified)}</span></td>
                    <td>{newer.has(f.key) && <span className="badge warn">chưa nạp</span>}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Card>
    </>
  );
}
