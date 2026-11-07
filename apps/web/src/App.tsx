import { NavLink, Route, Routes } from "react-router";
import { DataStatusBar } from "./components/DataStatusBar";
import { ArticleDetailPage } from "./pages/ArticleDetailPage";
import { ArticlesPage } from "./pages/ArticlesPage";
import { CategoriesPage } from "./pages/CategoriesPage";
import { OverviewPage } from "./pages/OverviewPage";
import { QualityPage } from "./pages/QualityPage";
import { SourcesPage } from "./pages/SourcesPage";
import { TimePage } from "./pages/TimePage";

const NAV = [
  { to: "/", label: "Tổng quan", end: true },
  { to: "/time", label: "Thời gian" },
  { to: "/categories", label: "Chuyên mục" },
  { to: "/quality", label: "Chất lượng" },
  { to: "/articles", label: "Bài báo" },
  { to: "/sources", label: "Nguồn dữ liệu" },
];

export function App() {
  return (
    <>
      <header className="topbar">
        <strong className="brand">Sự kiện tin tức</strong>
        <nav>
          {NAV.map((n) => <NavLink key={n.to} to={n.to} end={n.end}>{n.label}</NavLink>)}
        </nav>
      </header>
      <DataStatusBar />
      <main>
        <Routes>
          <Route path="/" element={<OverviewPage />} />
          <Route path="/time" element={<TimePage />} />
          <Route path="/categories" element={<CategoriesPage />} />
          <Route path="/quality" element={<QualityPage />} />
          <Route path="/articles" element={<ArticlesPage />} />
          <Route path="/articles/:articleId" element={<ArticleDetailPage />} />
          <Route path="/sources" element={<SourcesPage />} />
          <Route path="*" element={<p>Không tìm thấy trang.</p>} />
        </Routes>
      </main>
    </>
  );
}
