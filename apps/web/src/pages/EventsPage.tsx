import { useEffect, useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router";
import type { EventQuery, EventSummary } from "../api/client";
import { useEvents, useRunInfo } from "../api/queries";
import { EventErrorBox, EventNotice, NameSourceBadge } from "../components/EventBits";
import { Pagination } from "../components/Pagination";
import { SourceBadge } from "../components/SourceBadge";
import { Loading } from "../components/Status";
import { fmtDateTime, fmtInt } from "../lib/format";
import { fmtScore } from "../lib/vntime";

const PAGE_SIZE = 20;
const SORTS = { hot: "Nổi bật", newest: "Mới nhất", size: "Nhiều bài nhất" } as const;
const SIZES = [1, 2, 3, 5, 10];

export function EventsPage() {
  // Mọi bộ lọc nằm trên URL (giống trang Bài báo): tải lại không mất, gửi link được.
  const [params, setParams] = useSearchParams();
  const get = (k: string) => params.get(k) ?? "";
  const sort = (get("sort") || "hot") as keyof typeof SORTS;
  const minSize = Number(get("min_size") || "2") || 2;
  const page = Number(get("page") || "1") || 1;
  const [draft, setDraft] = useState(get("q"));
  useEffect(() => setDraft(params.get("q") ?? ""), [params]);

  const run = useRunInfo();
  const query: EventQuery = { sort, min_size: minSize, page, page_size: PAGE_SIZE };
  for (const k of ["q", "source", "date_from", "date_to"] as const) if (get(k)) query[k] = get(k);
  const events = useEvents(query);

  function update(next: Record<string, string>) {
    const merged = new URLSearchParams(params);
    for (const [k, v] of Object.entries(next)) {
      if (v) merged.set(k, v);
      else merged.delete(k);
    }
    merged.delete("page");
    setParams(merged);
  }
  function goPage(p: number) {
    const merged = new URLSearchParams(params);
    merged.set("page", String(p));
    setParams(merged);
    window.scrollTo({ top: 0 });
  }
  function onSearch(e: FormEvent) {
    e.preventDefault();
    update({ q: draft.trim() });
  }

  return (
    <>
      <h1>Sự kiện</h1>
      <EventNotice />
      <div className="filters">
        <label>
          Báo
          <select value={get("source")} onChange={(e) => update({ source: e.target.value })}>
            <option value="">Tất cả</option>
            {run.data?.nguon_bao.map((s) => <option key={s} value={s}>{s}</option>)}
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
          <select value={minSize} onChange={(e) => update({ min_size: e.target.value })}>
            {SIZES.map((s) => <option key={s} value={s}>{s === 1 ? "Mọi sự kiện" : `≥ ${s} bài`}</option>)}
          </select>
        </label>
        <label>
          Sắp xếp
          <select value={sort} onChange={(e) => update({ sort: e.target.value })}>
            {Object.entries(SORTS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </label>
        <button className="ghost" onClick={() => setParams({})}>Bỏ lọc</button>
      </div>
      <form className="search" onSubmit={onSearch}>
        <input type="search" value={draft} placeholder="Tìm trong tên sự kiện (gõ không dấu cũng được), rồi bấm Enter"
               onChange={(e) => setDraft(e.target.value)} />
        <button type="submit">Tìm</button>
      </form>

      {events.isPending && <Loading />}
      {events.error && <EventErrorBox error={events.error} />}
      {events.data && (
        <>
          <p className="muted">
            {fmtInt(events.data.total)} sự kiện khớp bộ lọc
            {sort === "hot" && " · “Nổi bật” = tổng điểm xu hướng theo giờ (cả độ nóng lẫn độ bền)"}
          </p>
          {events.data.total === 0 && <p className="empty">Không có sự kiện nào khớp. Thử bỏ bớt bộ lọc.</p>}
          <ul className="articles events">
            {events.data.items.map((e) => <EventItem key={e.event_id} e={e} />)}
          </ul>
          <Pagination page={events.data.page} pageSize={events.data.page_size}
                      total={events.data.total} onChange={goPage} />
        </>
      )}
    </>
  );
}

function EventItem({ e }: { e: EventSummary }) {
  return (
    <li>
      <Link to={`/events/${e.event_id}`} className="title">{e.ten}</Link>{" "}
      <NameSourceBadge source={e.nguon_ten} />
      <div className="meta">
        <strong>{fmtInt(e.size)}</strong> bài · {e.n_sources} báo · {fmtDateTime(e.first_seen)} → {fmtDateTime(e.last_seen)}
        {e.tong_diem != null && <> · tổng điểm {fmtScore(e.tong_diem)}</>}
        {e.so_gio_trong_top10 > 0 && <> · {e.so_gio_trong_top10} giờ trong top 10</>}
      </div>
      <div className="chips">
        {e.sources.map((s) => (
          <span key={s.source} className="chip"><SourceBadge source={s.source} /> {s.n}</span>
        ))}
      </div>
    </li>
  );
}
