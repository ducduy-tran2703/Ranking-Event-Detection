// Trạng thái thống nhất cho mọi trang gọi API: đang tải (khung xương), lỗi (thông báo + thử lại), rỗng (giải thích).
import type { ReactNode } from "react";
import { AuthError } from "../api/auth";
import { ApiError, apiMessage } from "../api/client";

export function Skeleton({ h = 16, w = "100%", r }: { h?: number; w?: number | string; r?: number }) {
  return <span className="skeleton" style={{ height: h, width: w, borderRadius: r }} aria-hidden="true" />;
}

/** Khung xương nhiều dòng + chữ "Đang tải…" cho trình đọc màn hình. */
export function Loading({ lines = 3, h = 18, label = "Đang tải…" }: { lines?: number; h?: number; label?: string }) {
  return (
    <div className="skel-stack" role="status" aria-live="polite" data-testid="loading">
      <span className="sr-only">{label}</span>
      {Array.from({ length: lines }, (_, i) => <Skeleton key={i} h={h} w={i === lines - 1 ? "60%" : "100%"} />)}
    </div>
  );
}

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  return error instanceof Error ? error.message : String(error);
}

const OFFLINE = "Không kết nối được máy chủ API. Kiểm tra backend có đang chạy ở cổng 8000 không.";

/** Lý do hiện trong ErrorBox: theo mã HTTP khi máy chủ có trả lời; "không kết nối được" chỉ khi không gọi tới được máy chủ. */
export function errorReason(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof AuthError) {
    if (error.status == null) return error.code === "server" ? OFFLINE : error.message;
    if (error.status === 401 || error.status === 403) return `Không có quyền xem nội dung này. ${error.message}`;
    return apiMessage(error.status, error.message);
  }
  return OFFLINE;                                    // fetch ném TypeError (mất mạng, máy chủ tắt)
}

export function ErrorBox({ error, onRetry, title = "Không tải được dữ liệu.", hint }: {
  error: unknown; onRetry?: () => void; title?: string; hint?: ReactNode;
}) {
  return (
    <div className="error-box" role="alert">
      <strong>{title}</strong>
      <span className="detail">{hint ?? errorReason(error)}</span>
      {onRetry && <button type="button" className="btn-ghost sm" onClick={onRetry}>Thử lại</button>}
    </div>
  );
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="empty" role="status">
      <strong>{title}</strong>
      {children && <span>{children}</span>}
    </div>
  );
}
