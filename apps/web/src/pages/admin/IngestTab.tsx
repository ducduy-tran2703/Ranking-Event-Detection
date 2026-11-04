import { useFiles, useFreshness, useOverview, useReload, useRunInfo } from "../../api/queries";
import { ErrorBox, Loading } from "../../components/Status";
import { fmtDateTime, fmtInt, fmtMB, timeAgo } from "../../lib/format";
import { sourceName } from "../../lib/sources";
import { useTitle } from "../../lib/useTitle";

const NO_DATA = <span className="muted">chưa có dữ liệu</span>;

/** Tab Thu thập: chưa có API trạng thái crawler → dùng số liệu kho Silver (/api/stats/overview, /api/files, /api/freshness). */
export function IngestTab() {
  useTitle("Thu thập · Quản trị");
  const overview = useOverview();
  const files = useFiles();
  const fresh = useFreshness();
  const run = useRunInfo();
  const reload = useReload();
  const fileOf = (src: string) => files.data?.filter((f) => f.key.includes(`/${src}/`)) ?? [];

  return (
    <div className="stack fade" style={{ gap: 16 }}>
      <h1 className="sr-only">Quản trị — Thu thập</h1>
      <p role="status" className="info-box">
        Chưa có API trạng thái crawler (bảng <code>crawl_runs</code> chưa nối vào web) nên cột Crawler/Trạng thái ghi “chưa có
        dữ liệu”. Số bài và file lấy từ kho Silver mà máy chủ đang nạp.
      </p>
      <div className="grid-auto">
        <div className="stat-card"><div className="label">Bài trong kho Silver</div>
          <div className="value accent">{overview.data ? fmtInt(overview.data.total.articles) : "…"}</div>
          {overview.data && <div className="note">{overview.data.total.sources} báo</div>}</div>
        <div className="stat-card"><div className="label">Crawler đang bật</div><div className="value" style={{ fontSize: 17, marginTop: 4 }}>{NO_DATA}</div></div>
        <div className="stat-card"><div className="label">Dữ liệu nạp lúc</div>
          <div className="value" style={{ fontSize: 17, marginTop: 4 }}>{fresh.data ? fmtDateTime(fresh.data.loaded_at) : "…"}</div>
          {fresh.data && <div className="note">{fresh.data.has_newer_data ? "⚠ trên kho có file mới hơn" : `kiểm tra kho ${timeAgo(fresh.data.checked_at)}`}</div>}</div>
        <div className="stat-card"><div className="label">Lần chạy pipeline sự kiện</div>
          <div className="value" style={{ fontSize: 17, marginTop: 4 }}>{run.data ? <code>{run.data.run_id}</code> : run.error ? "chưa có" : "…"}</div>
          {run.data && <div className="note">{fmtInt(run.data.n_su_kien)} sự kiện · worker liên tục làm ở giai đoạn 2</div>}</div>
      </div>
      <div className="inline">
        <button type="button" className={`btn${fresh.data?.has_newer_data ? "" : "-ghost"} sm pill`} disabled={reload.isPending}
                onClick={() => reload.mutate()}>{reload.isPending ? "Đang nạp lại…" : "⟳ Nạp lại dữ liệu từ kho"}</button>
        {reload.isSuccess && <span className="small" role="status" style={{ color: "var(--ok)" }}>✓ Đã nạp {fmtInt(reload.data.rows)} bài trong {reload.data.seconds}s</span>}
        {reload.error && <span className="small" role="alert" style={{ color: "var(--danger)" }}>{reload.error.message}</span>}
      </div>
      <section aria-labelledby="h-src" className="card pad-sm">
        <h2 id="h-src" style={{ fontSize: 16, marginBottom: 10 }}>Từng báo</h2>
        {overview.isPending && <Loading lines={4} />}
        {overview.error && <ErrorBox error={overview.error} onRetry={() => overview.refetch()} />}
        {overview.data && (
          <div className="table-wrap" tabIndex={0} aria-label="Bảng thu thập theo báo (cuộn ngang được)">
            <table className="wide">
              <thead><tr>
                <th scope="col">Báo</th><th scope="col">Crawler</th><th scope="col">Trạng thái</th><th scope="col" className="num">Bài</th>
                <th scope="col">Bài mới nhất</th><th scope="col">File trên kho</th>
              </tr></thead>
              <tbody>
                {overview.data.per_source.map((s) => {
                  const fs = fileOf(s.source);
                  const latest = fs.reduce<string | null>((m, f) => (!m || f.last_modified > m ? f.last_modified : m), null);
                  return (
                    <tr key={s.source}>
                      <th scope="row" style={{ background: "none", color: "var(--text)", fontSize: 14 }}>{sourceName(s.source)}</th>
                      <td>{NO_DATA}</td>
                      <td><span className="tag grey">Tắt</span></td>
                      <td className="num">{fmtInt(s.articles)}</td>
                      <td className="tnum">{s.last_published ?? "—"}</td>
                      <td className="small">{files.isPending ? "…" : fs.length
                        ? <>{fs.length} file · {fmtMB(fs.reduce((a, f) => a + f.size_bytes, 0))} · sửa {fmtDateTime(latest)}</>
                        : NO_DATA}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        <p className="hint" style={{ marginTop: 10 }}>Cảnh báo tự bật khi một báo đã bật crawler mà 2 giờ không có bài mới, hoặc lần chạy
          cuối là lỗi hay bị chặn (khi có API trạng thái crawler).</p>
      </section>
    </div>
  );
}
