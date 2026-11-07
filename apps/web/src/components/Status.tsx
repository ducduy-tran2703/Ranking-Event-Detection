/** Hiển thị thống nhất cho trạng thái đang tải và lỗi ở mọi trang. */
export function Loading() {
  return <p className="muted">Đang tải…</p>;
}

export function ErrorBox({ error }: { error: unknown }) {
  const message = error instanceof Error ? error.message : String(error);
  return (
    <div className="error">
      <strong>Không tải được dữ liệu.</strong> {message}
      <div className="muted">Kiểm tra backend có đang chạy ở cổng 8000 không.</div>
    </div>
  );
}
