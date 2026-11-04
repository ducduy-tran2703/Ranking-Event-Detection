import { ApiError } from "../api/client";
import { useRunInfo } from "../api/queries";
import { ErrorBox } from "./Status";

/** nguon_ten của backend → nhãn hiển thị. "an" = tên mô hình đang ẩn (cửa sổ tập test đặt tên). */
const NAME_SOURCES: Record<string, { label: string; cls: string; hint: string }> = {
  model: { label: "mô hình", cls: "neutral", hint: "Tên do mô hình ViT5 sinh, chưa có người duyệt" },
  medoid: {
    label: "medoid", cls: "neutral",
    hint: "Tên mô hình bị loại (không trung thực / quá dài / lặp) → dùng tiêu đề bài đại diện",
  },
  title: { label: "tiêu đề", cls: "neutral", hint: "Sự kiện một bài: tên là tiêu đề bài (có thể rút gọn)" },
  an: {
    label: "ẩn tạm", cls: "warn",
    hint: "Tên mô hình đang ẩn để giữ mù cho tập test đặt tên; đang hiển thị tiêu đề bài đại diện",
  },
};

export function NameSourceBadge({ source }: { source: string }) {
  const s = NAME_SOURCES[source] ?? { label: source, cls: "neutral", hint: "" };
  return <span className={`badge ${s.cls}`} title={s.hint}>{s.label}</span>;
}

/** Dải thông báo hạn chế, đặt trên mọi trang sự kiện. */
export function EventNotice() {
  const run = useRunInfo();
  const w = run.data?.cua_so_an_ten;
  const d = (iso: string) => `${iso.slice(8, 10)}/${iso.slice(5, 7)}`;
  return (
    <div className="event-notice" role="note">
      <span>Điểm xu hướng chưa được đánh giá</span>
      <span>tên do mô hình sinh, chưa người duyệt</span>
      {w && <span>tên {d(w.tu_ngay)}{w.den_ngay !== w.tu_ngay ? `–${d(w.den_ngay)}` : ""} đang ẩn</span>}
      {run.data && <span className="muted">lần chạy <code>{run.data.run_id}</code></span>}
    </div>
  );
}

/** Lỗi ở trang sự kiện: 503 = server chưa có kết quả pipeline (khác với mất kết nối backend). */
export function EventErrorBox({ error }: { error: unknown }) {
  if (error instanceof ApiError && error.status === 503) {
    return (
      <div className="error">
        <strong>Chưa có kết quả pipeline sự kiện trên server.</strong>
        <div>Chạy <code>make pipeline</code> (tạo <code>data/runs/&lt;run_id&gt;/</code>) hoặc đặt{" "}
          <code>EVENTS_RUN_DIR</code>, rồi khởi động lại API. Các trang dữ liệu bài báo vẫn dùng được.</div>
      </div>
    );
  }
  if (error instanceof ApiError && error.status === 404) {
    return <div className="error"><strong>Không tìm thấy sự kiện.</strong> Mã sự kiện không có trong lần chạy hiện tại.</div>;
  }
  return <ErrorBox error={error} />;
}
