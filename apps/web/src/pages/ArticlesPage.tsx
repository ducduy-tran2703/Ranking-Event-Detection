import { useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router";
import type { ArticleQuery } from "../api/client";
import { useArticles, useMeta } from "../api/queries";
import { FilterBar, useUrlFilter } from "../components/FilterBar";
import { Pagination } from "../components/Pagination";
import { SourceBadge } from "../components/SourceBadge";
import { ErrorBox, Loading } from "../components/Status";
import { fmtInt } from "../lib/format";
import { kho } from "../lib/routes";

const PAGE_SIZE = 20;
const ISSUE_LABELS: Record<string, string> = {
  missing_author: "Thiếu tác giả", missing_sapo: "Thiếu sapo", empty_content: "Thân bài rỗng", short_content: "Quá ngắn",
  bad_date: "Ngày hỏng", future_date: "Ngày tương lai", duplicate_url: "URL trùng", duplicate_id: "article_id trùng",
};
const SORTS = { newest: "Mới nhất", oldest: "Cũ nhất", longest: "Dài nhất", shortest: "Ngắn nhất" } as const;

export function ArticlesPage() {
  // Mọi bộ lọc nằm trên URL: tải lại trang không mất, nút Back hoạt động, gửi link cho người khác được.
  const { filter, params, update, setPage } = useUrlFilter();
  const page = Number(params.get("page") ?? "1") || 1;
  const sort = (params.get("sort") ?? "newest") as keyof typeof SORTS;
  const [draft, setDraft] = useState(filter.q ?? "");
  useEffect(() => setDraft(filter.q ?? ""), [filter.q]);

  const meta = useMeta();
  const categories = [...new Set((meta.data?.categories ?? [])
    .filter((c) => !filter.source || c.source === filter.source)
    .map((c) => c.category).filter((c): c is string => !!c))].sort((a, b) => a.localeCompare(b, "vi"));

  const query: ArticleQuery = { ...filter, page, page_size: PAGE_SIZE, sort };
  const articles = useArticles(query);

  function goPage(p: number) {
    setPage(p);
    window.scrollTo({ top: 0 });
  }

  function onSearch(e: FormEvent) {
    e.preventDefault();
    update({ q: draft.trim() });
  }

  return (
    <>
      <h1>Bài báo</h1>
      <FilterBar>
        <label>
          Chuyên mục
          <select value={filter.category ?? ""} onChange={(e) => update({ category: e.target.value })}>
            <option value="">Tất cả</option>
            {categories.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </label>
        <label>
          Lỗi
          <select value={filter.issue ?? ""} onChange={(e) => update({ issue: e.target.value })}>
            <option value="">Không lọc</option>
            {Object.entries(ISSUE_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </label>
        <label>
          Sắp xếp
          <select value={sort} onChange={(e) => update({ sort: e.target.value })}>
            {Object.entries(SORTS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </label>
      </FilterBar>
      <form className="search" onSubmit={onSearch}>
        <input type="search" value={draft} placeholder="Tìm trong tiêu đề và sapo, rồi bấm Enter"
               onChange={(e) => setDraft(e.target.value)} />
        <button type="submit">Tìm</button>
      </form>

      {articles.isPending && <Loading />}
      {articles.error && <ErrorBox error={articles.error} />}
      {articles.data && (
        <>
          <p className="muted">{fmtInt(articles.data.total)} bài khớp bộ lọc</p>
          <ul className="articles">
            {articles.data.items.map((a) => (
              <li key={a.article_id}>
                <div className="meta">
                  <SourceBadge source={a.source} /> · {a.category ?? "—"} · {a.published_at ?? "—"} ·{" "}
                  {fmtInt(a.n_words)} từ{!a.author && <> · <span className="badge warn">thiếu tác giả</span></>}
                </div>
                <Link to={kho.article(a.article_id)} className="title">{a.title ?? "(không có tiêu đề)"}</Link>
                <p className="muted">{a.sapo}</p>
              </li>
            ))}
          </ul>
          <Pagination page={articles.data.page} pageSize={articles.data.page_size}
                      total={articles.data.total} onChange={goPage} />
        </>
      )}
    </>
  );
}
