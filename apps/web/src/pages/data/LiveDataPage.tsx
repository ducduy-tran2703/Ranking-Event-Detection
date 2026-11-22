import { useState, type CSSProperties, type ReactNode } from "react";
import { Link } from "react-router";
import type { LiveOverview } from "../../api/client";
import { useLiveOverview } from "../../api/queries";
import { IconAlert, IconCheck } from "../../components/Icons";
import { SourceChip } from "../../components/SourceBadge";
import { ErrorBox, Loading } from "../../components/Status";
import { ddmm, fmtDec, fmtInt, fmtMB, fmtPct, fmtShort, timeAgo, vnClock } from "../../lib/format";
import { eventHref } from "../../lib/routes";
import { sourceMeta, sourceName } from "../../lib/sources";
import { useTitle } from "../../lib/useTitle";
import { DataNav } from "./DataNav";

type D = LiveOverview;
type Mode = "ingested" | "published";
type Health = "ok" | "warn" | "bad";

const delay = (s: number): CSSProperties => ({ animationDelay: `${s}s` });
const STALE_HOURS = 6;              // báo không có bài mới quá 6 giờ (crawler chạy 30 phút/lần) → cảnh báo
const WORKER_LATE_MIN = 15;         // worker chạy 5 phút/lần; còn bài chờ mà vòng cuối quá 15 phút → cảnh báo
const STEPS = [["embed", "Embedding"], ["recluster", "Gom cụm"], ["name", "Đặt tên"], ["trend", "Xu hướng"]] as const;
const NAME_SOURCE: Record<string, string> = {
  model: "Mô hình đặt tên (ViT5)", medoid: "Tiêu đề bài đại diện", title: "Tiêu đề bài", editor: "Biên tập viên sửa",
};
const STATUS_VI: Record<string, string> = {
  ok: "ổn", failed: "lỗi", blocked: "bị chặn", running: "đang chạy", completed: "xong", partial: "xong một phần",
  interrupted: "bị ngắt", queued: "chờ", open: "đang mở", closed: "đã đóng", merged: "đã gộp", hidden: "ẩn",
};
const TABLE_VI: Record<string, string> = {
  articles: "Bài báo", article_embeddings: "Vector embedding", events: "Sự kiện", event_articles: "Bài ↔ sự kiện",
  event_names: "Tên sự kiện (lịch sử)", event_assignment_log: "Nhật ký chuyển bài", trend_scores: "Điểm xu hướng",
  article_ner: "Thực thể (NER) cho RAG", rag_chunks: "Đoạn văn RAG", crawl_runs: "Lượt nạp bài", worker_runs: "Bước worker",
};
const SECTIONS = [
  ["duong-ong", "Đường ống"], ["theo-gio", "48 giờ qua"], ["tung-bao", "Từng báo"], ["theo-ngay", "14 ngày"],
  ["worker", "Worker"], ["su-kien", "Sự kiện"], ["luot-cao", "Lượt cào"], ["luu-tru", "Lưu trữ"],
] as const;

const hoursSince = (iso: string | null | undefined, now: number) => (iso ? (now - Date.parse(iso)) / 3.6e6 : Infinity);
const sum = (xs: number[]) => xs.reduce((a, b) => a + b, 0);
const statusVi = (s: string | null | undefined) => (s ? STATUS_VI[s] ?? s : "—");
const secs = (s: number | null | undefined) => (s == null ? "—" : s < 1 ? `${fmtDec(s, 2)} s` : `${fmtDec(s, s < 10 ? 1 : 0)} s`);

/** Số liệu trực tiếp của máy chủ: đọc Postgres đang chạy + dịch vụ crawler, tự cập nhật 30 giây/lần. */
export function LiveDataPage() {
  useTitle("Dữ liệu máy chủ");
  const [live, setLive] = useState(true);
  const q = useLiveOverview(live);

  return (
    <div className="page">
      <DataNav />
      <div className="page-head rise live-head">
        <div>
          <h1>Dữ liệu máy chủ</h1>
          <p>Toàn bộ số trên trang đọc thẳng từ Postgres đang chạy và dịch vụ crawler: bài vừa cào, các lượt nạp, từng vòng
            worker gom sự kiện, dung lượng lưu trữ. Khác trang Chất lượng dữ liệu (kho Silver tĩnh), trang này đổi theo từng phút.</p>
        </div>
        <div className="live-controls" role="group" aria-label="Cập nhật dữ liệu">
          <span className={`live-pulse${live && !q.isError ? " on" : ""}`} aria-hidden="true" />
          <span className="hint" style={{ margin: 0 }} aria-live="polite">
            {q.data ? <>Cập nhật {vnClock(q.data.generated_at).hhmm}{q.isFetching ? " · đang tải…" : ""}</> : "Đang tải…"}
          </span>
          <button type="button" className="btn-ghost sm" aria-pressed={!live} onClick={() => setLive((v) => !v)}>
            {live ? "Dừng tự cập nhật" : "Bật tự cập nhật"}
          </button>
          <button type="button" className="btn-ghost sm" onClick={() => q.refetch()} disabled={q.isFetching}>Tải lại</button>
        </div>
      </div>

      {q.isPending && <Loading lines={6} h={44} />}
      {q.error && !q.data && (
        <ErrorBox error={q.error} onRetry={() => q.refetch()}
                  hint="Trang này cần API ở cổng 8000 nối được Postgres (DATABASE_URL). Kiểm tra `make status`." />
      )}
      {q.data && <Body d={q.data} />}
    </div>
  );
}

function Body({ d }: { d: D }) {
  const now = Date.parse(d.generated_at);
  const [mode, setMode] = useState<Mode>("ingested");
  return (
    <>
      <nav aria-label="Các phần của trang" className="chips sys-toc rise" style={delay(.03)}>
        {SECTIONS.map(([id, label]) => <a key={id} className="chip" href={`#${id}`}>{label}</a>)}
      </nav>
      {d.clock_mode === "replay" && (
        <p className="note" role="note">Đồng hồ hệ thống đang ở chế độ phát lại (replay). Các cửa sổ 1 giờ / 24 giờ trên
          trang vẫn tính theo giờ thật của máy chủ.</p>
      )}
      <Pipeline d={d} now={now} />
      <Kpis d={d} />
      <Hourly d={d} mode={mode} setMode={setMode} />
      <Sources d={d} now={now} mode={mode} />
      <Daily d={d} />
      <Worker d={d} now={now} />
      <Events d={d} />
      <Crawls d={d} />
      <Storage d={d} />
    </>
  );
}

// ------------------------------------------------------------------ 1. Đường ống
function HealthTag({ h, children }: { h: Health; children: ReactNode }) {
  const cls = h === "ok" ? "ok" : h === "warn" ? "warn" : "bad";
  return (
    <span className={`tag live-tag ${cls}`}>
      {h === "ok" ? <IconCheck size={14} /> : <IconAlert size={14} />}{children}
    </span>
  );
}

function Pipeline({ d, now }: { d: D; now: number }) {
  const t = d.totals, c = d.crawler, w = d.worker;
  const stale = d.sources.filter((s) => hoursSince(s.last_crawled, now) > STALE_HOURS);
  const failing = d.sources.filter((s) => s.last_run_status === "failed" || s.last_run_status === "blocked" || s.stuck);
  const lastRound = w.rounds[0];
  const roundAge = lastRound ? (now - Date.parse(lastRound.started_at)) / 60_000 : Infinity;
  const lastJob = c?.jobs[0];
  const jobErrors = lastJob ? sum(lastJob.sources.map((s) => s.n_errors)) : 0;
  const ragGap = t.articles - t.rag_articles;

  const crawler: [Health, string] = !c ? ["bad", "Không liên lạc được :8002"]
    : !c.enabled ? ["warn", "Lịch cào đang tắt"] : c.active_job_id ? ["ok", "Đang cào"] : ["ok", "Đang chờ lượt kế"];
  const ingest: [Health, string] = failing.length ? ["bad", `${failing.length} báo lỗi ở lượt cuối`]
    : stale.length ? ["warn", `${stale.length} báo không có bài mới > ${STALE_HOURS} giờ`] : ["ok", "Mọi báo có bài mới"];
  const worker: [Health, string] = !lastRound ? ["bad", "Chưa có vòng nào"]
    : lastRound.status === "failed" ? ["bad", "Vòng cuối lỗi"]
    : t.not_embedded > 0 && roundAge > WORKER_LATE_MIN ? ["warn", `${fmtInt(t.not_embedded)} bài chờ xử lý`]
    : ["ok", t.not_embedded ? `${fmtInt(t.not_embedded)} bài chờ vòng kế` : "Đã xử lý hết bài"];
  const rag: [Health, string] = ragGap > 0 ? ["warn", `${fmtInt(ragGap)} bài chưa vào Hỏi đáp`] : ["ok", "Đủ mọi bài"];

  return (
    <section id="duong-ong" aria-labelledby="h-pipe" className="card pad-sm rise sys-anchor" style={delay(.06)}>
      <h2 id="h-pipe" style={{ fontSize: 18 }}>Đường ống dữ liệu lúc này</h2>
      <p className="hint" style={{ marginBottom: 14 }}>Bài đi từ trái sang phải. Mỗi khối ghi trạng thái theo số đo thật, kèm lý do khi có cảnh báo.</p>
      <ol className="live-pipe">
        <li className="live-stage">
          <div className="live-stage-name">1 · Crawler 8 báo</div>
          <HealthTag h={crawler[0]}>{crawler[1]}</HealthTag>
          <dl>
            <dt>Lịch</dt><dd>{c ? `${c.interval_minutes ?? "?"} phút/lần` : "—"}</dd>
            <dt>Lượt kế</dt><dd>{c?.next_run_at ? vnClock(c.next_run_at).hhmm : "—"}</dd>
            <dt>Job cuối</dt><dd>{lastJob ? `${fmtShort(lastJob.created_at)}, ${statusVi(lastJob.status)}` : "—"}</dd>
            <dt>Lỗi tách bài</dt><dd>{lastJob ? fmtInt(jobErrors) : "—"}</dd>
          </dl>
        </li>
        <li className="live-stage">
          <div className="live-stage-name">2 · Postgres: bài báo</div>
          <HealthTag h={ingest[0]}>{ingest[1]}</HealthTag>
          <dl>
            <dt>Tổng bài</dt><dd>{fmtInt(t.articles)}</dd>
            <dt>Mới 1 giờ</dt><dd>{fmtInt(t.new_1h)}</dd>
            <dt>Mới 24 giờ</dt><dd>{fmtInt(t.new_24h)}</dd>
            <dt>Nạp cuối</dt><dd>{timeAgo(t.last_crawled, now)}</dd>
          </dl>
        </li>
        <li className="live-stage">
          <div className="live-stage-name">3 · Worker gom sự kiện</div>
          <HealthTag h={worker[0]}>{worker[1]}</HealthTag>
          <dl>
            <dt>Vòng cuối</dt><dd>{lastRound ? timeAgo(lastRound.started_at, now) : "—"}</dd>
            <dt>Vòng có bài / 24 giờ</dt><dd>{fmtInt(w.rounds_24h)}</dd>
            <dt>Bài đã xử lý 24 giờ</dt><dd>{fmtInt(w.embedded_24h)}</dd>
            <dt>Bước lỗi 24 giờ</dt><dd>{fmtInt(w.failed_24h)}</dd>
          </dl>
        </li>
        <li className="live-stage">
          <div className="live-stage-name">4 · Web và Hỏi đáp</div>
          <HealthTag h={rag[0]}>{rag[1]}</HealthTag>
          <dl>
            <dt>Sự kiện đang mở</dt><dd>{fmtInt(t.events_by_status.open ?? 0)}</dd>
            <dt>Sự kiện mới 24 giờ</dt><dd>{fmtInt(t.events_new_24h)}</dd>
            <dt>Bài có trong RAG</dt><dd>{fmtPct(t.rag_articles, t.articles)}</dd>
            <dt>Đoạn văn RAG</dt><dd>{fmtInt(t.rag_chunks)}</dd>
          </dl>
        </li>
      </ol>
      {(stale.length > 0 || failing.length > 0) && (
        <ul className="live-warn-list">
          {failing.map((s) => (
            <li key={`f-${s.source}`}><IconAlert size={15} className="flag-mark" />
              <span><b>{sourceName(s.source)}</b>: {s.stuck ? "lượt nạp treo ở trạng thái đang chạy" : `lượt cuối ${statusVi(s.last_run_status)}`}
                {s.last_error ? ` (${s.last_error})` : ""}.</span></li>
          ))}
          {stale.map((s) => (
            <li key={`s-${s.source}`}><IconAlert size={15} className="flag-mark" />
              <span><b>{sourceName(s.source)}</b>: bài cuối vào hệ thống {timeAgo(s.last_crawled, now)} ({fmtShort(s.last_crawled)}).
                Xem log crawler (<code>data/logs/crawler.log</code>).</span></li>
          ))}
        </ul>
      )}
    </section>
  );
}

// ------------------------------------------------------------------ 2. Ô số
function Kpis({ d }: { d: D }) {
  const t = d.totals;
  const items = [
    { label: "Bài trong Postgres", value: fmtInt(t.articles), note: `đăng từ ${t.first_published?.slice(0, 4) ?? "?"} đến ${t.last_published ? fmtShort(t.last_published) : "?"}`, accent: true },
    { label: "Bài mới 24 giờ", value: fmtInt(t.new_24h), note: `${fmtInt(t.new_1h)} bài trong 1 giờ qua` },
    { label: "Sự kiện mới 24 giờ", value: fmtInt(t.events_new_24h), note: `${fmtInt(d.worker.moved_24h)} lượt chuyển bài, ${fmtInt(d.worker.merged_24h)} lần gộp` },
    { label: "Sự kiện đang mở", value: fmtInt(t.events_by_status.open ?? 0), note: `${fmtInt(t.events_by_status.closed ?? 0)} đã đóng, ${fmtInt(t.events_by_status.merged ?? 0)} đã gộp` },
    { label: "Bài đã có vector", value: fmtPct(t.embedded, t.articles), note: `${fmtInt(t.not_embedded)} bài chưa embedding` },
    { label: "Dung lượng cơ sở dữ liệu", value: fmtMB(t.db_bytes), note: `${d.tables.length} bảng chính, xem phần Lưu trữ` },
  ];
  return (
    <ul className="sys-kpis" aria-label="Số liệu tổng quan">
      {items.map((k, i) => (
        <li key={k.label} className="stat-card rise" style={delay(.08 + i * .03)}>
          <div className="label">{k.label}</div>
          <div className={`value tnum${k.accent ? " accent" : ""}`}>{k.value}</div>
          <p className="sys-kpi-note">{k.note}</p>
        </li>
      ))}
    </ul>
  );
}

// ------------------------------------------------------------------ 3. 48 giờ qua
function ModeSwitch({ mode, setMode }: { mode: Mode; setMode: (m: Mode) => void }) {
  return (
    <div className="seg" role="group" aria-label="Đếm bài theo">
      <button type="button" aria-pressed={mode === "ingested"} onClick={() => setMode("ingested")}>Giờ vào hệ thống</button>
      <button type="button" aria-pressed={mode === "published"} onClick={() => setMode("published")}>Giờ đăng</button>
    </div>
  );
}

function Hourly({ d, mode, setMode }: { d: D; mode: Mode; setMode: (m: Mode) => void }) {
  const hours = d.hourly.hours;
  const totals = hours.map((_, i) => sum(d.hourly.series.map((s) => s[mode][i])));
  const max = Math.max(1, ...totals);
  const [hover, setHover] = useState<number | null>(null);
  const idx = hover ?? totals.length - 1;
  const parts = d.hourly.series.map((s) => ({ source: s.source, n: s[mode][idx] })).filter((x) => x.n > 0).sort((a, b) => b.n - a.n);
  const c = vnClock(hours[idx]);
  const peak = totals.indexOf(max);

  return (
    <section id="theo-gio" aria-labelledby="h-hour" className="card pad-sm rise sys-anchor" style={delay(.12)}>
      <div className="card-head">
        <div>
          <h2 id="h-hour" style={{ fontSize: 18 }}>Bài theo giờ, 48 giờ qua</h2>
          <p className="hint">
            {mode === "ingested"
              ? "Giờ bài được nạp vào Postgres: cột cao là một lượt cào vừa xong (crawler chạy 30 phút/lần)."
              : "Giờ báo đăng bài: nhịp đưa tin thật của các báo, không phụ thuộc lúc crawler chạy."}
            {" "}Cao nhất {fmtInt(max)} bài lúc {vnClock(hours[peak]).hhmm} ngày {vnClock(hours[peak]).ddmm}.
          </p>
        </div>
        <ModeSwitch mode={mode} setMode={setMode} />
      </div>
      <p className="live-readout" aria-live="polite">
        <b>{c.hhmm}–{String((c.hour + 1) % 24).padStart(2, "0")}:00 ngày {c.ddmm}</b>: {fmtInt(totals[idx])} bài
        {parts.length > 0 && <> ({parts.map((p) => `${sourceName(p.source)} ${p.n}`).join(", ")})</>}
        {" "}· {fmtInt(d.hourly.events_created[idx])} sự kiện mới tạo
      </p>
      <div className="vchart-scroll">
        <div style={{ minWidth: 640 }}>
          <div className="vchart thin live-vchart" role="img" onMouseLeave={() => setHover(null)}
               aria-label={`Biểu đồ cột số bài mỗi giờ trong 48 giờ, cao nhất ${max} bài. Bảng số liệu ở dưới.`}>
            {totals.map((n, i) => (
              <div key={hours[i]} className="live-hit" onMouseEnter={() => setHover(i)}>
                <div className={`bar growy${i === idx ? " hot" : ""}`}
                     style={{ height: n ? Math.max(3, Math.round((n / max) * 150)) : 0, animationDelay: `${(i * 0.01).toFixed(2)}s` }} />
              </div>
            ))}
          </div>
          <div className="vchart-ticks thin" aria-hidden="true">
            {hours.map((h) => {
              const k = vnClock(h);
              return <span key={h}>{k.hour % 6 === 0 ? (k.hour === 0 ? k.ddmm : `${k.hour}h`) : ""}</span>;
            })}
          </div>
        </div>
      </div>
      <details className="live-details">
        <summary>Xem dạng bảng</summary>
        <div className="table-wrap" tabIndex={0}>
          <table className="live-table">
            <thead><tr><th scope="col">Giờ</th><th scope="col" className="num">Bài</th><th scope="col">Theo báo</th><th scope="col" className="num">Sự kiện mới</th></tr></thead>
            <tbody>
              {hours.map((h, i) => totals[i] || d.hourly.events_created[i] ? (
                <tr key={h}>
                  <td className="tnum">{fmtShort(h)}</td><td className="num">{fmtInt(totals[i])}</td>
                  <td>{d.hourly.series.filter((s) => s[mode][i]).map((s) => `${sourceName(s.source)} ${s[mode][i]}`).join(", ")}</td>
                  <td className="num">{fmtInt(d.hourly.events_created[i])}</td>
                </tr>
              ) : null).reverse()}
            </tbody>
          </table>
        </div>
      </details>
    </section>
  );
}

// ------------------------------------------------------------------ 4. Từng báo
function Spark({ values, max, label }: { values: number[]; max: number; label: string }) {
  return (
    <span className="live-spark" role="img" aria-label={label}>
      {values.map((v, i) => <span key={i} style={{ height: v ? Math.max(2, Math.round((v / max) * 26)) : 0 }} />)}
    </span>
  );
}

function Sources({ d, now, mode }: { d: D; now: number; mode: Mode }) {
  const series = new Map(d.hourly.series.map((s) => [s.source, s[mode]]));
  const max = Math.max(1, ...d.hourly.series.flatMap((s) => s[mode]));
  const rows = [...d.sources].sort((a, b) => b.new_24h - a.new_24h || b.total - a.total);
  return (
    <section id="tung-bao" aria-labelledby="h-src" className="card pad-sm rise sys-anchor" style={delay(.16)}>
      <h2 id="h-src" style={{ fontSize: 18 }}>Từng báo</h2>
      <p className="hint" style={{ marginBottom: 12 }}>
        Cột 48 giờ dùng chung một thang cho mọi báo ({mode === "ingested" ? "giờ vào hệ thống" : "giờ đăng"}, đổi ở biểu đồ
        trên), nên so được báo nào đưa nhiều bài hơn. Cờ chất lượng tính trên toàn bộ bài của báo.
      </p>
      <div className="table-wrap" tabIndex={0} aria-label="Bảng từng báo (cuộn ngang được)">
        <table className="wide live-table" style={{ minWidth: 980 }}>
          <thead>
            <tr>
              <th scope="col">Báo</th><th scope="col" className="num">Tổng bài</th><th scope="col" className="num">Mới 1 giờ</th>
              <th scope="col" className="num">Mới 24 giờ</th><th scope="col">48 giờ qua</th><th scope="col">Bài vào cuối</th>
              <th scope="col" className="num">Lượt nạp 24 giờ</th><th scope="col" className="num">Bị loại 24 giờ</th>
              <th scope="col">Thiếu tác giả</th><th scope="col" className="num">Thân rỗng / ngắn</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((s) => {
              const stale = hoursSince(s.last_crawled, now) > STALE_HOURS;
              const bad = s.last_run_status === "failed" || s.last_run_status === "blocked" || s.stuck;
              const values = series.get(s.source) ?? [];
              const author = s.total ? (s.flags.missing_author ?? 0) / s.total : 0;
              return (
                <tr key={s.source}>
                  <th scope="row" className="live-src"><SourceChip source={s.source} /></th>
                  <td className="num">{fmtInt(s.total)}</td>
                  <td className="num">{fmtInt(s.new_1h)}</td>
                  <td className="num"><b>{fmtInt(s.new_24h)}</b></td>
                  <td><Spark values={values} max={max} label={`${sourceName(s.source)}: ${sum(values)} bài trong 48 giờ`} /></td>
                  <td>
                    <span className="inline" style={{ flexWrap: "nowrap", gap: 6 }}>
                      {(stale || bad) && <IconAlert size={14} className="flag-mark" />}
                      <span className={stale || bad ? "live-bad-text" : undefined}>{timeAgo(s.last_crawled, now)}</span>
                    </span>
                    {bad && <span className="badge bad">{statusVi(s.last_run_status)}</span>}
                  </td>
                  <td className="num">{fmtInt(s.runs_24h)}{s.failed_24h ? <span className="badge bad" style={{ marginLeft: 6 }}>{s.failed_24h} lỗi</span> : null}</td>
                  <td className="num">{fmtInt(s.rejected_24h)}{s.seen_24h ? <span className="hint"> / {fmtInt(s.seen_24h)}</span> : null}</td>
                  <td>
                    <span className="inline" style={{ flexWrap: "nowrap" }}>
                      <span className="heat" style={{ width: 70, flex: "none" }} aria-hidden="true">
                        <span style={{ width: `${Math.min(100, author * 100)}%` }} />
                      </span>
                      <span className="tnum">{fmtPct(s.flags.missing_author ?? 0, s.total, 0)}</span>
                    </span>
                  </td>
                  <td className="num">{fmtInt(s.flags.no_body ?? 0)} / {fmtInt(s.flags.short_body ?? 0)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

// ------------------------------------------------------------------ 5. 14 ngày
const HEAT_STEPS = [14, 30, 48, 68, 88];

function Daily({ d }: { d: D }) {
  const max = Math.max(1, ...d.daily.series.flatMap((s) => s.counts));
  const step = (n: number) => (n ? HEAT_STEPS[Math.min(HEAT_STEPS.length - 1, Math.floor((n / max) * HEAT_STEPS.length))] : 0);
  const dayTotals = d.daily.days.map((_, i) => sum(d.daily.series.map((s) => s.counts[i])));
  const rows = [...d.daily.series].sort((a, b) => sum(b.counts) - sum(a.counts));
  return (
    <section id="theo-ngay" aria-labelledby="h-day" className="card pad-sm rise sys-anchor" style={delay(.2)}>
      <h2 id="h-day" style={{ fontSize: 18 }}>Bài theo ngày đăng, 14 ngày qua</h2>
      <p className="hint" style={{ marginBottom: 12 }}>
        Ô càng đậm càng nhiều bài (cùng một thang, cao nhất {fmtInt(max)} bài/ngày). Ô trống: báo không có bài nào được
        lưu cho ngày đó, thường vì crawler chưa chạy hoặc chỉ lấy bài mới trong 7 ngày.
      </p>
      <div className="table-wrap" tabIndex={0} aria-label="Bảng nhiệt số bài theo báo và ngày (cuộn ngang được)">
        <table className="live-heat">
          <thead>
            <tr>
              <th scope="col">Báo</th>
              {d.daily.days.map((day) => <th key={day} scope="col" className="tnum">{ddmm(day)}</th>)}
              <th scope="col" className="num">Tổng</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((s) => (
              <tr key={s.source}>
                <th scope="row">{sourceName(s.source)}</th>
                {s.counts.map((n, i) => {
                  const p = step(n);
                  return (
                    <td key={i} title={`${sourceName(s.source)}, ${ddmm(d.daily.days[i])}: ${fmtInt(n)} bài`}
                        style={p ? { background: `color-mix(in oklab, var(--indigo) ${p}%, var(--surface))`, color: p >= 48 ? "#fff" : "var(--ink)" } : undefined}
                        className={p ? "tnum" : "tnum live-nil"}>
                      {n ? fmtInt(n) : ""}
                    </td>
                  );
                })}
                <td className="num"><b>{fmtInt(sum(s.counts))}</b></td>
              </tr>
            ))}
            <tr className="live-heat-total">
              <th scope="row">Tổng</th>
              {dayTotals.map((n, i) => <td key={i} className="tnum">{n ? fmtInt(n) : ""}</td>)}
              <td className="num"><b>{fmtInt(sum(dayTotals))}</b></td>
            </tr>
          </tbody>
        </table>
      </div>
      <div className="live-legend" aria-hidden="true">
        <span>ít</span>{HEAT_STEPS.map((p) => <i key={p} style={{ background: `color-mix(in oklab, var(--indigo) ${p}%, var(--surface))` }} />)}<span>nhiều</span>
      </div>
    </section>
  );
}

// ------------------------------------------------------------------ 6. Worker
function stepNote(step: string, stats: Record<string, unknown>): string {
  const n = (k: string) => fmtInt(Number(stats[k] ?? 0));
  switch (step) {
    case "embed": return `${n("n_articles")} bài`;
    case "recluster": return `${n("n_new_events")} sự kiện mới · ${n("n_moved")} chuyển · ${n("n_merged")} gộp`;
    case "name": return `${n("n_generated")} tên mới / ${n("n_named")}`;
    case "trend": return `${n("n_marks")} mốc · ${n("n_events")} sự kiện`;
    default: return "";
  }
}

function Worker({ d, now }: { d: D; now: number }) {
  const w = d.worker;
  const total = (r: D["worker"]["rounds"][number]) => sum(Object.values(r.steps).map((s) => s.seconds ?? 0));
  const max = Math.max(1, ...w.rounds.map(total));
  const last = new Map(w.last_by_step.map((s) => [s.step, s]));
  return (
    <section id="worker" aria-labelledby="h-worker" className="card pad-sm rise sys-anchor" style={delay(.24)}>
      <h2 id="h-worker" style={{ fontSize: 18 }}>Worker: các vòng gần nhất</h2>
      <p className="hint" style={{ marginBottom: 12 }}>
        Mỗi 5 phút worker kiểm tra bài mới: embedding → gom cụm giữ mã sự kiện → đặt tên → tính xu hướng. Bước không có
        việc thì không ghi, nên vòng chỉ có "Xu hướng" là lúc không có bài mới.
      </p>
      <div className="chips" style={{ marginBottom: 14 }}>
        {STEPS.map(([k, label]) => {
          const s = last.get(k);
          return (
            <span key={k} className="tag outline">
              {label}: {s ? `${timeAgo(s.started_at, now)}, ${statusVi(s.status)}` : "chưa chạy"}
            </span>
          );
        })}
        <span className="tag grey">24 giờ: {fmtInt(w.new_events_24h)} sự kiện mới, {fmtInt(w.named_24h)} tên do mô hình sinh</span>
      </div>
      <div className="table-wrap" tabIndex={0} aria-label="Bảng các vòng worker (cuộn ngang được)">
        <table className="wide live-table" style={{ minWidth: 900 }}>
          <thead>
            <tr>
              <th scope="col">Bắt đầu</th><th scope="col">Thời gian</th>
              {STEPS.map(([k, label]) => <th key={k} scope="col">{label}</th>)}
              <th scope="col">Kết quả</th>
            </tr>
          </thead>
          <tbody>
            {w.rounds.map((r) => (
              <tr key={r.started_at}>
                <td className="tnum">{fmtShort(r.started_at)}</td>
                <td>
                  <span className="inline" style={{ flexWrap: "nowrap" }}>
                    <span className="heat" style={{ width: 80, flex: "none" }} aria-hidden="true">
                      <span style={{ width: `${(total(r) / max) * 100}%` }} />
                    </span>
                    <span className="tnum">{secs(total(r))}</span>
                  </span>
                </td>
                {STEPS.map(([k]) => {
                  const s = r.steps[k];
                  return (
                    <td key={k} className="live-step">
                      {s ? <><span className="tnum">{secs(s.seconds)}</span><span className="hint">{stepNote(k, s.stats)}</span>
                        {s.error && <span className="live-bad-text">{s.error}</span>}</> : <span className="hint">—</span>}
                    </td>
                  );
                })}
                <td>
                  {r.status === "ok" ? <span className="badge ok">ổn</span> : <span className="badge bad">{statusVi(r.status)}</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

// ------------------------------------------------------------------ 7. Sự kiện
function Meter({ rows, unit }: { rows: { label: ReactNode; value: number; note?: string }[]; unit: string }) {
  const max = Math.max(1, ...rows.map((r) => r.value));
  return (
    <ul className="live-meter">
      {rows.map((r, i) => (
        <li key={i}>
          <span className="live-meter-label">{r.label}</span>
          <span className="heat lg" aria-hidden="true"><span style={{ width: `${(r.value / max) * 100}%`, animationDelay: `${i * 50}ms` }} /></span>
          <span className="live-meter-val tnum">{fmtInt(r.value)} {unit}{r.note ? <span className="hint"> · {r.note}</span> : null}</span>
        </li>
      ))}
    </ul>
  );
}

function Events({ d }: { d: D }) {
  const e = d.events;
  const totalNamed = sum(Object.values(e.naming));
  return (
    <section id="su-kien" aria-labelledby="h-ev" className="sys-anchor">
      <h2 id="h-ev" className="rise" style={{ fontSize: 18, margin: "8px 0 4px" }}>Sự kiện có bài trong {e.window_days} ngày qua</h2>
      <p className="hint rise" style={{ marginBottom: 14 }}>
        {fmtInt(e.total)} sự kiện, {fmtInt(e.multi_source)} sự kiện ({fmtPct(e.multi_source, e.total, 0)}) được từ 2 báo trở lên
        đưa tin. Sự kiện một bài là tin riêng của một báo, vẫn được giữ để bài đến sau gom vào.
      </p>
      <div className="grid-2">
        <div className="card pad-sm rise" style={delay(.26)}>
          <h3 className="live-h3">Kích thước sự kiện (số bài)</h3>
          <Meter unit="sự kiện" rows={e.size_hist.map((b) => ({ label: `${b.label} bài`, value: b.events, note: `${fmtInt(b.articles)} bài` }))} />
        </div>
        <div className="card pad-sm rise" style={delay(.28)}>
          <h3 className="live-h3">Số báo cùng đưa một sự kiện</h3>
          <Meter unit="sự kiện" rows={e.sources_hist.map((b) => ({ label: `${b.n_sources} báo`, value: b.events, note: fmtPct(b.events, e.total, 1) }))} />
        </div>
        <div className="card pad-sm rise" style={delay(.3)}>
          <h3 className="live-h3">Chuyên mục (sự kiện ≥ 2 bài, xếp theo số bài)</h3>
          <Meter unit="bài" rows={e.categories.map((c) => ({ label: c.category, value: c.articles, note: `${fmtInt(c.events)} sự kiện` }))} />
        </div>
        <div className="card pad-sm rise" style={delay(.32)}>
          <h3 className="live-h3">Tên sự kiện lấy từ đâu (sự kiện ≥ 2 bài)</h3>
          <Meter unit="sự kiện" rows={Object.entries(e.naming).sort((a, b) => b[1] - a[1])
            .map(([k, v]) => ({ label: NAME_SOURCE[k] ?? k, value: v, note: fmtPct(v, totalNamed, 0) }))} />
          <p className="hint" style={{ marginTop: 10 }}>Tiêu đề bài đại diện được dùng khi tên do mô hình sinh bị bộ kiểm tra loại
            (không trung thực, lặp thực thể hoặc quá dài).</p>
        </div>
      </div>

      <div className="card pad-sm rise" style={{ ...delay(.34), marginTop: 20 }}>
        <h3 className="live-h3">Sự kiện được nhiều báo đưa nhất trong 24 giờ qua</h3>
        {e.top.length === 0 ? <p className="hint">Chưa có sự kiện nào có bài trong 24 giờ qua.</p> : (
          <ol className="live-top">
            {e.top.map((ev) => {
              const srcs = Object.entries(ev.sources).sort((a, b) => b[1] - a[1]);
              return (
                <li key={ev.event_id}>
                  <div className="live-top-main">
                    <Link to={eventHref(ev.event_id)} className="live-top-name">{ev.display_name}</Link>
                    <span className="hint">
                      {fmtInt(ev.size)} bài · {ev.n_sources} báo · {ev.category_std ?? "chưa phân loại"} · bài đầu {fmtShort(ev.first_seen)},
                      bài cuối {fmtShort(ev.last_seen)}{ev.peak_score != null ? ` · điểm nóng đỉnh ${fmtDec(ev.peak_score, 1)}` : ""}
                    </span>
                  </div>
                  <div className="live-top-src" aria-label="Số bài theo báo">
                    {srcs.map(([s, n]) => (
                      <span key={s} className="live-mini-src" title={`${sourceName(s)}: ${n} bài`}>
                        <span className="src-ini" style={{ background: sourceMeta(s).bg, color: sourceMeta(s).fg }}>{sourceMeta(s).ini}</span>
                        <b className="tnum">{n}</b>
                      </span>
                    ))}
                  </div>
                </li>
              );
            })}
          </ol>
        )}
      </div>
    </section>
  );
}

// ------------------------------------------------------------------ 8. Lượt cào
function Crawls({ d }: { d: D }) {
  const jobs = d.crawler?.jobs ?? [];
  return (
    <section id="luot-cao" aria-labelledby="h-crawl" className="card pad-sm rise sys-anchor" style={delay(.36)}>
      <h2 id="h-crawl" style={{ fontSize: 18 }}>Lượt cào và lượt nạp</h2>
      <p className="hint" style={{ marginBottom: 12 }}>
        Mỗi job của crawler cào cả 8 báo: tìm link → tải bài → tách nội dung → kiểm hợp đồng dữ liệu → nạp Postgres.
        "Bỏ" là bài không qua kiểm tra, "lỗi" là trang tải được nhưng không tách được thân bài.
      </p>
      {!d.crawler && <p className="note" role="note">Dịch vụ crawler (:8002) không trả lời, nên không có chi tiết từng job. Bật bằng <code>make up</code>.</p>}
      {jobs.map((j, i) => {
        const errs = sum(j.sources.map((s) => s.n_errors));
        const ins = sum(j.sources.map((s) => s.inserted));
        return (
          <details key={j.id ?? i} className="live-details live-job" open={i === 0}>
            <summary>
              <b className="tnum">{fmtShort(j.created_at)}</b>
              <span className={`badge ${j.status === "completed" ? "ok" : j.status === "failed" ? "bad" : "neutral"}`}>{statusVi(j.status)}</span>
              <span className="hint" style={{ margin: 0 }}>
                {j.trigger === "catch_up" ? "cào bù khung giờ" : j.trigger === "schedule" ? "theo lịch" : j.trigger ?? ""}
                {" "}· nạp mới {fmtInt(ins)} bài · {fmtInt(errs)} lỗi tách bài
              </span>
            </summary>
            <div className="table-wrap" tabIndex={0}>
              <table className="wide live-table" style={{ minWidth: 820 }}>
                <thead>
                  <tr><th scope="col">Báo</th><th scope="col">Trạng thái</th><th scope="col" className="num">Link tìm thấy</th>
                    <th scope="col" className="num">Đã xử lý</th><th scope="col" className="num">Sạch</th><th scope="col" className="num">Bỏ</th>
                    <th scope="col" className="num">Lỗi</th><th scope="col" className="num">Nạp mới</th><th scope="col">Lỗi tiêu biểu</th></tr>
                </thead>
                <tbody>
                  {j.sources.map((s) => (
                    <tr key={s.source}>
                      <th scope="row">{sourceName(s.source)}</th>
                      <td>{statusVi(s.status)}</td>
                      <td className="num">{fmtInt(s.discovered)}</td><td className="num">{fmtInt(s.processed)}</td>
                      <td className="num">{fmtInt(s.clean)}</td><td className="num">{fmtInt(s.rejected)}</td>
                      <td className="num">{s.failed ? <span className="live-bad-text">{fmtInt(s.failed)}</span> : 0}</td>
                      <td className="num"><b>{fmtInt(s.inserted)}</b></td>
                      <td className="live-err">{s.errors[0] ?? ""}{s.n_errors > 1 ? <span className="hint"> (+{s.n_errors - 1})</span> : null}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
        );
      })}
      <details className="live-details">
        <summary>{d.crawl_runs.length} lượt nạp gần nhất vào Postgres (bảng <code>crawl_runs</code>)</summary>
        <div className="table-wrap" tabIndex={0}>
          <table className="wide live-table" style={{ minWidth: 760 }}>
            <thead>
              <tr><th scope="col">Bắt đầu</th><th scope="col">Báo</th><th scope="col">Trạng thái</th><th scope="col" className="num">Thấy</th>
                <th scope="col" className="num">Mới</th><th scope="col" className="num">Cập nhật</th><th scope="col" className="num">Bị loại</th>
                <th scope="col" className="num">Thời gian</th><th scope="col">Lỗi</th></tr>
            </thead>
            <tbody>
              {d.crawl_runs.map((r) => (
                <tr key={r.run_id}>
                  <td className="tnum">{fmtShort(r.started_at)}</td><th scope="row">{sourceName(r.source)}</th>
                  <td>{r.status === "ok" ? statusVi(r.status) : <span className="badge bad">{statusVi(r.status)}</span>}</td>
                  <td className="num">{fmtInt(r.n_seen)}</td><td className="num">{fmtInt(r.n_new)}</td>
                  <td className="num">{fmtInt(r.n_updated)}</td>
                  <td className="num" title={Object.entries(r.reject_reasons).map(([k, v]) => `${k}: ${v}`).join(", ")}>{fmtInt(r.n_rejected)}</td>
                  <td className="num">{secs(r.seconds)}</td><td className="live-err">{r.error ?? ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </section>
  );
}

// ------------------------------------------------------------------ 9. Lưu trữ
function Storage({ d }: { d: D }) {
  const rows = [...d.tables].sort((a, b) => b.bytes - a.bytes);
  const tableBytes = sum(rows.map((r) => r.bytes));
  return (
    <section id="luu-tru" aria-labelledby="h-store" className="card pad-sm rise sys-anchor" style={delay(.4)}>
      <h2 id="h-store" style={{ fontSize: 18 }}>Lưu trữ trong Postgres</h2>
      <p className="hint" style={{ marginBottom: 12 }}>
        Cơ sở dữ liệu {fmtMB(d.totals.db_bytes)}; {rows.length} bảng dưới đây chiếm {fmtPct(tableBytes, d.totals.db_bytes, 0)},
        tính cả chỉ mục. Vector embedding và đoạn văn RAG nặng nhất vì mỗi bài có một vector 768 chiều và nhiều đoạn văn.
      </p>
      <Meter unit="MB" rows={rows.map((r) => ({
        label: TABLE_VI[r.table] ?? r.table, value: Math.round(r.bytes / 1e6), note: `${fmtInt(r.rows)} dòng · ${r.table}`,
      }))} />
    </section>
  );
}
