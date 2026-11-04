import { lazy, Suspense } from "react";
import { NavLink, Route, Routes } from "react-router";
import { DataStatusBar } from "./components/DataStatusBar";
import { Loading } from "./components/Status";
import { ArticleDetailPage } from "./pages/ArticleDetailPage";
import { ArticlesPage } from "./pages/ArticlesPage";
import { EventsPage } from "./pages/EventsPage";
import { SourcesPage } from "./pages/SourcesPage";
import { TrendingPage } from "./pages/TrendingPage";

// Các trang có biểu đồ (recharts, phần lớn dung lượng JS) tải khi mở lần đầu → trang Xu hướng / Sự kiện / Bài báo
// không phải đợi tải thư viện biểu đồ.
const OverviewPage = lazy(() => import("./pages/OverviewPage").then((m) => ({ default: m.OverviewPage })));
const TimePage = lazy(() => import("./pages/TimePage").then((m) => ({ default: m.TimePage })));
const CategoriesPage = lazy(() => import("./pages/CategoriesPage").then((m) => ({ default: m.CategoriesPage })));
const QualityPage = lazy(() => import("./pages/QualityPage").then((m) => ({ default: m.QualityPage })));
const EventDetailPage = lazy(() => import("./pages/EventDetailPage").then((m) => ({ default: m.EventDetailPage })));

// Hai mục đầu là web demo sự kiện (kết quả pipeline); các mục sau là trang kiểm soát dữ liệu bài báo.
const NAV = [
  { to: "/trending", label: "Xu hướng", featured: true },
  { to: "/events", label: "Sự kiện", featured: true },
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
          {NAV.map((n) => (
            <NavLink key={n.to} to={n.to} end={"end" in n ? n.end : false}
                     className={"featured" in n ? "featured" : undefined}>
              {n.label}
            </NavLink>
          ))}
        </nav>
      </header>
      <DataStatusBar />
      <main>
        <Suspense fallback={<Loading />}>
        <Routes>
          <Route path="/" element={<OverviewPage />} />
          <Route path="/trending" element={<TrendingPage />} />
          <Route path="/events" element={<EventsPage />} />
          <Route path="/events/:eventId" element={<EventDetailPage />} />
          <Route path="/time" element={<TimePage />} />
          <Route path="/categories" element={<CategoriesPage />} />
          <Route path="/quality" element={<QualityPage />} />
          <Route path="/articles" element={<ArticlesPage />} />
          <Route path="/articles/:articleId" element={<ArticleDetailPage />} />
          <Route path="/sources" element={<SourcesPage />} />
          <Route path="*" element={<p>Không tìm thấy trang.</p>} />
        </Routes>
        </Suspense>
      </main>
    </>
  );
}
