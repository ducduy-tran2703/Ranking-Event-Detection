import { IconCheck, IconFlag } from "../../components/Icons";
import type { CSSProperties } from "react";
import { useOverview, useQuality, useRunInfo, useTimeline } from "../../api/queries";
import { ErrorBox, Loading } from "../../components/Status";
import { ddmm, ddmmyyyy, fmtInt, fmtPct } from "../../lib/format";
import { sourceName } from "../../lib/sources";
import { useTitle } from "../../lib/useTitle";
import { DataNav } from "./DataNav";

// Giai đoạn gom cụm khi chưa có run sự kiện (configs/pipeline.yaml → trending.start/end của run v2).
const FALLBACK_PERIOD = { from: "2026-08-01", to: "2026-09-19" };
const AUTHOR_FULL = 30;            // thanh "thiếu tác giả" đầy ứng với 30% (như thiết kế)
const delay = (s: number): CSSProperties => ({ animationDelay: `${s}s` });

/** Khoảng ngày (giờ VN) của bảng xu hướng của run đang phục vụ: [xu_huong_tu, xu_huong_den − 1 giờ]. */
function usePeriod() {
  const run = useRunInfo();
  if (!run.data) return { ...FALLBACK_PERIOD, fromRun: false, pending: run.isPending };
  const from = run.data.xu_huong_tu.slice(0, 10);
  const to = new Date(Date.parse(run.data.xu_huong_den) - 3_600_000 + 7 * 3_600_000).toISOString().slice(0, 10);
  return { from, to, fromRun: true, pending: false };
}

/** Chất lượng dữ liệu (thiết kế DataQuality): số liệu từ API Silver (/api/stats/overview, /quality, /timeline). */
export function DataQualityPage() {
  useTitle("Chất lượng dữ liệu");
  const overview = useOverview();
  const quality = useQuality();
  const period = usePeriod();
  const timeline = useTimeline({ date_from: period.from, date_to: period.to }, "day");
  const pending = overview.isPending || quality.isPending;
  const error = overview.error ?? quality.error;

  return (
    <div className="page">
      <DataNav />
      <div className="page-head rise">
        <h1>Chất lượng dữ liệu</h1>
        <p>Mỗi bài được kiểm theo hợp đồng dữ liệu trước khi vào hệ thống. Bài thiếu thông tin bắt buộc bị loại; bài thiếu
          thông tin phụ chỉ bị gắn cờ, vẫn được dùng.</p>
      </div>
      {pending && <Loading lines={5} h={40} />}
      {error && <ErrorBox error={error} onRetry={() => { overview.refetch(); quality.refetch(); }} />}
      {overview.data && quality.data && (
        <Body period={period} overview={overview.data} quality={quality.data} timeline={timeline} />
      )}
    </div>
  );
}

type Overview = NonNullable<ReturnType<typeof useOverview>["data"]>;
type Quality = NonNullable<ReturnType<typeof useQuality>["data"]>;

function Body({ period, overview, quality, timeline }: {
  period: ReturnType<typeof usePeriod>; overview: Overview; quality: Quality; timeline: ReturnType<typeof useTimeline>;
}) {
  const total = overview.total;
  const issues = quality.issues_per_source;
  const inPeriod = new Map<string, number>();
  const perDay = new Map<string, number>();
  for (const r of timeline.data ?? []) {
    inPeriod.set(r.source, (inPeriod.get(r.source) ?? 0) + r.n);
    perDay.set(r.bucket, (perDay.get(r.bucket) ?? 0) + r.n);
  }
  const periodTotal = [...inPeriod.values()].reduce((a, b) => a + b, 0);
  const missingAuthor = issues.reduce((a, r) => a + r.missing_author, 0);
  const worstAuthor = [...issues].sort((a, b) => b.missing_author - a.missing_author)[0];
  const days = [...perDay.entries()].sort(([a], [b]) => a.localeCompare(b));
  const words = new Map(overview.per_source.map((s) => [s.source, s]));

  return (
    <>
      <div className="grid-auto" data-testid="quality-stats">
        <div className="stat-card rise" style={delay(.05)}>
          <div className="label">Bài trong kho Silver</div>
          <div className="value accent">{fmtInt(total.articles)}</div>
          <div className="note">{total.sources} báo · {total.categories} tên chuyên mục</div>
        </div>
        {timeline.data && periodTotal > 0 && (
          <div className="stat-card rise" style={delay(.1)}>
            <div className="label">Trong giai đoạn {ddmm(period.from)}–{ddmm(period.to)}</div>
            <div className="value">{fmtPct(periodTotal, total.articles, 0)}</div>
            <div className="note">{fmtInt(periodTotal)} bài, giai đoạn dùng để gom cụm</div>
          </div>
        )}
        <div className="stat-card rise" style={delay(.15)}>
          <div className="label">Bài bị gắn cờ thiếu tác giả</div>
          <div className="value">{fmtPct(missingAuthor, total.articles)}</div>
          <div className="note">
            {fmtInt(missingAuthor)} bài{worstAuthor?.missing_author ? `, nhiều nhất ở ${sourceName(worstAuthor.source)}` : ""}
          </div>
        </div>
        <div className="stat-card rise" style={delay(.2)}>
          <div className="label">Trung vị số từ mỗi bài</div>
          <div className="value">{fmtInt(total.median_words)}</div>
          <div className="note">{fmtInt(total.days)} ngày có bài</div>
        </div>
      </div>

      <section aria-labelledby="h-days" className="card pad-sm rise" style={delay(.15)}>
        <h2 id="h-days" style={{ fontSize: 16 }}>Số bài mỗi ngày, {ddmm(period.from)} đến {ddmmyyyy(period.to)}</h2>
        {timeline.isPending && <Loading lines={3} h={40} />}
        {timeline.error && <ErrorBox error={timeline.error} onRetry={() => timeline.refetch()} />}
        {timeline.data && days.length === 0 && <p className="hint">Không có bài nào trong giai đoạn này.</p>}
        {days.length > 0 && <DayBars days={days} />}
      </section>

      <section aria-labelledby="h-src" className="card pad-sm rise" style={delay(.2)}>
        <h2 id="h-src" style={{ fontSize: 16 }}>Từng báo</h2>
        <p className="hint" style={{ marginBottom: 12 }}>
          Tỉ lệ bài bị gắn cờ trên tổng số bài của báo. Thanh xanh: thiếu tác giả, thanh đầy ứng với {AUTHOR_FULL}%.
        </p>
        <div className="table-wrap" tabIndex={0} aria-label="Bảng chất lượng theo báo (cuộn ngang được)">
          <table className="wide" style={{ minWidth: 860 }}>
            <thead>
              <tr>
                <th scope="col">Báo</th>
                <th scope="col" className="num">Bài</th>
                <th scope="col" className="num">Trong {ddmm(period.from)}–{ddmm(period.to)}</th>
                <th scope="col">Thiếu tác giả</th>
                <th scope="col" className="num">Thân bài rỗng</th>
                <th scope="col" className="num">Thân bài &lt; {quality.short_content_words} từ</th>
                <th scope="col" className="num">Thiếu sapo</th>
                <th scope="col" className="num">Số từ (trung vị)</th>
              </tr>
            </thead>
            <tbody>
              {issues.map((r) => {
                const win = inPeriod.get(r.source);
                const pct = r.articles ? (r.missing_author / r.articles) * 100 : 0;
                return (
                  <tr key={r.source}>
                    <th scope="row" style={{ background: "none", color: "var(--text)", fontSize: 14 }}>{sourceName(r.source)}</th>
                    <td className="num">{fmtInt(r.articles)}</td>
                    <td className="num">{win == null ? "—" : `${fmtInt(win)} (${fmtPct(win, r.articles)})`}</td>
                    <td>
                      <div className="inline" style={{ flexWrap: "nowrap" }}>
                        <span className="heat lg" style={{ width: 120, flex: "none" }} aria-hidden="true">
                          <span className="grow" style={{ width: `${Math.min(100, (pct / AUTHOR_FULL) * 100)}%`,
                                                         background: "var(--accent)" }} />
                        </span>
                        <span className="tnum">{r.missing_author ? `${fmtInt(r.missing_author)} · ${fmtPct(r.missing_author, r.articles)}` : "0"}</span>
                      </div>
                    </td>
                    <td className="num">{fmtInt(r.empty_content)}</td>
                    <td className="num">{fmtInt(r.short_content)}</td>
                    <td className="num">{fmtInt(r.missing_sapo)}</td>
                    <td className="num">{fmtInt(words.get(r.source)?.median_words)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>

      <div className="grid-2">
        <section aria-labelledby="h-rules" className="card pad-sm rise" style={delay(.25)}>
          <h2 id="h-rules" style={{ fontSize: 16, marginBottom: 10 }}>Kiểm tra khi nạp</h2>
          <ul className="stack" style={{ listStyle: "none", margin: 0, padding: 0, gap: 8, fontSize: 14 }}>
            <li className="inline" style={{ flexWrap: "nowrap", alignItems: "flex-start" }}><IconCheck size={16} className="ok-mark" />Mã bài = sha256(url), không trùng URL</li>
            <li className="inline" style={{ flexWrap: "nowrap", alignItems: "flex-start" }}><IconCheck size={16} className="ok-mark" />Ngày đăng bắt buộc có múi giờ</li>
            <li className="inline" style={{ flexWrap: "nowrap", alignItems: "flex-start" }}><IconCheck size={16} className="ok-mark" />Có tiêu đề và chuyên mục</li>
            <li className="inline" style={{ flexWrap: "nowrap", alignItems: "flex-start" }}><IconFlag size={16} className="flag-mark" />Gắn cờ, không loại: thiếu sapo, thân bài rỗng hoặc dưới {quality.short_content_words} từ, thiếu tác giả, ngày ở tương lai</li>
            <li className="inline" style={{ flexWrap: "nowrap", alignItems: "flex-start" }}><IconFlag size={16} className="flag-mark" />Bài gần trùng giữa các báo được đánh dấu, không xoá: đó là tín hiệu chính để gom sự kiện</li>
          </ul>
        </section>
        <section aria-labelledby="h-known" className="card pad-sm rise" style={delay(.3)}>
          <h2 id="h-known" style={{ fontSize: 16, marginBottom: 10 }}>Hạn chế đã biết</h2>
          <KnownLimits overview={overview} quality={quality} inPeriod={inPeriod} />
        </section>
      </div>
    </>
  );
}

function DayBars({ days }: { days: [string, number][] }) {
  const max = Math.max(...days.map(([, n]) => n));
  const peak = days.find(([, n]) => n === max)!;
  const ticks = new Set([0, days.length - 1]);
  days.forEach(([d], i) => { if (d.endsWith("-01") || d.endsWith("-15")) ticks.add(i); });
  return (
    <>
      <p className="hint" style={{ marginBottom: 14 }}>
        Tổng của các báo, theo ngày đăng (giờ Việt Nam). Cao nhất {fmtInt(max)} bài ngày {ddmm(peak[0])}. Ngày cuối thấp
        nếu kho dừng giữa ngày.
      </p>
      <div className="vchart-scroll">
        <div style={{ minWidth: 640 }}>
          <div className="vchart thin" role="img" data-testid="day-chart"
               aria-label={`Biểu đồ cột số bài theo ngày, ${days.length} ngày, cao nhất ${max} bài ngày ${ddmm(peak[0])}`}>
            {days.map(([d, n], i) => (
              <div key={d} className="bar growy" title={`${ddmm(d)}: ${fmtInt(n)} bài`}
                   style={{ height: Math.round((n / max) * 150), animationDelay: `${(i * 0.012).toFixed(3)}s` }} />
            ))}
          </div>
          <div className="vchart-ticks thin" aria-hidden="true">
            {days.map(([d], i) => <span key={d}>{ticks.has(i) ? ddmm(d) : ""}</span>)}
          </div>
        </div>
      </div>
    </>
  );
}

function KnownLimits({ overview, quality, inPeriod }: { overview: Overview; quality: Quality; inPeriod: Map<string, number> }) {
  const last = overview.per_source.filter((s) => s.last_published).map((s) => ({ s: s.source, d: s.last_published!.slice(0, 10) }));
  const latest = last.reduce((m, x) => (x.d > m ? x.d : m), "");
  const early = last.filter((x) => x.d < latest);
  const lowPeriod = overview.per_source
    .map((s) => ({ s, pct: inPeriod.size ? ((inPeriod.get(s.source) ?? 0) / s.articles) * 100 : 100 }))
    .sort((a, b) => a.pct - b.pct)[0];
  const empty = [...quality.issues_per_source].sort((a, b) => b.empty_content - a.empty_content)[0];
  return (
    <ul className="stack" style={{ margin: 0, paddingLeft: 18, gap: 8, fontSize: 14, color: "var(--body-2)" }}>
      {early.length > 0 && latest && (
        <li>{early.map((x) => `${sourceName(x.s)} (${ddmm(x.d)})`).join(", ")} dừng sớm hơn; báo mới nhất tới {ddmm(latest)}.</li>
      )}
      {lowPeriod && lowPeriod.pct < 60 && (
        <li>{sourceName(lowPeriod.s.source)} có bài từ {lowPeriod.s.first_published?.slice(0, 4)} nên chỉ{" "}
          {Math.round(lowPeriod.pct)}% bài nằm trong giai đoạn gom cụm.</li>
      )}
      {/* Nguồn: docs/tong-hop.md mục 5.3 (bảng hạn chế Silver: "Mỗi chuyên mục bị giới hạn ~500 bài"). */}
      <li>Mỗi chuyên mục chỉ lấy được khoảng 500 bài gần nhất, nên số bài/ngày thấp hơn thực tế báo đăng.</li>
      {empty && empty.empty_content > 0 && (
        <li>Thân bài rỗng tập trung ở {sourceName(empty.source)} ({fmtInt(empty.empty_content)} bài,{" "}
          {fmtPct(empty.empty_content, empty.articles)}): cần xem lại bộ tách bài của báo này.</li>
      )}
    </ul>
  );
}
