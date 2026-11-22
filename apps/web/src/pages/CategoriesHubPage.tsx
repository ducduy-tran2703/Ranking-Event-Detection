import { Link } from "react-router";
import { useEventStats } from "../api/queries";
import { EventErrorBox } from "../components/EventBits";
import { Empty, Loading } from "../components/Status";
import { fmtInt } from "../lib/format";
import { useTitle } from "../lib/useTitle";

/** Chuyên mục: chuyên mục chính của các sự kiện ≥ 2 bài (đã gộp cách viết giữa các báo) → danh sách sự kiện đã lọc. */
export function CategoriesHubPage() {
  useTitle("Chuyên mục");
  const stats = useEventStats();
  const max = Math.max(1, ...(stats.data?.chuyen_muc.map((c) => c.n) ?? [1]));
  return (
    <div className="page">
      <div className="page-head rise">
        <h1>Chuyên mục</h1>
        <p>Chuyên mục chính của mỗi sự kiện là chuyên mục gặp nhiều nhất trong các bài của nó (gộp cách viết khác nhau giữa
          các báo, ví dụ “Y tế” và “Sức khỏe”). Chỉ tính sự kiện có từ 2 bài.</p>
      </div>
      {stats.isPending && <Loading lines={4} h={56} />}
      {stats.error && <EventErrorBox error={stats.error} onRetry={() => stats.refetch()} />}
      {stats.data && stats.data.chuyen_muc.length === 0 && <Empty title="Chưa có chuyên mục nào." />}
      {stats.data && stats.data.chuyen_muc.length > 0 && (
        <ul className="cat-list" data-testid="category-grid">
          {stats.data.chuyen_muc.map((c) => (
            <li key={c.category}>
              <Link to={`/events?category=${encodeURIComponent(c.category)}`}>
                <span className="name">{c.category}</span>
                <span className="n">{fmtInt(c.n)} sự kiện</span>
                <span className="heat"><span style={{ width: `${(c.n / max) * 100}%` }} /></span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
