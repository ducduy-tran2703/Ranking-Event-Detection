import { NavLink, Outlet, useLocation } from "react-router";
import { DataStatusBar } from "../../components/DataStatusBar";
import { kho } from "../../lib/routes";
import { useTitle } from "../../lib/useTitle";

const TITLES: [string, string][] = [
  [kho.time, "Thời gian"], [kho.categories, "Chuyên mục"], [kho.quality, "Chất lượng"], [kho.articles, "Bài báo"],
  [kho.sources, "Nguồn dữ liệu"],
];

/** Kho dữ liệu: 7 trang kiểm soát dữ liệu cũ (Tổng quan, Thời gian, Chuyên mục, Chất lượng, Bài báo, Nguồn). */
export function KhoShell() {
  const cls = ({ isActive }: { isActive: boolean }) => (isActive ? "active" : undefined);
  const { pathname } = useLocation();
  const page = TITLES.find(([p]) => pathname.startsWith(p))?.[1] ?? "Tổng quan";
  useTitle(`${page} · Kho dữ liệu · Quản trị`);
  return (
    <div className="kho fade">
      <nav aria-label="Kho dữ liệu" className="subnav">
        <NavLink to={kho.overview} end className={cls}>Tổng quan</NavLink>
        <NavLink to={kho.time} className={cls}>Thời gian</NavLink>
        <NavLink to={kho.categories} className={cls}>Chuyên mục</NavLink>
        <NavLink to={kho.quality} className={cls}>Chất lượng</NavLink>
        <NavLink to={kho.articles} className={cls}>Bài báo</NavLink>
        <NavLink to={kho.sources} className={cls}>Nguồn dữ liệu</NavLink>
      </nav>
      <DataStatusBar />
      <Outlet />
    </div>
  );
}
