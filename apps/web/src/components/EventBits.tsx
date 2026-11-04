import { ApiError } from "../api/client";
import { useRunInfo } from "../api/queries";
import { ErrorBox } from "./Status";

/** nguon_ten của backend → nhãn. "an" = tên mô hình đang ẩn (cửa sổ tập test đặt tên): hiển thị tiêu đề bài đại diện. */
const NAME_SOURCES: Record<string, { label: string; long: string; cls: string; hint: string }> = {
  model: { label: "ViT5", long: "Tên do máy tự đặt (ViT5)", cls: "outline", hint: "Tên do mô hình ViT5 sinh, chưa có người duyệt" },
  medoid: {
    label: "bài đại diện", long: "Tên lấy từ bài đại diện", cls: "outline",
    hint: "Tên mô hình bị loại (không khớp nội dung / quá dài / lặp) → dùng tiêu đề bài đại diện",
  },
  title: { label: "tiêu đề", long: "Sự kiện một bài: tên là tiêu đề", cls: "outline", hint: "Sự kiện một bài: tên là tiêu đề bài" },
  an: {
    label: "tên ẩn tạm", long: "Tên mô hình đang ẩn tạm", cls: "warn",
    hint: "Tên mô hình đang ẩn để giữ mù cho tập test đặt tên; đang hiển thị tiêu đề bài đại diện",
  },
};

export function NameSourceBadge({ source, long = false }: { source: string; long?: boolean }) {
  const s = NAME_SOURCES[source] ?? { label: source, long: source, cls: "outline", hint: "" };
  return <span className={`tag ${s.cls}`} title={s.hint}>{long ? s.long : s.label}</span>;
}

/** Dòng ghi chú hạn chế ngắn, đặt dưới tiêu đề các trang sự kiện. */
export function EventNotice() {
  const run = useRunInfo();
  const w = run.data?.cua_so_an_ten;
  const d = (iso: string) => `${iso.slice(8, 10)}/${iso.slice(5, 7)}`;
  return (
    <p className="notice-line" role="note">
      <span>Điểm xu hướng chưa được đánh giá</span>
      <span>tên do mô hình sinh, chưa người duyệt</span>
      {w && <span>tên mô hình {d(w.tu_ngay)}{w.den_ngay !== w.tu_ngay ? `–${d(w.den_ngay)}` : ""} đang ẩn</span>}
      {run.data && <span>lần chạy <code>{run.data.run_id}</code></span>}
    </p>
  );
}

/** Lỗi ở trang sự kiện: 503 = server chưa có kết quả pipeline (khác với mất kết nối backend). */
export function EventErrorBox({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  if (error instanceof ApiError && error.status === 503) {
    return (
      <div className="error-box info" role="alert" data-testid="no-run">
        <strong>Chưa có kết quả pipeline sự kiện trên máy chủ.</strong>
        <span className="detail">
          Người quản trị chạy <code>make pipeline</code> (tạo <code>data/runs/&lt;run_id&gt;/</code>) hoặc đặt{" "}
          <code>EVENTS_RUN_DIR</code>, rồi khởi động lại API. Trang dữ liệu bài báo trong khu Quản trị vẫn dùng được.
        </span>
        {onRetry && <button type="button" className="btn-ghost sm pill" onClick={onRetry}>Thử lại</button>}
      </div>
    );
  }
  if (error instanceof ApiError && error.status === 404) {
    return <ErrorBox error={error} title="Không tìm thấy sự kiện."
                     hint="Mã sự kiện không có trong lần chạy pipeline hiện tại. Liên kết có thể đã cũ." />;
  }
  if (error instanceof ApiError && error.status === 422) {
    return <ErrorBox error={error} title="Đường dẫn không hợp lệ."
                     hint="Mã sự kiện hoặc tham số trên đường dẫn không đúng dạng (mã sự kiện có dạng E20260910-f095bbfb)." />;
  }
  return <ErrorBox error={error} onRetry={onRetry} />;
}
