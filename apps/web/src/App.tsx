import { NavLink, Route, Routes } from "react-router";
import { ArticleDetailPage } from "./pages/ArticleDetailPage";
import { ArticlesPage } from "./pages/ArticlesPage";
import { OverviewPage } from "./pages/OverviewPage";

export function App() {
  return (
    <>
      <header className="topbar">
        <strong>Sự kiện tin tức</strong>
        <nav>
          <NavLink to="/" end>Tổng quan</NavLink>
          <NavLink to="/articles">Bài báo</NavLink>
        </nav>
      </header>
      <main>
        <Routes>
          <Route path="/" element={<OverviewPage />} />
          <Route path="/articles" element={<ArticlesPage />} />
          <Route path="/articles/:articleId" element={<ArticleDetailPage />} />
          <Route path="*" element={<p>Không tìm thấy trang.</p>} />
        </Routes>
      </main>
    </>
  );
}
