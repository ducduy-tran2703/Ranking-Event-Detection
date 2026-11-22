import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router";
import type { EventQuery, EventSummary } from "../api/client";
import { useEventStats, useEvents, useRunInfo } from "../api/queries";
import { EventErrorBox, EventNotice, NameSourceBadge } from "../components/EventBits";
import { IconSearch } from "../components/Icons";
import { Pagination } from "../components/Pagination";
import { SourceChip } from "../components/SourceBadge";
import { Empty, Loading } from "../components/Status";
import { fmtInt, fmtShort } from "../lib/format";
import { eventHref } from "../lib/routes";
import { sourceName } from "../lib/sources";
import { fmtScore } from "../lib/vntime";
import { useTitle } from "../lib/useTitle";

const PAGE_SIZE = 20;
const SORTS = { hot: "Nổi bật", newest: "Mới cập nhật", first_seen: "Mới xuất hiện", size: "Nhiều bài nhất" } as const;
const SIZES = [1, 2, 3, 5, 10];

/** Danh sách + tìm kiếm + lọc sự kiện. Mọi bộ lọc nằm trên URL: tải lại không mất, gửi link được. */
export function EventsPage() {
  const [params, setParams] = useSearchParams();
  const get = (k: string) => params.get(k) ?? "";
  useTitle(get("q") ? `Tìm “${get("q")}”` : get("category") || "Sự kiện");
  const sort = (get("sort") in SORTS ? get("sort") : "hot") as keyof typeof SORTS;
  const minSize = Number(get("min_size") || "2") || 2;
  const page = Number(get("page") || "1") || 1;
  const [draft, setDraft] = useState(get("q"));
  useEffect(() => setDraft(params.get("q") ?? ""), [params]);
  const searchRef = useRef<HTMLInputElement>(null);
  useEffect(() => { if (params.get("tim") === "1") searchRef.current?.focus(); }, [params]);

  const run = useRunInfo();
  const stats = useEventStats();
  const query: EventQuery = { sort, min_size: minSize, page, page_size: PAGE_SIZE };
  for (const k of ["q", "source", "category", "date_from", "date_to"] as const) if (get(k)) query[k] = get(k);
  const events = useEvents(query);

  function update(next: Record<string, string>) {
    const merged = new URLSearchParams(params);
    for (const [k, v] of Object.entries(next)) {
      if (v) merged.set(k, v);
      else merged.delete(k);
    }
    merged.delete("page");
    merged.delete("tim");
    setParams(merged);
  }
  function goPage(p: number) {
    const merged = new URLSearchParams(params);
    merged.set("page", String(p));
    setParams(merged);
    window.scrollTo({ top: 0 });
  }
  const onSearch = (e: FormEvent) => { e.preventDefault(); update({ q: draft.trim() }); };
  const filtered = ["q", "source", "category", "date_from", "date_to", "min_size", "sort"].some((k) => get(k));

  return (
    <div className="page">
      <div className="page-head rise">
        <h1>Sự kiện{get("category") ? <> · {get("category")}</> : null}</h1>
        <p>Mỗi sự kiện gom các bài của nhiều báo cùng đưa một tin. Tìm theo tên sự kiện hoặc tiêu đề bài đại diện, gõ không dấu cũng được.</p>
        <EventNotice />
      </div>

      <form className="searchbar" role="search" onSubmit={onSearch} style={{ maxWidth: "none" }}>
        <IconSearch />
        <label htmlFor="q-events" className="sr-only">Tìm sự kiện</label>
        <input id="q-events" ref={searchRef} type="search" value={draft} placeholder="Tìm sự kiện, người, địa danh…"
               onChange={(e) => setDraft(e.target.value)} />
        <button type="submit" className="btn">Tìm</button>
      </form>

      <div className="filters" role="group" aria-label="Bộ lọc">
        <label>
          Báo
          <select value={get("source")} onChange={(e) => update({ source: e.target.value })}>
            <option value="">Tất cả</option>
            {run.data?.nguon_bao.map((s) => <option key={s} value={s}>{sourceName(s)}</option>)}
          </select>
        </label>
        <label>
          Chuyên mục
          <select value={get("category")} onChange={(e) => update({ category: e.target.value })}>
            <option value="">Tất cả</option>
            {stats.data?.chuyen_muc.map((c) => <option key={c.category} value={c.category}>{c.category}</option>)}
            {get("category") && !stats.data?.chuyen_muc.some((c) => c.category === get("category")) &&
              <option value={get("category")}>{get("category")}</option>}
          </select>
        </label>
        <label>
          Từ ngày
          <input type="date" value={get("date_from")} onChange={(e) => update({ date_from: e.target.value })} />
        </label>
        <label>
          Đến ngày
          <input type="date" value={get("date_to")} onChange={(e) => update({ date_to: e.target.value })} />
        </label>
        <label>
          Kích thước
          <select value={minSize} onChange={(e) => update({ min_size: e.target.value === "2" ? "" : e.target.value })}>
            {SIZES.map((s) => <option key={s} value={s}>{s === 1 ? "Mọi sự kiện" : `≥ ${s} bài`}</option>)}
          </select>
        </label>
        <label>
          Sắp xếp
          <select value={sort} onChange={(e) => update({ sort: e.target.value === "hot" ? "" : e.target.value })}>
            {Object.entries(SORTS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </label>
        <button type="button" className="btn-ghost sm" disabled={!filtered} onClick={() => setParams({})}>Bỏ lọc</button>
      </div>

      {events.isPending && <Loading lines={6} h={60} label="Đang tải danh sách sự kiện…" />}
      {events.error && <EventErrorBox error={events.error} onRetry={() => events.refetch()} />}
      {events.data && (
        <>
          <p className="muted small" aria-live="polite" data-testid="result-count">
            {fmtInt(events.data.total)} sự kiện khớp bộ lọc
            {sort === "hot" && " · “Nổi bật” = tổng điểm xu hướng theo giờ (cả độ nóng lẫn độ bền)"}
          </p>
          {events.data.total === 0 && (
            <Empty title="Không có sự kiện nào khớp.">
              Thử từ khoá khác, bỏ bớt bộ lọc, hoặc chọn “Mọi sự kiện” ở ô Kích thước để gồm cả sự kiện một bài.
            </Empty>
          )}
          <ul className="event-list" style={{ opacity: events.isPlaceholderData ? .6 : 1 }}>
            {events.data.items.map((e) => <EventItem key={e.event_id} e={e} />)}
          </ul>
          <Pagination page={events.data.page} pageSize={events.data.page_size} total={events.data.total} onChange={goPage} />
        </>
      )}
    </div>
  );
}

function EventItem({ e }: { e: EventSummary }) {
  return (
    <li className="event-item">
      <div className="inline">
        {e.chuyen_muc_chinh && <span className="tag">{e.chuyen_muc_chinh}</span>}
        <NameSourceBadge source={e.nguon_ten} />
      </div>
      <Link to={eventHref(e.event_id)} className="title">{e.ten}</Link>
      <div className="meta">
        <span><b>{fmtInt(e.size)}</b> bài · {e.n_sources} báo</span>
        <span>{fmtShort(e.first_seen)} đến {fmtShort(e.last_seen)}</span>
        {e.tong_diem != null && <span>tổng điểm {fmtScore(e.tong_diem)}</span>}
        {e.so_gio_trong_top10 > 0 && <span>{e.so_gio_trong_top10} giờ trong top 10</span>}
      </div>
      <div className="chips" style={{ gap: 6 }}>
        {e.sources.map((s) => <SourceChip key={s.source} source={s.source} n={s.n} />)}
      </div>
    </li>
  );
}
