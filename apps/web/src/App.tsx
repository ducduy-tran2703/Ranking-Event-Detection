import { lazy, type ComponentType } from "react";
import { Navigate, Route, Routes, useLocation, useParams } from "react-router";
import { AdminLayout, AuthLayout, PublicLayout, RequireAuth } from "./components/Layouts";
import { kho } from "./lib/routes";

// Mọi trang tách gói riêng (tải khi mở lần đầu) → JS ban đầu chỉ còn khung, header và React.
function page<K extends string, P extends object = any>(load: () => Promise<Record<K, ComponentType<P>>>, name: K) {
  return lazy(() => load().then((m) => ({ default: m[name] })));
}
const HomePage = page(() => import("./pages/HomePage"), "HomePage");
const EventsPage = page(() => import("./pages/EventsPage"), "EventsPage");
const EventDetailPage = page(() => import("./pages/EventDetailPage"), "EventDetailPage");
const CategoriesHubPage = page(() => import("./pages/CategoriesHubPage"), "CategoriesHubPage");
const ChatPage = page(() => import("./pages/ChatPage"), "ChatPage");
const NotFoundPage = page(() => import("./pages/NotFoundPage"), "NotFoundPage");
const DataQualityPage = page(() => import("./pages/data/DataQualityPage"), "DataQualityPage");
const ModelsPage = page(() => import("./pages/data/ModelsPage"), "ModelsPage");
const ClusterMapPage = page(() => import("./pages/data/ClusterMapPage"), "ClusterMapPage");
const AuthPage = page(() => import("./pages/account/AuthPage"), "AuthPage");
const MePage = page(() => import("./pages/account/MePage"), "MePage");
const AdminShell = page(() => import("./pages/admin/AdminShell"), "AdminShell");
const IngestTab = page(() => import("./pages/admin/IngestTab"), "IngestTab");
const FeedbackTab = page(() => import("./pages/admin/MockTabs"), "FeedbackTab");
const MailTab = page(() => import("./pages/admin/MockTabs"), "MailTab");
const UsersTab = page(() => import("./pages/admin/MockTabs"), "UsersTab");
const KeysTab = page(() => import("./pages/admin/MockTabs"), "KeysTab");
const KhoShell = page(() => import("./pages/admin/KhoShell"), "KhoShell");
// Kho dữ liệu: 7 trang kiểm soát dữ liệu cũ (giữ chức năng), nay trong khu quản trị.
const OverviewPage = page(() => import("./pages/OverviewPage"), "OverviewPage");
const TimePage = page(() => import("./pages/TimePage"), "TimePage");
const CategoriesPage = page(() => import("./pages/CategoriesPage"), "CategoriesPage");
const QualityPage = page(() => import("./pages/QualityPage"), "QualityPage");
const ArticlesPage = page(() => import("./pages/ArticlesPage"), "ArticlesPage");
const ArticleDetailPage = page(() => import("./pages/ArticleDetailPage"), "ArticleDetailPage");
const SourcesPage = page(() => import("./pages/SourcesPage"), "SourcesPage");

/** Chuyển hướng giữ nguyên ?query (đường dẫn cũ: /trending?t=… → /?t=…, /articles?source=… → /admin/kho/bai-bao?…). */
function Moved({ to }: { to: string }) {
  const { search } = useLocation();
  return <Navigate to={`${to}${search}`} replace />;
}
function MovedArticle() {
  const { articleId = "" } = useParams();
  return <Navigate to={kho.article(articleId)} replace />;
}

export function App() {
  return (
    <Routes>
      <Route element={<PublicLayout />}>
        <Route index element={<HomePage />} />
        <Route path="trending" element={<Moved to="/" />} />
        <Route path="events" element={<EventsPage />} />
        <Route path="events/:eventId" element={<EventDetailPage />} />
        <Route path="chuyen-muc" element={<CategoriesHubPage />} />
        <Route path="hoi-dap" element={<ChatPage />} />
        <Route path="hoi-dap/:conversationId" element={<ChatPage />} />
        <Route path="du-lieu" element={<Navigate to="/du-lieu/chat-luong" replace />} />
        <Route path="du-lieu/chat-luong" element={<DataQualityPage />} />
        <Route path="du-lieu/mo-hinh" element={<ModelsPage />} />
        <Route path="du-lieu/gom-cum" element={<ClusterMapPage />} />
        <Route path="me" element={<RequireAuth><MePage /></RequireAuth>} />
        {/* đường dẫn cũ của trang kiểm soát dữ liệu */}
        <Route path="time" element={<Moved to={kho.time} />} />
        <Route path="categories" element={<Moved to={kho.categories} />} />
        <Route path="quality" element={<Moved to={kho.quality} />} />
        <Route path="articles" element={<Moved to={kho.articles} />} />
        <Route path="articles/:articleId" element={<MovedArticle />} />
        <Route path="sources" element={<Moved to={kho.sources} />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
      <Route element={<AuthLayout />}>
        <Route path="login" element={<AuthPage mode="login" />} />
        <Route path="register" element={<AuthPage mode="register" />} />
        <Route path="forgot-password" element={<AuthPage mode="forgot" />} />
        <Route path="reset-password" element={<AuthPage mode="reset" />} />
        <Route path="verify-email" element={<AuthPage mode="verify" />} />
      </Route>
      <Route path="admin" element={<AdminLayout />}>
        <Route element={<AdminShell />}>
          <Route index element={<Navigate to="/admin/thu-thap" replace />} />
          <Route path="thu-thap" element={<IngestTab />} />
          <Route path="bao-sai" element={<FeedbackTab />} />
          <Route path="thu" element={<MailTab />} />
          <Route path="nguoi-dung" element={<UsersTab />} />
          <Route path="khoa-api" element={<KeysTab />} />
          <Route path="kho" element={<KhoShell />}>
            <Route index element={<OverviewPage />} />
            <Route path="thoi-gian" element={<TimePage />} />
            <Route path="chuyen-muc" element={<CategoriesPage />} />
            <Route path="chat-luong" element={<QualityPage />} />
            <Route path="bai-bao" element={<ArticlesPage />} />
            <Route path="bai-bao/:articleId" element={<ArticleDetailPage />} />
            <Route path="nguon" element={<SourcesPage />} />
          </Route>
          <Route path="*" element={<NotFoundPage />} />
        </Route>
      </Route>
    </Routes>
  );
}
