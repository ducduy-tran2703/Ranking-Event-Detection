import { useEffect, useRef, useState } from "react";
import { Link, NavLink, useLocation } from "react-router";
import { useCurrentUser, useNotifications } from "../api/accountQueries";
import { initials } from "../lib/format";
import { loginHref } from "../lib/routes";
import { IconBell, IconClose, IconMenu, IconSearch, IconTrend, IconUser } from "./Icons";

const NAV = [
  { to: "/", label: "Xu hướng", end: true },
  { to: "/events", label: "Sự kiện" },
  { to: "/chuyen-muc", label: "Chuyên mục" },
  { to: "/du-lieu", label: "Dữ liệu & mô hình" },
];

function Brand({ sub }: { sub?: boolean }) {
  return (
    <Link to="/" className="brand" aria-label="EventRank — về trang xu hướng">
      <span className="brand-mark" aria-hidden="true"><IconTrend /></span>
      <span className="brand-name">Event<span>Rank</span></span>
      {sub && <span className="brand-sub">Sự kiện tin tức Việt Nam</span>}
    </Link>
  );
}

function SkipLink() {
  return <a href="#noi-dung" className="skip-link">Bỏ qua, tới nội dung chính</a>;
}

/** Header công khai: thanh xanh nổi, nav 4 mục; điện thoại: icon tìm kiếm / tài khoản / menu. */
export function SiteHeader() {
  const { data: user } = useCurrentUser();
  const notis = useNotifications();
  const unread = notis.data?.filter((n) => !n.read).length ?? 0;
  const loc = useLocation();
  const [open, setOpen] = useState(false);
  const menuBtn = useRef<HTMLButtonElement>(null);
  useEffect(() => setOpen(false), [loc.pathname, loc.search]);
  useEffect(() => {                                  // Esc đóng menu điện thoại và trả focus về nút menu
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") { setOpen(false); menuBtn.current?.focus(); }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);
  const login = loginHref(loc.pathname + loc.search);

  return (
    <>
      <SkipLink />
      <header className="site-header">
        <div className="hdr">
          <Brand />
          <nav aria-label="Chính" className="main-nav">
            {NAV.map((n) => (
              <NavLink key={n.to} to={n.to} end={n.end} className={({ isActive }) => `navlink${isActive ? " active" : ""}`}>
                {n.label}
              </NavLink>
            ))}
          </nav>
          <div className="hdr-right">
            <Link to="/events?tim=1" className="hdr-icon mobile-only" aria-label="Tìm sự kiện"><IconSearch /></Link>
            {user ? (
              <>
                <Link to="/me#thong-bao" className="hdr-icon"
                      aria-label={unread ? `Thông báo, ${unread} chưa đọc` : "Thông báo, không có tin chưa đọc"}>
                  <IconBell size={21} className={unread ? "ring" : undefined} />
                  {unread > 0 && <span className="hdr-badge" aria-hidden="true">{unread > 99 ? "99+" : unread}</span>}
                </Link>
                {user.role === "admin" && <Link to="/admin" className="hdr-btn desktop-only">Quản trị</Link>}
                <Link to="/me" className="avatar-link desktop-only" aria-label={`Trang của tôi (${user.display_name})`}>
                  <span className="avatar" aria-hidden="true">{initials(user.display_name)}</span>
                  <span>{user.display_name}</span>
                </Link>
                <Link to="/me" className="hdr-icon mobile-only" aria-label="Trang của tôi"><IconUser /></Link>
              </>
            ) : (
              <>
                <Link to={login} className="hdr-btn desktop-only">Đăng nhập</Link>
                <Link to="/register" className="hdr-cta desktop-only">Tạo tài khoản</Link>
                <Link to={login} className="hdr-icon mobile-only" aria-label="Đăng nhập"><IconUser /></Link>
              </>
            )}
            <button ref={menuBtn} type="button" className="hdr-icon mobile-only" aria-expanded={open} aria-controls="menu-dien-thoai"
                    aria-label={open ? "Đóng menu" : "Mở menu"} onClick={() => setOpen(!open)}>
              {open ? <IconClose /> : <IconMenu />}
            </button>
          </div>
        </div>
        <nav id="menu-dien-thoai" aria-label="Menu điện thoại" className={`mobile-menu${open ? " open" : ""}`} hidden={!open}>
          {NAV.map((n) => (
            <NavLink key={n.to} to={n.to} end={n.end} className={({ isActive }) => (isActive ? "active" : undefined)}>
              {n.label}
            </NavLink>
          ))}
          {user ? (
            <>
              <NavLink to="/me">Trang của tôi</NavLink>
              {user.role === "admin" && <NavLink to="/admin">Quản trị</NavLink>}
            </>
          ) : (
            <>
              <Link to={login}>Đăng nhập</Link>
              <Link to="/register">Tạo tài khoản</Link>
            </>
          )}
        </nav>
      </header>
    </>
  );
}

/** Header gọn cho trang đăng nhập/đăng ký. */
export function SimpleHeader() {
  return (
    <>
      <SkipLink />
      <header className="site-header simple">
        <div className="hdr">
          <Brand sub />
          <Link to="/" className="hdr-back">← Về trang xu hướng</Link>
        </div>
      </header>
    </>
  );
}

/** Header khu quản trị: xanh đậm hơn + nhãn "Quản trị". */
export function AdminHeader({ who }: { who?: string }) {
  return (
    <>
      <SkipLink />
      <header className="site-header admin">
        <div className="hdr">
          <Link to="/admin" className="brand" aria-label="EventRank Quản trị — trang đầu khu quản trị">
            <span className="brand-mark" aria-hidden="true"><IconTrend /></span>
            <span className="brand-name">Event<span>Rank</span></span>
            <span className="admin-tag">Quản trị</span>
          </Link>
          <div className="hdr-right">
            {who && <span className="brand-sub desktop-only">Đăng nhập: {who}</span>}
            <Link to="/" className="hdr-btn">Về trang công khai</Link>
          </div>
        </div>
      </header>
    </>
  );
}
