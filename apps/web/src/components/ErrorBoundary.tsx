import { Component, type ErrorInfo, type ReactNode } from "react";
import { useLocation } from "react-router";

/**
 * Lỗi khi hiển thị một trang (dữ liệu lạ từ API, gói JS lười tải hỏng…) chỉ thay phần nội dung trang bằng hộp lỗi có nút
 * "Tải lại trang"; header, menu và các trang khác vẫn dùng được. Không có lớp này, React gỡ cả cây và trang trắng hẳn.
 */
class Boundary extends Component<{ resetKey: string; children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };
  static getDerivedStateFromError(error: Error) { return { error }; }
  componentDidCatch(error: Error, info: ErrorInfo) { console.error("Lỗi hiển thị trang:", error, info.componentStack); }
  componentDidUpdate(prev: { resetKey: string }) {    // sang trang khác thì thử hiển thị lại (không dựng lại cây khi không lỗi)
    if (this.state.error && prev.resetKey !== this.props.resetKey) this.setState({ error: null });
  }
  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="page">
        <div className="error-box" role="alert" data-testid="page-crash">
          <strong>Trang này gặp lỗi khi hiển thị.</strong>
          <span className="detail">
            Có thể máy chủ vừa trả dữ liệu khác dạng mong đợi. Tải lại trang, hoặc mở trang khác từ thanh trên.
            {" "}(Chi tiết: {String(this.state.error.message || this.state.error).slice(0, 200)})
          </span>
          <button type="button" className="btn-ghost sm" onClick={() => window.location.reload()}>Tải lại trang</button>
        </div>
      </div>
    );
  }
}

/** Bọc <Outlet/> của layout; đang hiện lỗi mà đổi đường dẫn thì bỏ lỗi (lỗi của trang cũ không dính sang trang mới). */
export function RouteErrorBoundary({ children }: { children: ReactNode }) {
  const { pathname } = useLocation();
  return <Boundary resetKey={pathname}>{children}</Boundary>;
}
