import { NavLink, Outlet } from "react-router";
import { useAdminFeedback } from "../../api/adminQueries";

/** Khu quản trị (thiết kế Admin): tab theo route để kiểm thử/gửi link được. */
export function AdminShell() {
  const fb = useAdminFeedback();
  const open = fb.data?.filter((f) => f.status === "open").length ?? 0;
  const cls = ({ isActive }: { isActive: boolean }) => (isActive ? "active" : undefined);
  return (
    <div className="page" style={{ gap: 18 }}>
      <nav aria-label="Khu quản trị" className="tabs">
        <NavLink to="/admin/thu-thap" className={cls}>Thu thập</NavLink>
        <NavLink to="/admin/bao-sai" className={cls}>Báo sai{open ? ` (${open})` : ""}</NavLink>
        <NavLink to="/admin/thu" className={cls}>Thư hệ thống</NavLink>
        <NavLink to="/admin/nguoi-dung" className={cls}>Người dùng</NavLink>
        <NavLink to="/admin/khoa-api" className={cls}>Khoá API</NavLink>
        <NavLink to="/admin/kho" className={cls}>Kho dữ liệu</NavLink>
      </nav>
      <Outlet />
    </div>
  );
}
