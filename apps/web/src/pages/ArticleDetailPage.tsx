import { Link, useNavigate, useParams } from "react-router";
import { useArticle } from "../api/queries";
import { SourceBadge } from "../components/SourceBadge";
import { ErrorBox, Loading } from "../components/Status";
import { fmtInt } from "../lib/format";

export function ArticleDetailPage() {
  const { articleId = "" } = useParams();
  const navigate = useNavigate();
  const { data, isPending, error } = useArticle(articleId);
  if (isPending) return <Loading />;
  if (error) return <ErrorBox error={error} />;

  const safeUrl = /^https?:\/\//i.test(data.url) ? data.url : undefined;
  return (
    <article className="detail">
      <button className="ghost" onClick={() => navigate(-1)}>‹ Quay lại</button>
      <div className="meta">
        <SourceBadge source={data.source} /> · {data.category ?? "—"} · {data.published_at ?? "—"} ·{" "}
        {fmtInt(data.n_words)} từ
      </div>
      <h1>{data.title}</h1>
      <p className="sapo">{data.sapo}</p>
      <dl className="fields">
        <dt>Tác giả</dt><dd>{data.author ?? <span className="badge warn">không có</span>}</dd>
        <dt>Bài gốc</dt>
        <dd>{safeUrl ? <a href={safeUrl} target="_blank" rel="noopener noreferrer">{data.url}</a> : data.url}</dd>
        <dt>article_id</dt><dd><code>{data.article_id}</code></dd>
        <dt>source gốc</dt><dd><code>{data.source_raw}</code></dd>
        <dt>published_at gốc</dt><dd><code>{data.published_at_raw}</code></dd>
        <dt>File trên kho</dt><dd><code>{data.source_file}</code></dd>
        <dt>Cùng nguồn</dt><dd><Link to={`/articles?source=${data.source}`}>Xem các bài khác của {data.source}</Link></dd>
      </dl>
      {/* React tự thoát ký tự đặc biệt khi hiển thị chuỗi: nội dung cào về không thể chèn mã */}
      <div className="content">{data.content_text || "(thân bài rỗng)"}</div>
    </article>
  );
}
