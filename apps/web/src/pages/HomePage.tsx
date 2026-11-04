import { useState, type CSSProperties, type FormEvent, type ReactNode } from "react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router";
import { useBookmarks, useCurrentUser, useToggleBookmark } from "../api/accountQueries";
import type { TrendItem, TrendTimes, Trending } from "../api/client";
import { useEventStats, useEvents, useRunInfo, useTrendTimes, useTrending } from "../api/queries";
import { ApiError } from "../api/client";
import { urlHour } from "../api/prefetch";
import { EventErrorBox } from "../components/EventBits";
import { IconBookmark, IconChevronLeft, IconChevronRight, IconSearch } from "../components/Icons";
import { Empty, ErrorBox, Loading, Skeleton } from "../components/Status";
import { fmtDec, fmtInt, fmtShort, fmtWeekday, vnClock, ddmm, ddmmyyyy } from "../lib/format";
import { eventHref, loginHref } from "../lib/routes";
import { useTitle } from "../lib/useTitle";
import { HOUR_MS, parseUrlTime, vnLocal } from "../lib/vntime";

const delay = (s: number): CSSProperties => ({ animationDelay: `${s.toFixed(2)}s` });
const heatPct = (score: number, max: number) => `${Math.max(3, Math.round((score / (max || 1)) * 100))}%`;

/**
 * Trang chủ "Xu hướng" (thiết kế Main + MobileHome). Dữ liệu là MỘT lần chạy pipeline (chưa có crawler chạy liên tục),
 * nên trang "phát lại": người xem chọn một giờ và thấy top-20 sự kiện nóng NHƯ TẠI GIỜ ĐÓ. Giờ đang xem nằm trên URL
 * (?t=YYYY-MM-DDTHH:MM, giờ VN) — giống trang /trending cũ (nay chuyển hướng về đây).
 */
export function HomePage() {
  useTitle("Xu hướng");
  const [params, setParams] = useSearchParams();
  const tParam = params.get("t");
  const parsed = tParam ? parseUrlTime(tParam) : NaN;
  const times = useTrendTimes();
  const run = useRunInfo();
  const lo = times.data ? Date.parse(times.data.dau) : NaN;
  const hi = times.data ? Date.parse(times.data.cuoi) + HOUR_MS - 1 : NaN;
  const invalid = !!tParam && !Number.isFinite(parsed);
  const outOfRange = Number.isFinite(parsed) && Number.isFinite(lo) && (parsed < lo || parsed > hi);
  // ?t= sai dạng hoặc ngoài khoảng → không gửi (server dùng mốc mặc định) và báo nhẹ phía trên
  const tSend = Number.isFinite(parsed) && !outOfRange ? vnLocal(parsed) : undefined;
  const trending = useTrending(tSend);
  const data = trending.data;
  // ngày/giờ đang xem biết sớm từ URL (không đợi /api/trending) → các API phụ gọi song song
  const tIso = data?.t ?? (urlHour(tSend ?? null) ? `${urlHour(tSend ?? null)}:00+07:00` : undefined);
  const day = tIso ? vnClock(tIso).date : undefined;
  const stats = useEventStats(day);
  const outOf422 = trending.error instanceof ApiError && trending.error.status === 422;

  const goTo = (iso: string | null) => iso && setParams({ t: vnLocal(Date.parse(iso)) }, { replace: true });
  const nSources = run.data?.nguon_bao.length;
  const rangeText = times.data ? `${ddmmyyyy(vnClock(times.data.dau).date)} đến ${ddmmyyyy(vnClock(times.data.cuoi).date)}` : "";

  return (
    <>
      <section aria-labelledby="h-hero" className="hero">
        <div aria-hidden="true" className="blob" style={{ right: "6%", top: 30, width: 360, height: 360,
          background: "radial-gradient(circle, rgba(56,189,248,.28) 0%, rgba(56,189,248,0) 70%)" }} />
        <div className="hero-inner">
          <div className="hero-main rise">
            <span className="replay-chip" data-testid="replay-chip">
              <span className="dot-live pulse" aria-hidden="true" />
              {data ? <>Phát lại · {vnClock(data.t).hhmm}, {fmtWeekday(data.t)}</> : "Phát lại bảng xu hướng"}
            </span>
            <h1 id="h-hero">Hôm nay báo chí đang nói về <span className="grad-text">điều gì?</span></h1>
            <p className="hero-lead">
              Bài của {nSources ?? "nhiều"} báo được gom thành sự kiện, đặt tên ngắn và xếp theo tốc độ đưa tin, cập nhật
              mỗi giờ.
            </p>
            {day && stats.data?.ngay && (
              <p className="hero-mini" data-testid="hero-mini">
                Ngày {ddmm(day)}: <b>{fmtInt(stats.data.ngay.so_bai)}</b> bài · <b>{fmtInt(stats.data.ngay.so_su_kien_nhieu_bai)}</b>{" "}
                sự kiện ≥ 2 bài · <b>{stats.data.ngay.so_bao}</b> báo
              </p>
            )}
            <HeroSearch />
          </div>
          <HeroStats day={day} stats={stats.data?.ngay ?? null} loading={stats.isPending && !!day} />
        </div>
      </section>

      <div className="page" style={{ paddingTop: 8, gap: 26 }}>
        {(invalid || outOfRange) && (
          <p className="info-box small" role="status" data-testid="t-notice">
            {invalid ? <>Mốc giờ trên đường dẫn không hợp lệ (“{tParam!.slice(0, 40)}”)</>
              : <>Giờ {fmtShort(new Date(parsed).toISOString())} nằm ngoài khoảng có dữ liệu ({rangeText})</>}
            , đang hiện mốc mặc định.{" "}<Link to="/">Bỏ khỏi đường dẫn</Link>
          </p>
        )}
        <div className="stack" style={{ gap: 6 }}>
          <div className="row-between">
            <h2 style={{ fontSize: 24, fontWeight: 800 }}>
              {data ? <>Đang nóng lúc <span className="grad-text">{vnClock(data.t).hhmm}</span></> : "Đang nóng"}
            </h2>
            {data && <TimePicker data={data} times={times.data} onGo={goTo}
                                 onPick={(t) => setParams({ t }, { replace: true })} />}
          </div>
          <p className="hint">
            <span className="full-hint">Dữ liệu là một lần chạy pipeline trên kho bài đã thu (chưa có crawler chạy liên tục), nên
              trang phát lại bảng xu hướng như tại giờ bạn chọn. Điểm độ nóng là công thức, chưa được đánh giá.</span>
            <span className="mobile-hint">Phát lại một lần chạy pipeline (chưa có crawler); điểm chưa được đánh giá.</span>
          </p>
        </div>

        {trending.isPending && <Loading lines={5} h={26} label="Đang tải bảng xu hướng…" />}
        {trending.error && (
          <>
            {outOf422
              ? <ErrorBox error={trending.error} title="Giờ này nằm ngoài khoảng có dữ liệu."
                          hint={rangeText ? `Bảng xu hướng có từ ${rangeText}.` : undefined} />
              : <EventErrorBox error={trending.error} onRetry={() => trending.refetch()} />}
            {tParam && <Link to="/" className="btn-ghost pill" style={{ alignSelf: "flex-start" }}>Về mốc mặc định</Link>}
          </>
        )}
        {data && data.items.length === 0 && (
          <Empty title="Không có sự kiện nào đủ điều kiện ở giờ này.">
            Cần ≥ 2 bài, trong đó ≥ 1 bài trong 3 giờ qua — thường là đêm khuya ít bài. Thử giờ khác hoặc{" "}
            <Link to="/">về mốc mặc định</Link>.
          </Empty>
        )}
        {data && data.items.length > 0 && (
          <Board data={data} stale={trending.isPlaceholderData}
                 aside={<Aside day={day} tIso={tIso} categories={stats.data?.chuyen_muc} />} />
        )}
        {data && data.items.length === 0 && <Aside day={day} tIso={tIso} categories={stats.data?.chuyen_muc} />}
        <JoinStrip />
      </div>
    </>
  );
}

function HeroSearch() {
  const navigate = useNavigate();
  const [q, setQ] = useState("");
  const submit = (e: FormEvent) => {
    e.preventDefault();
    navigate(q.trim() ? `/events?q=${encodeURIComponent(q.trim())}` : "/events");
  };
  return (
    <form className="searchbar" role="search" onSubmit={submit}>
      <IconSearch />
      <label htmlFor="q-hero" className="sr-only">Tìm sự kiện</label>
      <input id="q-hero" type="search" placeholder="Tìm sự kiện, người, địa danh…" value={q}
             onChange={(e) => setQ(e.target.value)} />
      <button type="submit" className="btn">Tìm</button>
    </form>
  );
}

function HeroStats({ day, stats, loading }: {
  day?: string; stats: { so_bai: number; so_su_kien_nhieu_bai: number; so_bao: number } | null; loading: boolean;
}) {
  if (loading) {
    return (
      <div className="hero-stats rise" style={delay(.1)} aria-hidden="true">
        <div className="hero-stat wide"><Skeleton h={48} /></div>
        <div className="hero-stat"><Skeleton h={40} /></div>
        <div className="hero-stat"><Skeleton h={40} /></div>
      </div>
    );
  }
  if (!stats || !day) return null;          // không có số thì ẩn, không bịa
  return (
    <dl className="hero-stats rise" style={{ ...delay(.1), margin: 0 }} data-testid="hero-stats">
      <div className="hero-stat wide">
        <dt className="l">Bài đăng cả ngày {ddmm(day)}</dt>
        <dd className="v" style={{ margin: 0 }}>{fmtInt(stats.so_bai)}</dd>
      </div>
      <div className="hero-stat">
        <dd className="v" style={{ margin: 0 }}>{fmtInt(stats.so_su_kien_nhieu_bai)}</dd>
        <dt className="l">sự kiện có từ 2 bài trong ngày</dt>
      </div>
      <div className="hero-stat">
        <dd className="v" style={{ margin: 0 }}>{fmtInt(stats.so_bao)}</dd>
        <dt className="l">báo có bài trong ngày</dt>
      </div>
    </dl>
  );
}

/** Chọn giờ: trước/sau một giờ (t_truoc/t_sau của API) + chọn ngày/giờ bất kỳ trong khoảng có dữ liệu. */
function TimePicker({ data, times, onGo, onPick }: {
  data: Trending; times?: TrendTimes; onGo: (iso: string | null) => void; onPick: (t: string) => void;
}) {
  const c = vnClock(data.t);
  const [open, setOpen] = useState(false);
  const [dateErr, setDateErr] = useState<string | null>(null);
  const min = times ? vnClock(times.dau).date : undefined;
  const max = times ? vnClock(times.cuoi).date : undefined;
  const pickDate = (v: string) => {
    if (!v) return;
    if ((min && v < min) || (max && v > max)) {             // chặn trước khi gọi API (gõ tay vượt min/max)
      setDateErr(`Chỉ có dữ liệu từ ${ddmmyyyy(min!)} đến ${ddmmyyyy(max!)}.`);
      return;
    }
    setDateErr(null);
    onPick(`${v}T${String(c.hour).padStart(2, "0")}:00`);
  };
  return (
    <div className="inline">
      <div role="group" aria-label="Chọn giờ" className="time-pill">
        <button type="button" className="icon-btn" aria-label="Giờ trước" disabled={!data.t_truoc}
                onClick={() => onGo(data.t_truoc)}><IconChevronLeft /></button>
        <span className="label" aria-live="polite" data-testid="current-hour">{c.ddmm} · {c.hhmm}</span>
        <button type="button" className="icon-btn" aria-label="Giờ sau" disabled={!data.t_sau}
                onClick={() => onGo(data.t_sau)}><IconChevronRight /></button>
      </div>
      <button type="button" className="btn-ghost sm pill" aria-expanded={open} aria-controls="chon-gio-khac"
              onClick={() => setOpen(!open)}>Chọn giờ khác</button>
      {open && times && (
        <div id="chon-gio-khac" className="filters drop" style={{ width: "100%", justifyContent: "flex-end" }}>
          <label>
            Ngày
            <input type="date" value={c.date} min={min} max={max} aria-describedby="loi-ngay"
                   aria-invalid={!!dateErr} onChange={(e) => pickDate(e.target.value)} />
          </label>
          <label>
            Giờ
            <select value={c.hour} onChange={(e) => onPick(`${c.date}T${e.target.value.padStart(2, "0")}:00`)}>
              {Array.from({ length: 24 }, (_, h) => <option key={h} value={h}>{String(h).padStart(2, "0")}:00</option>)}
            </select>
          </label>
          <Link to="/" className="btn-ghost sm pill">Mốc mặc định</Link>
          <span id="loi-ngay" className="field-error" role={dateErr ? "alert" : undefined} style={{ width: "100%", textAlign: "right" }}>
            {dateErr ?? ""}</span>
        </div>
      )}
    </div>
  );
}

function sinceLabel(item: TrendItem, t: string) {
  const f = vnClock(item.first_seen);
  return f.date === vnClock(t).date ? `Từ ${f.hhmm} hôm nay` : `Từ ${f.ddmm} ${f.hhmm}`;
}

function Board({ data, stale, aside }: { data: Trending; stale: boolean; aside: ReactNode }) {
  const [all, setAll] = useState(false);
  const max = data.items[0]?.score ?? 1;
  const [first, ...others] = data.items;
  const second = others.slice(0, 2);
  const rest = others.slice(2, all ? 19 : 9);
  const day = vnClock(data.t).date;
  return (
    <div className="stack" style={{ gap: 26, opacity: stale ? .6 : 1, transition: "opacity .2s" }} aria-busy={stale}>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 16, alignItems: "flex-start" }}>
        <TopCard item={first} max={max} t={data.t} />
        {second.length > 0 && (
          <div style={{ flex: "1 1 360px", minWidth: 0, display: "flex", flexDirection: "column", gap: 16 }}>
            {second.map((it, i) => (
              <article key={it.event_id} className="card lift rise mid-card" style={delay(.15 + i * .05)}>
                <div className="row-between" style={{ gap: 8 }}>
                  <span className="rank-big grad-text">#{it.hang}</span>
                  {it.chuyen_muc_chinh && <span className="tag">{it.chuyen_muc_chinh}</span>}
                </div>
                <Link to={eventHref(it.event_id)} className="name">{it.ten}</Link>
                <div className="meta">
                  {fmtInt(it.so_bai_den_t)} bài · {it.so_bao} báo ·{" "}
                  <span style={{ color: "var(--accent)", fontWeight: 600 }}>+{it.so_bai_3h} trong 3 giờ</span>
                </div>
                <span className="heat" role="img" aria-label={`Độ nóng ${fmtDec(it.score)}`}>
                  <span className="grow" style={{ ...delay(.15 + i * .05), width: heatPct(it.score, max) }} />
                </span>
              </article>
            ))}
          </div>
        )}
      </div>

      <div className="split">
      {rest.length > 0 && (
        <section aria-labelledby="h-list" className="card tight rise main" style={{ ...delay(.2), display: "block" }}>
          <h3 id="h-list" style={{ padding: "14px 16px 6px" }}>Tiếp theo trên bảng</h3>
          <ol className="rank-list" data-testid="rank-list">
            {rest.map((it, i) => (
              <li key={it.event_id} className="rank-row">
                <span className="rank" aria-label={`Hạng ${it.hang}`}>{it.hang}</span>
                <div className="body">
                  <Link to={eventHref(it.event_id)} className="title">{it.ten}</Link>
                  <div className="meta">
                    {vnClock(it.first_seen).date === day && <span className="tag new">Mới</span>}
                    {it.chuyen_muc_chinh && <span className="cat">{it.chuyen_muc_chinh}</span>}
                    <span>{fmtInt(it.so_bai_den_t)} bài · {it.so_bao} báo</span>
                    <span className={`vel${it.so_bai_3h >= 4 ? " fast" : ""}`}>+{it.so_bai_3h} trong 3 giờ</span>
                  </div>
                </div>
                <span className="heat" role="img" aria-label={`Độ nóng ${fmtDec(it.score)}`}>
                  <span className="grow" style={{ ...delay(.15 + i * .05), width: heatPct(it.score, max) }} />
                </span>
                <IconChevronRight className="chev" />
              </li>
            ))}
          </ol>
          {data.items.length > 10 && (
            <button type="button" className="more-link" aria-expanded={all} onClick={() => setAll(!all)}>
              {all ? "Thu gọn" : `Xem cả bảng ${data.items.length} sự kiện`}
            </button>
          )}
        </section>
      )}
      <aside className="side">{aside}</aside>
      </div>
    </div>
  );
}

function TopCard({ item, max, t }: { item: TrendItem; max: number; t: string }) {
  const { data: user } = useCurrentUser();
  const saved = useBookmarks();
  const toggle = useToggleBookmark();
  const navigate = useNavigate();
  const loc = useLocation();
  const isSaved = !!saved.data?.some((b) => b.event_id === item.event_id);
  const onSave = () => {
    if (!user) { navigate(loginHref(loc.pathname + loc.search)); return; }
    toggle.mutate({ on: !isSaved, ev: { event_id: item.event_id, ten: item.ten, size: item.so_bai_den_t,
                                        n_sources: item.so_bao, chuyen_muc: item.chuyen_muc_chinh } });
  };
  return (
    <article className="top-card lift rise" style={{ ...delay(.1), flex: "999 1 560px", minWidth: 0 }} data-testid="top-card">
      <div aria-hidden="true" className="blob" style={{ right: -60, top: -60, width: 260, height: 260,
        background: "radial-gradient(circle, rgba(255,255,255,.25) 0%, rgba(255,255,255,0) 70%)" }} />
      <div aria-hidden="true" className="ghost-num">1</div>
      <div className="inline">
        <span className="tag white">#1 · Nóng nhất</span>
        {item.chuyen_muc_chinh && <span className="tag glass">{item.chuyen_muc_chinh}</span>}
      </div>
      <Link to={eventHref(item.event_id)} className="name">{item.ten}</Link>
      <div className="pills">
        <span><b>{fmtInt(item.so_bai_den_t)}</b> bài</span>
        <span><b>{item.so_bao}</b> báo</span>
        <span><b>+{item.so_bai_3h}</b> bài trong 3 giờ</span>
        <span>{sinceLabel(item, t)}</span>
      </div>
      <div className="foot">
        <div className="heat-wrap">
          <span>Độ nóng · điểm {fmtDec(item.score)}</span>
          <span className="heat lg white"><span className="grow" style={{ width: heatPct(item.score, max) }} /></span>
        </div>
        <button type="button" className="glass-btn" onClick={onSave} aria-pressed={user ? isSaved : undefined}
                aria-label={user ? (isSaved ? "Bỏ lưu sự kiện" : "Lưu sự kiện") : "Đăng nhập để lưu sự kiện"}
                disabled={toggle.isPending}>
          <IconBookmark size={20} />
        </button>
        <Link to={eventHref(item.event_id)} className="btn white">Xem diễn biến →</Link>
      </div>
    </article>
  );
}

function Aside({ day, tIso, categories }: { day?: string; tIso?: string; categories?: { category: string; n: number }[] }) {
  const tLocal = tIso ? vnLocal(Date.parse(tIso)) : undefined;
  const fresh = useEvents(
    { sort: "first_seen", min_size: 2, first_from: `${day}T00:00`, first_to: tLocal, page_size: 5 }, !!(day && tLocal));
  return (
    <>
      <section aria-labelledby="h-new" className="card rise" style={delay(.25)}>
        <h3 id="h-new" style={{ marginBottom: 14 }}>Mới xuất hiện {day ? `ngày ${ddmm(day)}` : "hôm nay"}</h3>
        {(fresh.isPending || !day) && <Loading lines={4} />}
        {fresh.error && <EventErrorBox error={fresh.error} onRetry={() => fresh.refetch()} />}
        {day && fresh.data && fresh.data.items.length === 0 && (
          <p className="muted small">Chưa có sự kiện nhiều bài nào xuất hiện trong ngày tính tới giờ đang xem.</p>
        )}
        {day && fresh.data && fresh.data.items.length > 0 && (
          <ul className="timeline-list" data-testid="fresh-list">
            {fresh.data.items.map((e) => (
              <li key={e.event_id}>
                <span className="time">{vnClock(e.first_seen).hhmm}</span>
                <Link to={eventHref(e.event_id)}>{e.ten}</Link>
              </li>
            ))}
          </ul>
        )}
      </section>
      <section aria-labelledby="h-cat" className="card rise" style={delay(.3)}>
        <h3 id="h-cat" style={{ marginBottom: 12 }}>Chuyên mục</h3>
        {!categories && <Loading lines={2} />}
        {categories && categories.length === 0 && <p className="muted small">Chưa có dữ liệu chuyên mục.</p>}
        {categories && (
          <div className="chips">
            {categories.map((c) => (
              <Link key={c.category} to={`/events?category=${encodeURIComponent(c.category)}`} className="chip">{c.category}</Link>
            ))}
          </div>
        )}
      </section>
    </>
  );
}

function JoinStrip() {
  const { data: user, isPending } = useCurrentUser();
  if (isPending || user) return null;
  return (
    <section aria-labelledby="h-join" className="join rise" style={delay(.35)}>
      <div aria-hidden="true" className="blob" style={{ left: -40, bottom: -80, width: 260, height: 260,
        background: "radial-gradient(circle, rgba(14,165,233,.22) 0%, rgba(14,165,233,0) 70%)" }} />
      <div style={{ flex: "1 1 420px", minWidth: 0 }}>
        <h2 id="h-join">Không bỏ lỡ diễn biến của sự kiện bạn quan tâm</h2>
        <p>Tạo tài khoản miễn phí để lưu sự kiện, theo dõi diễn biến và nhận thông báo khi có tin mới về chủ đề bạn đăng ký.</p>
      </div>
      <Link to="/register" className="btn">Tạo tài khoản miễn phí</Link>
    </section>
  );
}
