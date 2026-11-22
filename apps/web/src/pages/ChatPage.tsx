import { Fragment, useEffect, useMemo, useRef, useState, type FormEvent, type KeyboardEvent, type ReactNode } from "react";
import { Link, useLocation, useNavigate, useParams, useSearchParams } from "react-router";
import { useCurrentUser } from "../api/accountQueries";
import { isPending, type RagMessage, type RagSource, type RagStatus } from "../api/rag";
import { useAsk, useCancel, useConversation, useConversations, useDeleteConversation, useRagStatus } from "../api/ragQueries";
import { ConfirmBox } from "../components/ConfirmBox";
import { IconClose, IconLink, IconSpinner } from "../components/Icons";
import { SourceChip } from "../components/SourceBadge";
import { Loading, errorMessage } from "../components/Status";
import { fmtDateTime, fmtShort, timeAgo } from "../lib/format";
import { eventHref, loginHref } from "../lib/routes";
import { sourceName } from "../lib/sources";

const MAX_LEN = 2048;
/** Câu hỏi mẫu — mỗi câu kèm khoảng ngày có tin trong kho (kiểm 07/11/2026). */
const EXAMPLES = [
  { q: "U23 Việt Nam thắng U23 Philippines với tỷ số bao nhiêu?", from: "2026-09-18", to: "2026-09-19" },
  { q: "Lượt về chung kết ASEAN Cup 2026 giữa Việt Nam và Thái Lan kết thúc ra sao?", from: "2026-08-25", to: "2026-08-27" },
  { q: "Lũ quét ở biên giới Nepal – Trung Quốc gây thiệt hại thế nào?", from: "2026-08-27", to: "2026-08-29" },
  { q: "U20 Việt Nam thua U20 Palestine như thế nào?", from: "2026-09-02", to: "2026-09-04" },
];

interface Filters { source: string; from: string; to: string }
const NO_FILTERS: Filters = { source: "", from: "", to: "" };

const fmtDate = (iso: string | null | undefined) => (iso ? iso.split("-").reverse().join("/") : "");

export function ChatPage() {
  const { conversationId } = useParams();
  const id = conversationId && /^\d+$/.test(conversationId) ? Number(conversationId) : null;
  const { data: user, isPending: userPending } = useCurrentUser();
  const status = useRagStatus();
  const loc = useLocation();

  useEffect(() => { document.title = "Hỏi đáp tin tức · EventRank"; }, []);

  if (userPending) return <div className="page"><Loading lines={4} /></div>;
  return (
    <div className="page chat-page">
      <div className="chat">
        {user && <ChatSidebar activeId={id} />}
        <section className="chat-main card" aria-label="Hỏi đáp">
          {!user ? (
            <div className="chat-thread guest">
              <Welcome status={status.data}>
                <div className="info-box">
                  <h2>Đăng nhập để đặt câu hỏi</h2>
                  <p className="muted">Mỗi câu hỏi chạy mô hình ngôn ngữ trên GPU, nên chỉ thành viên đã đăng nhập mới hỏi được.</p>
                  <div className="inline" style={{ marginTop: 10 }}>
                    <Link to={loginHref(loc.pathname + loc.search)} className="btn sm">Đăng nhập</Link>
                    <Link to="/register" className="btn-ghost sm">Tạo tài khoản</Link>
                  </div>
                </div>
              </Welcome>
            </div>
          ) : (
            <Conversation key={id ?? "moi"} id={id} status={status.data} statusError={status.error} />
          )}
        </section>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ danh sách cuộc trò chuyện
function ChatSidebar({ activeId }: { activeId: number | null }) {
  const list = useConversations();
  const del = useDeleteConversation();
  const navigate = useNavigate();
  const [confirm, setConfirm] = useState<number | null>(null);
  const items = list.data ?? [];
  const current = items.find((c) => c.conversation_id === activeId);

  const remove = (cid: number) => del.mutate(cid, {
    onSuccess: () => { setConfirm(null); if (cid === activeId) navigate("/hoi-dap"); },
  });

  const body = (
    <>
      <Link to="/hoi-dap" className="btn sm pill chat-new">+ Cuộc trò chuyện mới</Link>
      {list.isPending ? <Loading lines={3} h={14} /> : list.error ? (
        <p className="small muted" role="alert">{errorMessage(list.error)}</p>
      ) : items.length === 0 ? (
        <p className="small muted">Chưa có cuộc trò chuyện nào.</p>
      ) : (
        <ul className="chat-convs">
          {items.map((c) => (
            <li key={c.conversation_id} className={c.conversation_id === activeId ? "active" : undefined}>
              <Link to={`/hoi-dap/${c.conversation_id}`} aria-current={c.conversation_id === activeId ? "page" : undefined}>
                <span className="chat-conv-title">{c.title}</span>
                <span className="chat-conv-meta">
                  {c.last_status && isPending({ status: c.last_status }) && <IconSpinner size={12} className="spin" />}
                  {c.n_messages} câu · {timeAgo(c.updated_at)}
                </span>
              </Link>
              <button type="button" className="chat-conv-del" aria-label={`Xoá cuộc trò chuyện “${c.title}”`}
                      onClick={() => setConfirm(c.conversation_id)}><IconClose size={14} /></button>
              {confirm === c.conversation_id && (
                <ConfirmBox title="Xoá cuộc trò chuyện này?" confirmLabel="Xoá" busy={del.isPending}
                            onConfirm={() => remove(c.conversation_id)} onCancel={() => setConfirm(null)}>
                  Mọi câu hỏi và câu trả lời trong đó sẽ mất, không khôi phục được.
                </ConfirmBox>
              )}
            </li>
          ))}
        </ul>
      )}
    </>
  );
  return (
    <aside className="chat-side card" aria-label="Các cuộc trò chuyện">
      <div className="chat-side-desk stack">{body}</div>
      <details className="chat-side-mobile">
        <summary>{current ? current.title : "Các cuộc trò chuyện"} <span className="muted small">({items.length})</span></summary>
        <div className="stack" style={{ marginTop: 10 }}>{body}</div>
      </details>
    </aside>
  );
}

// ------------------------------------------------------------------ một cuộc trò chuyện
function Conversation({ id, status, statusError }: { id: number | null; status?: RagStatus; statusError: unknown }) {
  const conv = useConversation(id);
  const ask = useAsk();
  const stop = useCancel();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const [text, setText] = useState(() => params.get("q") ?? "");
  const [filters, setFilters] = useState<Filters>(() => ({
    source: params.get("source") ?? "", from: params.get("from") ?? "", to: params.get("to") ?? "",
  }));
  const [showFilters, setShowFilters] = useState(() => !!(params.get("from") || params.get("to") || params.get("source")));
  const threadEnd = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);

  const messages = conv.data?.messages ?? [];
  const pending = messages.find(isPending);
  const waiting = !!pending;
  const lastKey = messages.map((m) => `${m.message_id}:${m.status}`).join(",");

  useEffect(() => {                                   // ?q=… chỉ dùng để điền sẵn, xoá khỏi địa chỉ
    if (params.has("q") || params.has("from") || params.has("to") || params.has("source")) setParams({}, { replace: true });
  }, []);
  useEffect(() => { threadEnd.current?.scrollIntoView({ block: "end", behavior: "smooth" }); }, [lastKey]);
  useEffect(() => {                                   // lấy bộ lọc của câu cuối khi mở lại cuộc trò chuyện cũ
    const last = messages[messages.length - 1];
    if (last && !text) setFilters({ source: last.filters.source ?? "", from: last.filters.date_from ?? "", to: last.filters.date_to ?? "" });
  }, [conv.data?.conversation.conversation_id]);

  const available = status ? status.available : true;   // chưa tải xong trạng thái thì không khoá khung nhập
  const remaining = status?.daily_limit != null && status.used_today != null ? status.daily_limit - status.used_today : null;
  const blocked = !available || waiting || ask.isPending || remaining === 0;

  const submit = (question: string, f: Filters) => {
    const q = question.trim();
    if (!q || blocked) return;
    ask.mutate({
      question: q, conversation_id: id ?? undefined,
      source: f.source || undefined, date_from: f.from || undefined, date_to: f.to || undefined,
    }, {
      onSuccess: (msg) => {
        setText("");
        if (id == null) navigate(`/hoi-dap/${msg.conversation_id}`, { replace: true });
      },
    });
  };
  const onSubmit = (e: FormEvent) => { e.preventDefault(); submit(text, filters); };
  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); submit(text, filters); }
  };
  const retry = (m: RagMessage) => submit(m.question, {
    source: m.filters.source ?? "", from: m.filters.date_from ?? "", to: m.filters.date_to ?? "",
  });
  const cancel = () => { if (pending && !stop.isPending) stop.mutate(pending.message_id); };
  const pickExample = (ex: typeof EXAMPLES[number]) => {
    setText(ex.q);
    setFilters({ source: "", from: ex.from, to: ex.to });
    setShowFilters(true);
    input.current?.focus();
  };

  return (
    <>
      <div className="chat-thread">
        {id == null ? (
          <Welcome status={status}>
            <div className="stack">
              <h2 className="small muted chat-label">Thử hỏi</h2>
              <div className="chips">
                {EXAMPLES.map((ex) => (
                  <button key={ex.q} type="button" className="chip" onClick={() => pickExample(ex)}>{ex.q}</button>
                ))}
              </div>
            </div>
          </Welcome>
        ) : conv.isPending ? <Loading lines={4} /> : conv.error ? (
          <div className="error-box" role="alert">
            <strong>Không mở được cuộc trò chuyện.</strong>
            <span className="detail">{errorMessage(conv.error)}</span>
            <Link to="/hoi-dap" className="btn-ghost sm">Cuộc trò chuyện mới</Link>
          </div>
        ) : (
          <ol className="chat-msgs" aria-live="polite">
            {messages.map((m) => (
              <li key={m.message_id} className="chat-turn">
                <UserBubble m={m} />
                <AssistantBubble m={m} onRetry={() => retry(m)} canRetry={!blocked} onStop={cancel} stopping={stop.isPending} />
              </li>
            ))}
          </ol>
        )}
        <div ref={threadEnd} />
      </div>

      <form className="chat-composer" onSubmit={onSubmit} aria-label="Đặt câu hỏi">
        {!!statusError && <p className="form-error" role="alert">Không kiểm tra được trạng thái hỏi đáp: {errorMessage(statusError)}</p>}
        {status && !available && (
          <div className="chat-unavailable" role="status">
            <strong>Hỏi đáp tạm thời chưa dùng được.</strong>
            <ul>{status.problems.map((p) => <li key={p}>{p}</li>)}</ul>
          </div>
        )}
        {showFilters && <FilterRow status={status} value={filters} onChange={setFilters} />}
        <div className="chat-input">
          <label htmlFor="chat-q" className="sr-only">Câu hỏi</label>
          <textarea id="chat-q" ref={input} rows={2} maxLength={MAX_LEN} value={text} disabled={!available}
                    placeholder={waiting ? "Đang chờ câu trả lời trước…" : "Hỏi về một sự kiện trong kho tin, ví dụ: diễn biến, kết quả, con số…"}
                    onChange={(e) => setText(e.target.value)} onKeyDown={onKey} />
          {waiting ? (
            <button type="button" className="btn pill chat-stop" onClick={cancel} disabled={stop.isPending}
                    aria-label="Dừng câu hỏi đang trả lời">
              {stop.isPending ? <IconSpinner className="spin" /> : <span className="chat-stop-icon" aria-hidden="true" />} Dừng
            </button>
          ) : (
            <button type="submit" className="btn" disabled={blocked || !text.trim()}>
              {ask.isPending ? <><IconSpinner className="spin" /> Đang gửi</> : "Gửi"}
            </button>
          )}
        </div>
        <div className="chat-foot small muted">
          <button type="button" className="link-btn" aria-expanded={showFilters} onClick={() => setShowFilters(!showFilters)}>
            {showFilters ? "Ẩn bộ lọc" : "Lọc theo báo / ngày"}
          </button>
          {!showFilters && <FilterSummary f={filters} onClear={() => setFilters(NO_FILTERS)} />}
          <span className="chat-spacer" />
          {remaining != null && <span>Còn {Math.max(remaining, 0)}/{status?.daily_limit} câu trong 24 giờ</span>}
          <span className="hide-sm">Enter để gửi · Shift+Enter xuống dòng</span>
        </div>
        {ask.error && <p className="form-error" role="alert">{errorMessage(ask.error)}</p>}
        {stop.error && <p className="form-error" role="alert">{errorMessage(stop.error)}</p>}
      </form>
    </>
  );
}

function Welcome({ status, children }: { status?: RagStatus; children?: ReactNode }) {
  const s = status?.snapshot;
  return (
    <div className="chat-welcome">
      <h1>Hỏi đáp tin tức</h1>
      <p className="muted">
        Đặt câu hỏi bằng tiếng Việt về các sự kiện trong kho tin. Hệ thống tìm các đoạn báo liên quan (theo từ khoá và theo nghĩa),
        rồi để mô hình ngôn ngữ trả lời <strong>chỉ dựa trên các đoạn đó</strong>. Mỗi ý trong câu trả lời có trích dẫn nguyên văn và
        đường dẫn tới bài gốc.
      </p>
      <ul className="chat-facts">
        {s && s.articles > 0 && (
          <li>Kho: <strong className="tnum">{s.articles.toLocaleString("vi-VN")}</strong> bài từ {s.sources.length} báo;
            tin mới nhất đăng ngày <strong>{fmtDate(s.to_date)}</strong> — không có tin sau ngày này.</li>
        )}
        <li>Mỗi câu được trả lời <strong>riêng</strong>: trợ lý không nhớ câu trước, hãy hỏi đủ ý trong một câu.</li>
        <li>Câu về “hôm nay”, “mới nhất” cần chọn khoảng ngày; câu thống kê toàn kho (bao nhiêu bài…) không hỗ trợ.</li>
        <li>Lần hỏi đầu sau một lúc không dùng, mô hình phải khởi động trên GPU nên có thể mất vài phút.</li>
      </ul>
      {children}
    </div>
  );
}

function FilterRow({ status, value, onChange }: { status?: RagStatus; value: Filters; onChange: (f: Filters) => void }) {
  const s = status?.snapshot;
  return (
    <div className="chat-filters">
      <div className="field-group">
        <label htmlFor="chat-source" className="small">Báo</label>
        <select id="chat-source" className="field" value={value.source} onChange={(e) => onChange({ ...value, source: e.target.value })}>
          <option value="">Tất cả các báo</option>
          {(s?.sources ?? []).map((src) => <option key={src} value={src}>{sourceName(src)}</option>)}
        </select>
      </div>
      <div className="field-group">
        <label htmlFor="chat-from" className="small">Từ ngày</label>
        <input id="chat-from" type="date" className="field" value={value.from} min={s?.from_date ?? undefined}
               max={value.to || s?.to_date || undefined} onChange={(e) => onChange({ ...value, from: e.target.value })} />
      </div>
      <div className="field-group">
        <label htmlFor="chat-to" className="small">Đến ngày</label>
        <input id="chat-to" type="date" className="field" value={value.to} min={value.from || s?.from_date || undefined}
               max={s?.to_date ?? undefined} onChange={(e) => onChange({ ...value, to: e.target.value })} />
      </div>
      {(value.source || value.from || value.to) && (
        <button type="button" className="link-btn" onClick={() => onChange(NO_FILTERS)}>Bỏ lọc</button>
      )}
    </div>
  );
}

function FilterSummary({ f, onClear }: { f: Filters; onClear: () => void }) {
  if (!f.source && !f.from && !f.to) return null;
  return (
    <span className="inline">
      <FilterTags source={f.source} from={f.from} to={f.to} />
      <button type="button" className="link-btn" onClick={onClear}>Bỏ lọc</button>
    </span>
  );
}

function FilterTags({ source, from, to }: { source?: string | null; from?: string | null; to?: string | null }) {
  return (
    <>
      {source && <span className="tag outline">{sourceName(source)}</span>}
      {(from || to) && (
        <span className="tag outline">{from && to && from === to ? fmtDate(from) : `${fmtDate(from) || "…"} → ${fmtDate(to) || "…"}`}</span>
      )}
    </>
  );
}

// ------------------------------------------------------------------ tin nhắn
function UserBubble({ m }: { m: RagMessage }) {
  const f = m.filters;
  return (
    <div className="chat-bubble user">
      <p>{m.question}</p>
      {(f.source || f.date_from || f.date_to) && (
        <div className="inline chat-bubble-tags"><FilterTags source={f.source} from={f.date_from} to={f.date_to} /></div>
      )}
    </div>
  );
}

function Elapsed({ since }: { since: string }) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => { const t = window.setInterval(() => setNow(Date.now()), 1000); return () => window.clearInterval(t); }, []);
  const s = Math.max(0, Math.round((now - new Date(since).getTime()) / 1000));
  return <span className="tnum">{Math.floor(s / 60)}:{String(s % 60).padStart(2, "0")}</span>;
}

function AssistantBubble({ m, onRetry, canRetry, onStop, stopping }: {
  m: RagMessage; onRetry: () => void; canRetry: boolean; onStop: () => void; stopping: boolean;
}) {
  const stopBtn = (
    <button type="button" className="link-btn chat-stop-link" onClick={onStop} disabled={stopping}>
      {stopping ? "Đang dừng…" : "Dừng câu hỏi này"}
    </button>
  );
  if (m.status === "queued") {
    return (
      <div className="chat-bubble bot pending" role="status">
        <p><IconSpinner className="spin" /> Đang xếp hàng{m.queue_position && m.queue_position > 1 ? ` — vị trí ${m.queue_position}` : "…"}</p>
        {stopBtn}
      </div>
    );
  }
  if (m.status === "running") {
    return (
      <div className="chat-bubble bot pending" role="status">
        <p><IconSpinner className="spin" /> Đang tìm trong kho tin và soạn câu trả lời… {m.started_at && <Elapsed since={m.started_at} />}</p>
        <p className="small muted">Nếu mô hình vừa nghỉ, máy chủ cần khởi động GPU — lần đầu có thể mất vài phút. Bạn có thể rời trang và quay lại sau.</p>
        {stopBtn}
      </div>
    );
  }
  if (m.status === "cancelled") {
    return (
      <div className="chat-bubble bot info">
        <p className="muted">Đã dừng câu hỏi này.</p>
        <button type="button" className="btn-ghost sm" disabled={!canRetry} onClick={onRetry}>Hỏi lại</button>
      </div>
    );
  }
  if (m.status === "failed" || m.status === "invalid_generation") {
    return (
      <div className="chat-bubble bot warn" role="alert">
        <p><strong>{m.status === "failed" ? "Chưa trả lời được." : "Câu trả lời không qua được bước kiểm trích dẫn nên đã bị loại."}</strong></p>
        <p className="small">{m.status === "failed" ? m.error : m.answer}</p>
        <button type="button" className="btn-ghost sm" disabled={!canRetry} onClick={onRetry}>Hỏi lại</button>
      </div>
    );
  }
  if (m.status === "insufficient_evidence" || m.status === "unsupported_query") {
    return (
      <div className="chat-bubble bot info">
        <p>{m.answer}</p>
        <p className="small muted">
          {m.status === "unsupported_query"
            ? "Hãy hỏi về nội dung một sự kiện cụ thể, kèm khoảng ngày nếu hỏi về tin gần đây."
            : "Thử nêu rõ hơn (tên người, địa điểm, sự kiện) hoặc mở rộng / thu hẹp khoảng ngày và báo."}
        </p>
        <Meta m={m} />
      </div>
    );
  }
  return (
    <div className="chat-bubble bot">
      <AnswerText text={m.answer ?? ""} mid={m.message_id} />
      {m.degraded && <p className="small"><span className="tag warn">Chỉ dùng một cách tìm ({m.retrieval_mode === "bm25_only" ? "từ khoá" : "theo nghĩa"})</span></p>}
      <Sources sources={m.sources} mid={m.message_id} />
      <Meta m={m} />
    </div>
  );
}

function Meta({ m }: { m: RagMessage }) {
  return (
    <p className="chat-meta small muted">
      {fmtShort(m.finished_at ?? m.created_at)}{m.seconds != null && ` · ${m.seconds.toLocaleString("vi-VN")} giây`}
    </p>
  );
}

const citeId = (mid: number, n: number) => `nguon-${mid}-${n}`;

/** Câu trả lời: các đoạn cách nhau bởi dòng trống; [n] thành nút nhảy tới nguồn n. */
function AnswerText({ text, mid }: { text: string; mid: number }) {
  const paras = useMemo(() => text.split(/\n{2,}/).map((p) => p.trim()).filter(Boolean), [text]);
  const jump = (n: number) => {
    const el = document.getElementById(citeId(mid, n));
    el?.scrollIntoView({ block: "nearest", behavior: "smooth" });
    el?.classList.add("flash");
    window.setTimeout(() => el?.classList.remove("flash"), 1200);
  };
  return (
    <div className="chat-answer">
      {paras.map((p, i) => (
        <p key={i}>
          {p.split(/(\[\d+\])/).map((part, j) => {
            const hit = /^\[(\d+)\]$/.exec(part);
            return hit ? (
              <button key={j} type="button" className="chat-cite" onClick={() => jump(Number(hit[1]))}
                      aria-label={`Xem nguồn ${hit[1]}`}>{hit[1]}</button>
            ) : <Fragment key={j}>{part}</Fragment>;
          })}
        </p>
      ))}
    </div>
  );
}

function Sources({ sources, mid }: { sources: RagSource[]; mid: number }) {
  if (!sources.length) return null;
  return (
    <div className="chat-sources">
      <h3 className="small muted chat-label">Nguồn ({sources.length})</h3>
      <ol>
        {sources.map((s) => (
          <li key={s.citation_id} id={citeId(mid, s.citation_id)} className="chat-source">
            <span className="chat-source-n" aria-hidden="true">{s.citation_id}</span>
            <div className="chat-source-body">
              {s.kind === "data" || !s.url ? (
                // Số liệu do công cụ truy vấn kho sinh ra (đếm bài, phạm vi kho…): không có bài/URL.
                <>
                  <span className="chat-source-title">{s.title}</span>
                  <div className="inline small muted"><span>Dữ liệu trong kho</span></div>
                </>
              ) : (
                <>
                  <a href={s.url} target="_blank" rel="noopener noreferrer" className="chat-source-title">
                    {s.title} <IconLink size={13} />
                  </a>
                  <div className="inline small muted">
                    {s.source && <SourceChip source={s.source} />}
                    <span>{fmtDateTime(s.published_at)}</span>
                    {s.event_id && <Link to={eventHref(s.event_id)}>Sự kiện: {s.event_name}</Link>}
                  </div>
                </>
              )}
              {s.quotes.map((q) => <blockquote key={q} className="chat-quote">“{q}”</blockquote>)}
            </div>
          </li>
        ))}
      </ol>
    </div>
  );
}
