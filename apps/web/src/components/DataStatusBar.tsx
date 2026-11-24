import { useCurrentUser } from "../api/accountQueries";
import { useFreshness, useMeta, useReload } from "../api/queries";
import { fmtDateTime, fmtInt, timeAgo } from "../lib/format";

/**
 * Thanh trạng thái ở đầu mọi trang.
 * Backend giữ một BẢN SAO dữ liệu trong RAM (DuckDB), nạp từ R2 lúc khởi động.
 * Crawler đẩy file mới lên R2 thì bản sao đó cũ đi → thanh này tự phát hiện (mỗi 2 phút)
 * và nút "Cập nhật dữ liệu" nạp lại từ R2, rồi làm mới mọi biểu đồ.
 */
export function DataStatusBar() {
  const meta = useMeta();
  const fresh = useFreshness();
  const reload = useReload();
  const { data: user } = useCurrentUser();
  const admin = user?.role === "admin";               // nạp lại kho chỉ admin gọi được (máy chủ trả 401/403 cho người khác)

  const stale = fresh.data?.has_newer_data ?? false;
  const loadedAt = fresh.data?.loaded_at ?? meta.data?.loaded_at ?? null;

  return (
    <div className={`status-bar ${stale ? "stale" : ""}`}>
      <div className="status-info">
        <span className="muted">Dữ liệu:</span> <code>{meta.data?.dataset ?? "…"}</code>
        {" · "}<strong>{fmtInt(meta.data?.rows)}</strong> bài
        {" · "}nạp lúc {fmtDateTime(loadedAt)} <span className="muted">({timeAgo(loadedAt)})</span>
        {fresh.data && (
          <span className="muted">
            {" · "}kiểm tra kho {timeAgo(fresh.data.checked_at)}
          </span>
        )}
      </div>

      {stale && (
        <div className="status-warn">
          ⚠ Trên kho có dữ liệu mới hơn bản đang hiển thị
          ({fresh.data!.newer_files.map((f) => f.split("/")[1]).join(", ")}).
        </div>
      )}

      <div className="status-actions">
        {reload.isSuccess && !reload.isPending && (
          <span className="ok">
            ✓ Đã cập nhật {fmtInt(reload.data.rows)} bài trong {reload.data.seconds}s
          </span>
        )}
        {reload.isError && <span className="err">{reload.error.message}</span>}
        {admin && (
          <button
            className={stale ? "primary" : ""}
            disabled={reload.isPending}
            onClick={() => reload.mutate()}
            title="Nạp lại dữ liệu mới nhất từ kho R2"
          >
            {reload.isPending ? "Đang cập nhật…" : "⟳ Cập nhật dữ liệu"}
          </button>
        )}
      </div>
    </div>
  );
}
