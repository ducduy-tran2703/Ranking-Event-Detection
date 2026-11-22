import { useState, type CSSProperties, type FormEvent, type ReactNode } from "react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router";
import { useBookmarks, useCurrentUser, useToggleBookmark } from "../api/accountQueries";
import type { TrendItem, TrendTimes, Trending } from "../api/client";
import { useEventStats, useEvents, useRunInfo, useTrendTimes, useTrending } from "../api/queries";
import { ApiError } from "../api/client";
import { urlHour } from "../api/prefetch";
import { EventErrorBox } from "../components/EventBits";
import { IconBookmark, IconChevronLeft, IconChevronRight, IconSearch } from "../components/Icons";
import { Empty, ErrorBox, Loading } from "../components/Status";
import { fmtDec, fmtInt, fmtShort, fmtWeekday, vnClock, ddmm, ddmmyyyy } from "../lib/format";
import { eventHref, loginHref } from "../lib/routes";
import { useTitle } from "../lib/useTitle";
import { HOUR_MS, parseUrlTime, vnLocal } from "../lib/vntime";

const FIRST_RANKS = 10;

/** Độ dài rãnh độ nóng theo điểm so với hạng 1. */
const heatPct = (score: number, max: number) => `${Math.max(4, Math.round((score / (max || 1)) * 100))}%`;

/**
 * Trang chủ "Xu hướng". Dữ liệu là MỘT lần chạy pipeline (chưa có crawler chạy liên tục), nên trang "phát lại": người xem
 * chọn một giờ và thấy top-20 sự kiện nóng NHƯ TẠI GIỜ ĐÓ. Giờ đang xem nằm trên URL (?t=YYYY-MM-DDTHH:MM, giờ VN).
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
  const dayStats = stats.data?.ngay;

  return (
    <div className="page">
      <section aria-labelledby="h-hero" className="opener">
        <div className="opener-main">
          <h1 id="h-hero">Hôm nay báo chí đang nói về điều gì?</h1>
          <p className="opener-lead">
            Bài của {nSources ?? "nhiều"} báo được gom thành từng sự kiện, đặt tên ngắn và xếp theo tốc độ đưa tin, cập nhật mỗi giờ.
          </p>
          {day && dayStats && (
            <p className="opener-count" data-testid="hero-stats">
              Ngày {ddmm(day)}: <b>{fmtInt(dayStats.so_bai)}</b> bài, <b>{fmtInt(dayStats.so_su_kien_nhieu_bai)}</b> sự kiện
              từ 2 bài trở lên, <b>{fmtInt(dayStats.so_bao)}</b> báo
            </p>
          )}
          <HeroSearch />
        </div>
        {data && <HourControl data={data} times={times.data} onGo={goTo} onPick={(t) => setParams({ t }, { replace: true })} />}
      </section>

      {(invalid || outOfRange) && (
        <p className="info-box small" role="status" data-testid="t-notice">
          {invalid ? <>Mốc giờ trên đường dẫn không hợp lệ (“{tParam!.slice(0, 40)}”)</>
            : <>Giờ {fmtShort(new Date(parsed).toISOString())} nằm ngoài khoảng có dữ liệu ({rangeText})</>}
          , đang hiện mốc mặc định.{" "}<Link to="/">Bỏ khỏi đường dẫn</Link>
        </p>
      )}

      {trending.isPending && <Loading lines={5} h={26} label="Đang tải bảng xu hướng…" />}
      {trending.error && (
        <>
          {outOf422
            ? <ErrorBox error={trending.error} title="Giờ này nằm ngoài khoảng có dữ liệu."
                        hint={rangeText ? `Bảng xu hướng có từ ${rangeText}.` : undefined} />
            : <EventErrorBox error={trending.error} onRetry={() => trending.refetch()} />}
          {tParam && <Link to="/" className="btn-ghost" style={{ alignSelf: "flex-start" }}>Về mốc mặc định</Link>}
        </>
      )}
      {data && data.items.length === 0 && (
        <Empty title="Không có sự kiện nào đủ điều kiện ở giờ này.">
          Cần ≥ 2 bài, trong đó ≥ 1 bài trong 3 giờ qua, thường là đêm khuya ít bài. Thử giờ khác hoặc{" "}
          <Link to="/">về mốc mặc định</Link>.
        </Empty>
      )}
      {data && data.items.length > 0 && (
        <Board key={data.t} data={data} stale={trending.isPlaceholderData}
               aside={<Aside day={day} tIso={tIso} categories={stats.data?.chuyen_muc} />} />
      )}
      {data && data.items.length === 0 && <Aside day={day} tIso={tIso} categories={stats.data?.chuyen_muc} />}
      <JoinStrip />
    </div>
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
    <form className="searchbar" role="search" onSubmit={submit} style={{ marginTop: 6 }}>
      <IconSearch />
      <label htmlFor="q-hero" className="sr-only">Tìm sự kiện</label>
      <input id="q-hero" type="search" placeholder="Tìm sự kiện, người, địa danh…" value={q}
             onChange={(e) => setQ(e.target.value)} />
      <button type="submit" className="btn">Tìm</button>
    </form>
  );
}

/** Giờ đang phát lại: trước/sau một giờ (t_truoc/t_sau của API) + chọn ngày/giờ bất kỳ trong khoảng có dữ liệu. */
function HourControl({ data, times, onGo, onPick }: {
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
    <div className="hour">
      <div className="hour-now" role="group" aria-label="Chọn giờ">
        <button type="button" className="icon-btn" aria-label="Giờ trước" disabled={!data.t_truoc}
                onClick={() => onGo(data.t_truoc)}><IconChevronLeft size={22} /></button>
        <span key={c.hhmm} className="big" aria-live="polite" data-testid="current-hour">{c.hhmm}</span>
        <button type="button" className="icon-btn" aria-label="Giờ sau" disabled={!data.t_sau}
                onClick={() => onGo(data.t_sau)}><IconChevronRight size={22} /></button>
        <span className="day">{fmtWeekday(data.t)}</span>
      </div>
      <div className="hour-note" data-testid="replay-chip">
        <span>
          <b>Phát lại, không phải thời gian thực.</b>{" "}
          <span className="full-hint">Dữ liệu là một lần chạy pipeline; điểm độ nóng là công thức, chưa được đánh giá.</span>
          <span className="mobile-hint">Điểm độ nóng chưa được đánh giá.</span>
        </span>
      </div>
      <div className="inline">
        <button type="button" className="btn-ghost sm" aria-expanded={open} aria-controls="chon-gio-khac"
                onClick={() => setOpen(!open)}>Chọn giờ khác</button>
        <Link to="/" className="link-btn">Mốc mặc định</Link>
      </div>
      {open && times && (
        <div id="chon-gio-khac" className="filters drop">
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
          <span id="loi-ngay" className="field-error" role={dateErr ? "alert" : undefined} style={{ width: "100%" }}>{dateErr ?? ""}</span>
        </div>
      )}
    </div>
  );
}

function sinceLabel(item: TrendItem, t: string) {
  const f = vnClock(item.first_seen);
  return f.date === vnClock(t).date ? `từ ${f.hhmm} hôm nay` : `từ ${f.ddmm} ${f.hhmm}`;
}

/** Bảng xếp hạng: mỗi sự kiện là một khối nổi, rãnh lún cho biết độ nóng; mỗi lúc chỉ mở một khối (mặc định là hạng 1). */
function Board({ data, stale, aside }: { data: Trending; stale: boolean; aside: ReactNode }) {
  const [all, setAll] = useState(false);
  const [openId, setOpenId] = useState<string | null>(data.items[0]?.event_id ?? null);
  const max = data.items[0]?.score ?? 1;
  const shown = data.items.slice(0, all ? data.items.length : FIRST_RANKS);
  const hidden = data.items.length - shown.length;
  const day = vnClock(data.t).date;
  return (
    <div className="split" style={{ opacity: stale ? .6 : 1, transition: "opacity .2s" }} aria-busy={stale}>
      <section aria-labelledby="h-list" className="main">
        <h2 id="h-list" className="sr-only">Bảng xếp hạng lúc {vnClock(data.t).hhmm}</h2>
        <ol className="volume" data-testid="rank-list">
          {shown.map((it, i) => (
            <Section key={it.event_id} item={it} index={i} max={max} t={data.t} day={day}
                     open={openId === it.event_id} onToggle={() => setOpenId(openId === it.event_id ? null : it.event_id)} />
          ))}
        </ol>
        {data.items.length > FIRST_RANKS && (
          <div className="loose">
            <button type="button" className="btn-ghost sm" aria-expanded={all} onClick={() => setAll(!all)}>
              {all ? "Thu gọn" : `Còn ${hidden} hạng nữa, xem cả bảng`}
            </button>
          </div>
        )}
      </section>
      <aside className="side">{aside}</aside>
    </div>
  );
}

function Section({ item, index, max, t, day, open, onToggle }: {
  item: TrendItem; index: number; max: number; t: string; day: string; open: boolean; onToggle: () => void;
}) {
  const panel = `chi-tiet-${item.event_id}`;
  const lead = index === 0;
  return (
    <li className={`section${lead ? " lead" : ""}`} style={{ "--i": index } as CSSProperties} data-testid={lead ? "top-card" : undefined}>
      <div className="rank-well">
        <span className="n" aria-label={`Hạng ${item.hang}`}>{item.hang}</span>
      </div>
      <div className="leaf">
        <div className="leaf-head">
          <h3 style={{ font: "inherit" }}><Link to={eventHref(item.event_id)} className="leaf-name">{item.ten}</Link></h3>
          <span className="leaf-score" aria-label={`Độ nóng ${fmtDec(item.score)}`}>{fmtDec(item.score)}</span>
          <button type="button" className="leaf-toggle" aria-expanded={open} aria-controls={panel}
                  aria-label={open ? "Thu gọn sự kiện này" : "Mở chi tiết sự kiện này"} onClick={onToggle}>
            <IconChevronRight size={20} />
          </button>
          <div className="leaf-meta">
            {vnClock(item.first_seen).date === day && <span className="tag new">Mới</span>}
            {item.chuyen_muc_chinh && <span className="cat">{item.chuyen_muc_chinh}</span>}
            <span>{fmtInt(item.so_bai_den_t)} bài · {item.so_bao} báo</span>
            <span className={`vel${item.so_bai_3h >= 4 ? " fast" : ""}`}>+{item.so_bai_3h} trong 3 giờ</span>
          </div>
        </div>
        <span className="groove" aria-hidden="true"><span style={{ width: heatPct(item.score, max), animationDelay: `${index * 45 + 150}ms` }} /></span>
        <div id={panel} className={`leaf-flat${open ? " open" : ""}`} inert={!open}>
          <div>
            <div className="leaf-open">
              <p>Độ nóng <b>{fmtDec(item.score)}</b>, đang được đưa tin {sinceLabel(item, t)}.</p>
              <SaveButton item={item} />
              <Link to={eventHref(item.event_id)} className="btn sm">Xem diễn biến</Link>
            </div>
          </div>
        </div>
      </div>
    </li>
  );
}

function SaveButton({ item }: { item: TrendItem }) {
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
    <button type="button" className="btn-ghost sm" onClick={onSave} aria-pressed={user ? isSaved : undefined} disabled={toggle.isPending}>
      <IconBookmark size={16} /> {user ? (isSaved ? "Đã lưu" : "Lưu") : "Đăng nhập để lưu"}
    </button>
  );
}

function Aside({ day, tIso, categories }: { day?: string; tIso?: string; categories?: { category: string; n: number }[] }) {
  const tLocal = tIso ? vnLocal(Date.parse(tIso)) : undefined;
  const fresh = useEvents(
    { sort: "first_seen", min_size: 2, first_from: `${day}T00:00`, first_to: tLocal, page_size: 5 }, !!(day && tLocal));
  return (
    <>
      <section aria-labelledby="h-new" className="side-sheet">
        <h3 id="h-new">Mới xuất hiện {day ? `ngày ${ddmm(day)}` : "hôm nay"}</h3>
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
      <section aria-labelledby="h-cat" className="side-sheet">
        <h3 id="h-cat">Chuyên mục</h3>
        {!categories && <Loading lines={2} />}
        {categories && categories.length === 0 && <p className="muted small">Chưa có dữ liệu chuyên mục.</p>}
        {categories && (
          <div className="chips" style={{ marginTop: 10 }}>
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
    <section aria-labelledby="h-join" className="join">
      <div style={{ flex: "1 1 420px", minWidth: 0 }}>
        <h2 id="h-join">Không bỏ lỡ diễn biến của sự kiện bạn quan tâm</h2>
        <p>Tạo tài khoản miễn phí để lưu sự kiện, theo dõi diễn biến và nhận thông báo khi có tin mới về chủ đề bạn đăng ký.</p>
      </div>
      <Link to="/register" className="btn">Tạo tài khoản miễn phí</Link>
    </section>
  );
}
