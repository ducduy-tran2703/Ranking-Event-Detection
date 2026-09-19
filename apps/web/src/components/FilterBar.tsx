import { useSearchParams } from "react-router";
import type { StatsFilter } from "../api/client";
import { useMeta } from "../api/queries";

/** Bộ lọc chung (nguồn, khoảng ngày) lưu trên URL — tải lại trang không mất, gửi link được. */
export function useUrlFilter() {
  const [params, setParams] = useSearchParams();
  const filter: StatsFilter = {};
  for (const key of ["source", "category", "q", "date_from", "date_to", "issue"] as const) {
    const v = params.get(key);
    if (v) filter[key] = v;
  }
  function update(next: Record<string, string | undefined>) {
    const merged = new URLSearchParams(params);
    for (const [k, v] of Object.entries(next)) {
      if (v) merged.set(k, v);
      else merged.delete(k);
    }
    merged.delete("page"); // đổi bộ lọc thì về trang 1
    setParams(merged);
  }
  function setPage(page: number) {
    const merged = new URLSearchParams(params);
    merged.set("page", String(page));
    setParams(merged);
  }
  return { filter, params, update, setPage };
}

export function FilterBar({ children }: { children?: React.ReactNode }) {
  const { filter, update } = useUrlFilter();
  const meta = useMeta();
  const range = meta.data?.date_range;

  return (
    <div className="filters">
      <label>
        Nguồn
        <select value={filter.source ?? ""} onChange={(e) => update({ source: e.target.value })}>
          <option value="">Tất cả</option>
          {meta.data?.sources.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
      </label>
      <label>
        Từ ngày
        <input type="date" value={filter.date_from ?? ""} min={range?.min_date ?? undefined}
               max={range?.max_date ?? undefined} onChange={(e) => update({ date_from: e.target.value })} />
      </label>
      <label>
        Đến ngày
        <input type="date" value={filter.date_to ?? ""} min={range?.min_date ?? undefined}
               max={range?.max_date ?? undefined} onChange={(e) => update({ date_to: e.target.value })} />
      </label>
      {children}
      <button className="ghost" onClick={() =>
        update({ source: "", date_from: "", date_to: "", category: "", q: "", issue: "" })}>
        Bỏ lọc
      </button>
    </div>
  );
}
