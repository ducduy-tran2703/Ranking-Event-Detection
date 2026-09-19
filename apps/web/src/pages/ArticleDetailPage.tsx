import { Link, useParams } from "react-router";
import { useArticle } from "../api/queries";
import { SourceBadge } from "../components/SourceBadge";
import { ErrorBox, Loading } from "../components/Status";

export function ArticleDetailPage() {
  const { articleId = "" } = useParams();
  const { data, isPending, error } = useArticle(articleId);
  if (isPending) return <Loading />;
  if (error) return <ErrorBox error={error} />;

  const safeUrl = /^https?:\/\//i.test(data.url) ? data.url : undefined;
  return (
    <article className="detail">
      <Link to="/articles">‹ Quay lại danh sách</Link>
      <div className="meta">
        <SourceBadge source={data.source} /> · {data.category ?? "—"} · {data.published_at ?? "—"} ·{" "}
        {data.n_words.toLocaleString("vi-VN")} từ
      </div>
      <h1>{data.title}</h1>
      <p className="sapo">{data.sapo}</p>
      <p className="muted">
        Tác giả: {data.author ?? "—"}
        {safeUrl && <> · <a href={safeUrl} target="_blank" rel="noopener noreferrer">Xem bài gốc</a></>}
      </p>
      {/* React tự thoát ký tự đặc biệt khi hiển thị chuỗi: nội dung cào về không thể chèn mã */}
      <div className="content">{data.content_text || "(thân bài rỗng)"}</div>
    </article>
  );
}
