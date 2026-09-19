import { useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router";
import type { ArticleQuery } from "../api/client";
import { useArticles, useMeta } from "../api/queries";
import { Pagination } from "../components/Pagination";
import { SourceBadge } from "../components/SourceBadge";
import { ErrorBox, Loading } from "../components/Status";

const PAGE_SIZE = 20;

export function ArticlesPage() {
  // Bộ lọc nằm trên URL (?source=tuoitre&q=bão&page=2):
  // tải lại trang không mất bộ lọc, nút Back hoạt động, gửi link cho người khác được.
  const [params, setParams] = useSearchParams();
  const source = params.get("source") ?? "";
  const q = params.get("q") ?? "";
  const page = Number(params.get("page") ?? "1") || 1;
  const [draft, setDraft] = useState(q);

  const meta = useMeta();
  const query: ArticleQuery = { page, page_size: PAGE_SIZE, sort: "newest" };
  if (source) query.source = source;
  if (q) query.q = q;
  const articles = useArticles(query);

  function update(next: Record<string, string>) {
    const merged = new URLSearchParams(params);
    for (const [k, v] of Object.entries(next)) {
      if (v) merged.set(k, v);
      else merged.delete(k);
    }
    setParams(merged);
  }

  function onSearch(e: FormEvent) {
    e.preventDefault();
    update({ q: draft.trim(), page: "" });
  }

  return (
    <>
      <h1>Bài báo</h1>
      <form className="filters" onSubmit={onSearch}>
        <select value={source} onChange={(e) => update({ source: e.target.value, page: "" })}>
          <option value="">Tất cả nguồn</option>
          {meta.data?.sources.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        <input
          type="search"
          value={draft}
          placeholder="Tìm trong tiêu đề và sapo"
          onChange={(e) => setDraft(e.target.value)}
        />
        <button type="submit">Tìm</button>
      </form>

      {articles.isPending && <Loading />}
      {articles.error && <ErrorBox error={articles.error} />}
      {articles.data && (
        <>
          <p className="muted">{articles.data.total.toLocaleString("vi-VN")} bài</p>
          <ul className="articles">
            {articles.data.items.map((a) => (
              <li key={a.article_id}>
                <div className="meta">
                  <SourceBadge source={a.source} /> · {a.category ?? "—"} · {a.published_at ?? "—"}
                </div>
                <Link to={`/articles/${a.article_id}`} className="title">{a.title ?? "(không có tiêu đề)"}</Link>
                <p className="muted">{a.sapo}</p>
              </li>
            ))}
          </ul>
          <Pagination
            page={articles.data.page}
            pageSize={articles.data.page_size}
            total={articles.data.total}
            onChange={(p) => update({ page: String(p) })}
          />
        </>
      )}
    </>
  );
}
