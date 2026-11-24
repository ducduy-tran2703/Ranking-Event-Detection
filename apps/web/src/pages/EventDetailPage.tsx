import { useState, type CSSProperties, type FormEvent } from "react";
import { Link, useLocation, useParams } from "react-router";
import {
  useBookmarks, useCurrentUser, useFollows, useSubmitFeedback, useToggleBookmark, useToggleFollow,
} from "../api/accountQueries";
import { AUTH_MOCK } from "../api/auth";
import type { EventDetail } from "../api/client";
import type { FeedbackKind, Snapshot } from "../api/me";
import { useEvent } from "../api/queries";
import { EventErrorBox, NameSourceBadge } from "../components/EventBits";
import { HourBars } from "../components/HourBars";
import { IconArrowLeft, IconBell, IconBookmark, IconExternal, IconFlag, IconLink } from "../components/Icons";
import { SourceStrip } from "../components/SourceStrip";
import { useToast } from "../components/Layouts";
import { Loading } from "../components/Status";
import { fmtInt, fmtShort, vnClock } from "../lib/format";
import { chatHref, loginHref } from "../lib/routes";
import { sourceMeta } from "../lib/sources";
import { useTitle } from "../lib/useTitle";

const delay = (s: number): CSSProperties => ({ animationDelay: `${s}s` });
const FIRST_ARTICLES = 10;
const KINDS: { value: FeedbackKind; label: string }[] = [
  { value: "wrong_name", label: "Tên không đúng nội dung" },
  { value: "stray_article", label: "Có bài không thuộc sự kiện này" },
  { value: "duplicate", label: "Trùng với một sự kiện khác" },
  { value: "other", label: "Lý do khác" },
];

export function EventDetailPage() {
  const { eventId = "" } = useParams();
  const ev = useEvent(eventId);
  useTitle(ev.data?.ten ?? (ev.error ? "Không tìm thấy sự kiện" : "Sự kiện"));
  return (
    <div className="page">
      {ev.isPending && <Loading lines={6} h={28} label="Đang tải sự kiện…" />}
      {ev.error && (
        <>
          <EventErrorBox error={ev.error} onRetry={() => ev.refetch()} />
          <Link to="/events" className="btn-ghost" style={{ alignSelf: "flex-start" }}><IconArrowLeft /> Danh sách sự kiện</Link>
        </>
      )}
      {ev.data && <EventBody data={ev.data} />}
    </div>
  );
}

async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    try {                                                     // trình duyệt cũ / không phải ngữ cảnh an toàn
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.setAttribute("readonly", "");
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      const ok = document.execCommand("copy");
      document.body.removeChild(ta);
      return ok;
    } catch {
      return false;
    }
  }
}

function EventBody({ data }: { data: EventDetail }) {
  const loc = useLocation();
  const { data: user } = useCurrentUser();
  const follows = useFollows();
  const saved = useBookmarks();
  const toggleFollow = useToggleFollow();
  const toggleSave = useToggleBookmark();
  const toast = useToast();
  const [reportOpen, setReportOpen] = useState(false);
  const [chart, setChart] = useState<"diem" | "so_bai">("diem");
  const [allArticles, setAllArticles] = useState(false);

  const snap: Snapshot = { event_id: data.event_id, ten: data.ten, size: data.size, n_sources: data.n_sources,
                           chuyen_muc: data.chuyen_muc_chinh };
  const isFollowing = !!follows.data?.some((f) => f.event_id === data.event_id);
  const isSaved = !!saved.data?.some((b) => b.event_id === data.event_id);
  const login = loginHref(loc.pathname);
  const ranks = data.chuoi.filter((p) => p.hang != null).map((p) => p.hang!);
  const bestRank = ranks.length ? Math.min(...ranks) : null;
  const maxN = Math.max(...data.sources.map((s) => s.n), 1);
  const arts = allArticles ? data.bai : data.bai.slice(0, FIRST_ARTICLES);

  const onCopy = async () => toast.show((await copyText(window.location.href))
    ? "Đã sao chép liên kết" : "Không sao chép được — hãy chép địa chỉ trên thanh trình duyệt");

  return (
    <>
      {toast.node}
      <section aria-labelledby="h-ev" className="ev-hero rise">
        <div className="stack">
          <nav aria-label="Vị trí" className="crumbs">
            <Link to="/">Xu hướng</Link><span aria-hidden="true">/</span>
            <Link to="/events">Sự kiện</Link>
            {data.chuyen_muc_chinh && (
              <><span aria-hidden="true">/</span>
                <Link to={`/events?category=${encodeURIComponent(data.chuyen_muc_chinh)}`}>{data.chuyen_muc_chinh}</Link></>
            )}
          </nav>
          <div className="inline">
            <span className="tag solid">{data.n_sources} báo cùng đưa tin</span>
            <NameSourceBadge source={data.nguon_ten} long />
          </div>
          <h1 id="h-ev">{data.ten}</h1>
          <SourceStrip sources={data.sources} total={data.size} />
          {data.ten_bi_an && (
            <p className="small" style={{ color: "var(--warn)" }}>
              Tên mô hình của sự kiện này đang ẩn (cửa sổ tập test đặt tên) — đang hiển thị tiêu đề bài đại diện.
            </p>
          )}
          <div className="inline" style={{ gap: 10 }}>
            {user ? (
              <button type="button" className="btn" aria-pressed={isFollowing} disabled={toggleFollow.isPending}
                      onClick={() => toggleFollow.mutate({ ev: snap, on: !isFollowing })}>
                <IconBell /> {isFollowing ? "Đang theo dõi" : "Theo dõi diễn biến"}
              </button>
            ) : (
              <Link to={login} className="btn"><IconBell /> Theo dõi diễn biến</Link>
            )}
            {user ? (
              <button type="button" className="btn-ghost" aria-pressed={isSaved} disabled={toggleSave.isPending}
                      onClick={() => toggleSave.mutate({ ev: snap, on: !isSaved })}>
                <IconBookmark /> {isSaved ? "Đã lưu" : "Lưu"}
              </button>
            ) : (
              <Link to={login} className="btn-ghost"><IconBookmark /> Lưu</Link>
            )}
            <button type="button" className="btn-ghost" onClick={onCopy}><IconLink /> Sao chép liên kết</button>
            <Link to={chatHref({ q: `Diễn biến chính của sự kiện “${data.ten}” là gì?`, from: vnClock(data.first_seen).date,
                                to: vnClock(data.last_seen).date })} className="btn-ghost">Hỏi về sự kiện này</Link>
            <button type="button" className="btn-ghost danger" aria-expanded={reportOpen} aria-controls="bao-sai"
                    onClick={() => setReportOpen(!reportOpen)}><IconFlag /> Báo sai</button>
          </div>
          {(toggleFollow.error || toggleSave.error) && (
            <p className="form-error" role="alert">
              {toggleFollow.error ? "Không đổi được theo dõi" : "Không lưu được"}: {(toggleFollow.error ?? toggleSave.error)!.message}
            </p>
          )}
          <dl className="ev-stats">
            <div className="stat"><dt>Số bài</dt><dd>{fmtInt(data.size)}</dd></div>
            <div className="stat"><dt>Hạng cao nhất</dt><dd className="accent">{bestRank ? `#${bestRank}` : "—"}</dd></div>
            <div className="stat"><dt>Giờ trong top 10</dt><dd>{data.so_gio_trong_top10}</dd></div>
            <div className="stat"><dt>Diễn ra</dt><dd className="text"><span className="nowrap">{fmtShort(data.first_seen)}</span> đến <span className="nowrap">{fmtShort(data.last_seen)}</span></dd></div>
          </dl>
        </div>
      </section>

      {reportOpen && <ReportForm data={data} onClose={() => setReportOpen(false)} />}

      <div className="split">
        <div className="main">
          <section aria-labelledby="h-chart" className="card rise" style={delay(.1)}>
            <div className="row-between" style={{ marginBottom: 8 }}>
              <h2 id="h-chart">{chart === "diem" ? "Độ nóng theo giờ" : "Số bài theo giờ"}</h2>
              <div className="seg" role="group" aria-label="Chọn đại lượng">
                <button type="button" aria-pressed={chart === "diem"} onClick={() => setChart("diem")}>Độ nóng</button>
                <button type="button" aria-pressed={chart === "so_bai"} onClick={() => setChart("so_bai")}>Số bài</button>
              </div>
            </div>
            <HourBars points={data.chuoi} kind={chart} />
            {data.chuoi_bi_cat && <p className="hint">Sự kiện kéo dài — chỉ vẽ phần đầu.</p>}
            <p className="hint">Điểm độ nóng là công thức (vận tốc đưa tin, mỗi bài giảm một nửa sau 3 giờ), chưa được đánh giá.</p>
          </section>

          <section aria-labelledby="h-arts" className="card rise" style={{ ...delay(.15), paddingBottom: 14 }}>
            <h2 id="h-arts" style={{ marginBottom: 4 }}>Diễn biến qua các bài viết</h2>
            <p className="hint" style={{ marginBottom: 14 }}>Xếp theo giờ đăng. Mở bài để đọc trên trang của báo.</p>
            <ol className="art-list" data-testid="article-list">
              {arts.map((a) => {
                const m = sourceMeta(a.source);
                const safeUrl = a.url && /^https?:\/\//i.test(a.url) ? a.url : undefined;
                return (
                  <li key={a.article_id}>
                    <span className="art-ini" aria-hidden="true" style={{ background: m.bg, color: m.fg }}>{m.ini}</span>
                    <div className="body">
                      <div className="meta"><b>{m.name}</b> · {fmtShort(a.published_at)}{a.category && <> · {a.category}</>}</div>
                      {safeUrl ? (
                        <a href={safeUrl} target="_blank" rel="noopener noreferrer" className="title">
                          {a.title || "(không có tiêu đề)"}<IconExternal />
                          <span className="sr-only"> (mở bài gốc trên {m.name}, tab mới)</span>
                        </a>
                      ) : (
                        <span className="title">{a.title || "(không có tiêu đề)"}</span>
                      )}
                      {a.is_medoid && <span className="tag" style={{ alignSelf: "flex-start" }}>Bài đại diện</span>}
                    </div>
                  </li>
                );
              })}
            </ol>
            {data.bai.length > FIRST_ARTICLES && (
              <button type="button" className="more-link" style={{ margin: "6px 0 0", width: "100%" }} aria-expanded={allArticles}
                      onClick={() => setAllArticles(!allArticles)}>
                {allArticles ? "Thu gọn" : `Xem thêm ${data.bai.length - FIRST_ARTICLES} bài`}
              </button>
            )}
          </section>
        </div>

        <aside className="side">
          <section aria-labelledby="h-src" className="card lift rise" style={delay(.2)}>
            <h2 id="h-src" style={{ fontSize: 16, marginBottom: 14 }}>Báo đưa tin</h2>
            <ul className="src-bars">
              {data.sources.map((s) => (
                <li key={s.source}>
                  <span>{sourceMeta(s.source).name}</span>
                  <span className="track" aria-hidden="true"><span style={{ width: `${(s.n / maxN) * 100}%`, background: sourceMeta(s.source).fg }} /></span>
                  <span className="n" aria-label={`${s.n} bài`}>{s.n}</span>
                </li>
              ))}
            </ul>
          </section>
          {data.chuyen_muc.length > 0 && (
            <section aria-labelledby="h-cat2" className="card lift rise" style={delay(.25)}>
              <h2 id="h-cat2" style={{ fontSize: 16, marginBottom: 10 }}>Chuyên mục của các bài</h2>
              <div className="chips">
                {data.chuyen_muc.map((c) => <span key={c.category} className="tag" style={{ fontSize: 13.5, padding: "6px 12px", fontWeight: 400 }}>
                  {c.category} · <b>{c.n}</b></span>)}
              </div>
            </section>
          )}
          <section aria-labelledby="h-follow" className="soft-panel">
            <h2 id="h-follow">Nhận tin khi có diễn biến mới</h2>
            <p>Theo dõi để được báo khi sự kiện có thêm bài, thay vì phải tự quay lại kiểm tra.</p>
            {user ? (
              <button type="button" className="btn white" aria-pressed={isFollowing} disabled={toggleFollow.isPending}
                      onClick={() => toggleFollow.mutate({ ev: snap, on: !isFollowing })}>
                {isFollowing ? "Bỏ theo dõi" : "Theo dõi sự kiện này"}
              </button>
            ) : (
              <Link to={login} className="btn white">Đăng nhập để theo dõi</Link>
            )}
            {/* cùng lỗi đã có role=alert ở đầu trang; ở đây chỉ nhắc lại cạnh nút, không đọc lần hai */}
            {toggleFollow.error && <p className="form-error">Không đổi được theo dõi: {toggleFollow.error.message}</p>}
          </section>
        </aside>
      </div>
    </>
  );
}

function ReportForm({ data, onClose }: { data: EventDetail; onClose: () => void }) {
  const [kind, setKind] = useState<FeedbackKind>("wrong_name");
  const [note, setNote] = useState("");
  const submit = useSubmitFeedback();
  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    submit.mutate({ eventId: data.event_id, kind, note: note.trim(), event_name: data.ten });
  };
  if (submit.isSuccess) {
    return (
      <div id="bao-sai" className="report drop" role="status">
        <p className="form-ok">
          Cảm ơn bạn! Báo sai đã được ghi lại.
          {AUTH_MOCK && " (Bản xem trước: chỉ lưu trên trình duyệt này, quản trị viên xem ở Quản trị › Báo sai.)"}
        </p>
        <button type="button" className="btn-ghost sm" style={{ alignSelf: "flex-start" }} onClick={onClose}>Đóng</button>
      </div>
    );
  }
  return (
    <form id="bao-sai" className="report drop" onSubmit={onSubmit} aria-label="Báo sai sự kiện">
      <fieldset style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <legend>Sự kiện này sai ở đâu?</legend>
        {KINDS.map((k) => (
          <label key={k.value} className="check" style={{ alignItems: "center" }}>
            <input type="radio" name="kind" value={k.value} checked={kind === k.value} onChange={() => setKind(k.value)} />
            {k.label}
          </label>
        ))}
      </fieldset>
      <div className="field-group">
        <label htmlFor="report-note">Ghi chú (không bắt buộc)</label>
        <textarea id="report-note" className="field" rows={3} maxLength={1000} placeholder="Ví dụ: tên đúng nên là…"
                  value={note} onChange={(e) => setNote(e.target.value)} />
      </div>
      {submit.error && <p className="form-error" role="alert">Không gửi được: {submit.error.message}</p>}
      <div className="inline" style={{ gap: 10 }}>
        <button type="submit" className="btn" disabled={submit.isPending}>{submit.isPending ? "Đang gửi…" : "Gửi báo sai"}</button>
        <button type="button" className="btn-ghost" onClick={onClose}>Huỷ</button>
        <span className="small muted">Biên tập viên sẽ xem và sửa. Không cần đăng nhập.</span>
      </div>
    </form>
  );
}
