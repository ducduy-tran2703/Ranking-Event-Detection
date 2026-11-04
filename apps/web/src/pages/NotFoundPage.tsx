import { Link, useLocation } from "react-router";
import { useTitle } from "../lib/useTitle";

export function NotFoundPage() {
  useTitle("Không tìm thấy trang");
  const { pathname } = useLocation();
  return (
    <div className="page narrow">
      <div className="notfound rise" data-testid="not-found">
        <span className="big grad-text" aria-hidden="true">404</span>
        <h1>Không tìm thấy trang</h1>
        <p className="muted">Không có trang nào ở <code>{pathname}</code>. Liên kết có thể đã cũ hoặc gõ nhầm.</p>
        <div className="inline" style={{ justifyContent: "center" }}>
          <Link to="/" className="btn pill">Về trang xu hướng</Link>
          <Link to="/events" className="btn-ghost pill">Tìm sự kiện</Link>
        </div>
      </div>
    </div>
  );
}
