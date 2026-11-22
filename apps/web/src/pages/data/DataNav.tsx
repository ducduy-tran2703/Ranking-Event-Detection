import { NavLink } from "react-router";

/** Thanh chuyển giữa các trang "Dữ liệu & mô hình". */
export function DataNav() {
  const cls = ({ isActive }: { isActive: boolean }) => (isActive ? "active" : undefined);
  return (
    <nav aria-label="Dữ liệu và mô hình" className="subnav rise">
      <NavLink to="/du-lieu/he-thong" className={cls}>Kiến trúc hệ thống</NavLink>
      <NavLink to="/du-lieu/may-chu" className={cls}>Dữ liệu máy chủ</NavLink>
      <NavLink to="/du-lieu/chat-luong" className={cls}>Chất lượng dữ liệu</NavLink>
      <NavLink to="/du-lieu/mo-hinh" className={cls}>Mô hình</NavLink>
      <NavLink to="/du-lieu/gom-cum" className={cls}>Trực quan gom cụm</NavLink>
    </nav>
  );
}
