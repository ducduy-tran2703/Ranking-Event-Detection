import { useQueryClient } from "@tanstack/react-query";
import { Suspense, useEffect, useRef, useState, type ReactNode } from "react";
import { Link, Navigate, Outlet, useLocation } from "react-router";
import { useCurrentUser } from "../api/accountQueries";
import { AUTH_MOCK, type Role } from "../api/auth";
import { prefetchRoute } from "../api/prefetch";
import { useRunInfo } from "../api/queries";
import { sourceName, DEFAULT_SOURCES } from "../lib/sources";
import { loginHref } from "../lib/routes";
import { AdminHeader, SimpleHeader, SiteHeader } from "./SiteHeader";
import { Loading } from "./Status";

function Footer() {
  const run = useRunInfo();
  const sources = (run.data?.nguon_bao.length ? run.data.nguon_bao : DEFAULT_SOURCES).map(sourceName);
  return (
    <footer className="site-footer">
      <div className="inner">
        <span>Nguồn: {sources.join(", ")}</span>
        <span>Chỉ hiện tiêu đề và liên kết tới bài gốc</span>
        <span>Tên sự kiện do mô hình ViT5 tự sinh, có thể sai</span>
        <Link to="/du-lieu/mo-hinh">Về các mô hình</Link>
      </div>
    </footer>
  );
}

/** Dải báo rõ khu tài khoản đang chạy giả lập (VITE_AUTH_MOCK). */
export function PreviewStrip() {
  if (!AUTH_MOCK) return null;
  return (
    <p className="preview-strip" role="note" data-testid="preview-strip">
      <span aria-hidden="true">⚠</span>
      <span><strong>Bản xem trước</strong> — tài khoản chưa nối máy chủ, dữ liệu chỉ lưu trên trình duyệt này.</span>
    </p>
  );
}

/** Trang lazy đang tải: khung xương trong khung trang. */
export function PageFallback() {
  return <div className="page"><Loading lines={4} h={22} /></div>;
}

/**
 * Khi đổi trang (không tính lần tải đầu và khi chỉ đổi ?query): cuộn lên đầu và chuyển focus tới h1 của trang mới (trình đọc
 * màn hình đọc tiêu đề mới; trang lười có thể chưa có h1 ngay → chờ tối đa ~1,5 s rồi rơi về <main>). Đường dẫn có #neo thì
 * không cuộn lên đầu; chỉ đổi #neo (cùng trang) thì không làm gì.
 */
function ScrollTop() {
  const { pathname } = useLocation();
  const first = useRef(true);
  useEffect(() => {
    if (first.current) { first.current = false; return; }
    if (!window.location.hash) window.scrollTo({ top: 0 });
    let tries = 0;
    const id = window.setInterval(() => {
      const main = document.getElementById("noi-dung");
      const h1 = main?.querySelector<HTMLElement>("h1:not(.sr-only)") ?? main?.querySelector<HTMLElement>("h1");
      if (h1 || ++tries > 30) {
        window.clearInterval(id);
        const target = h1 ?? main;
        if (!target) return;
        if (!target.hasAttribute("tabindex")) target.setAttribute("tabindex", "-1");
        target.focus({ preventScroll: true });
      }
    }, 50);
    return () => window.clearInterval(id);
  }, [pathname]);
  return null;
}

/** Gọi trước API của trang mới, song song với tải gói JS lười (api/prefetch.ts). */
function Prefetch() {
  const qc = useQueryClient();
  const { pathname, search } = useLocation();
  useEffect(() => { prefetchRoute(qc, pathname, search); }, [qc, pathname, search]);
  return null;
}

export function PublicLayout() {
  return (
    <>
      <ScrollTop />
      <Prefetch />
      <SiteHeader />
      <main id="noi-dung" tabIndex={-1}>
        <Suspense fallback={<PageFallback />}><Outlet /></Suspense>
      </main>
      <Footer />
    </>
  );
}

export function AuthLayout() {
  return (
    <div style={{ minHeight: "100vh", display: "flex", flexDirection: "column" }}>
      <ScrollTop />
      <SimpleHeader />
      <PreviewStrip />
      <main id="noi-dung" tabIndex={-1} style={{ flex: "1 1 auto", display: "flex" }}>
        <Suspense fallback={<PageFallback />}><Outlet /></Suspense>
      </main>
    </div>
  );
}

/** Chặn trang cần đăng nhập (và vai trò). Chưa đăng nhập → /login?next=…; sai vai trò → giải thích. */
export function RequireAuth({ role, children }: { role?: Role; children: ReactNode }) {
  const { data: user, isPending, error, refetch } = useCurrentUser();
  const loc = useLocation();
  if (isPending) return <PageFallback />;
  if (error) {
    return (
      <div className="page">
        <div className="error-box" role="alert">
          <strong>Không kiểm tra được đăng nhập.</strong>
          <button type="button" className="btn-ghost sm pill" onClick={() => refetch()}>Thử lại</button>
        </div>
      </div>
    );
  }
  if (!user) return <Navigate to={loginHref(loc.pathname + loc.search + loc.hash)} replace />;
  if (role && user.role !== role) {
    return (
      <div className="page narrow">
        <div className="notfound" role="alert">
          <span className="big grad-text" aria-hidden="true">403</span>
          <h1>Khu này chỉ dành cho quản trị viên</h1>
          <p className="muted">
            Bạn đang đăng nhập bằng <b>{user.email}</b> (vai trò <b>{user.role}</b>).
            {AUTH_MOCK && <> Trong bản xem trước, đăng nhập bằng tài khoản mẫu <code>admin@example.com</code> để vào.</>}
          </p>
          <Link to="/" className="btn pill">Về trang xu hướng</Link>
        </div>
      </div>
    );
  }
  return <>{children}</>;
}

export function AdminLayout() {
  const { data: user } = useCurrentUser();
  return (
    <RequireAuth role="admin">
      <ScrollTop />
      <AdminHeader who={user ? `${user.role} · ${user.display_name}` : undefined} />
      <PreviewStrip />
      <main id="noi-dung" tabIndex={-1}>
        <Suspense fallback={<PageFallback />}><Outlet /></Suspense>
      </main>
    </RequireAuth>
  );
}

/** Thông báo ngắn ở đáy màn hình (role=status), tự tắt sau 2,5 giây. */
export function useToast() {
  const [msg, setMsg] = useState<string | null>(null);
  useEffect(() => {
    if (!msg) return;
    const id = window.setTimeout(() => setMsg(null), 2500);
    return () => window.clearTimeout(id);
  }, [msg]);
  const node = <div aria-live="polite" role="status">{msg && <div className="toast" data-testid="toast">{msg}</div>}</div>;
  return { show: setMsg, node };
}
