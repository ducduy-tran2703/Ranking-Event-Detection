import { useState, type FormEvent } from "react";
import {
  usePatchCrawlerSchedule, useRunCrawler, useRunRagSync, useSaveEventWorker, useSaveRagSync, useSystemSettings,
} from "../../api/adminQueries";
import type {
  CrawlerSettings, EventWorkerBlock, EventWorkerSettings, RagSyncBlock, RagSyncSettings, SystemRun,
} from "../../api/system";
import { ErrorBox, Loading, errorMessage } from "../../components/Status";
import { fmtDateTime, fmtInt, timeAgo } from "../../lib/format";
import { sourceName } from "../../lib/sources";
import { useTitle } from "../../lib/useTitle";

/** Mã lý do của bộ lập lịch RAG (eventrank/rag/auto_sync.py::Decision) → câu cho người đọc. */
const REASONS: Record<string, string> = {
  off: "chế độ đang Tắt",
  no_pending: "không có bài chờ",
  crawl_running: "đang có lượt cào, đợi xong mới đồng bộ",
  waiting_crawl: "chờ lượt cào báo kế tiếp",
  waiting_interval: "chưa tới chu kỳ",
  low_memory: "RAM trống dưới ngưỡng nên bỏ qua",
  already_running: "đang có một lượt đồng bộ khác",
  other_scheduler: "một tiến trình API khác đang giữ bộ lập lịch",
  missing_migration: "chưa áp migration 011",
  ok: "vừa đồng bộ xong",
  failed: "lần chạy gần nhất bị lỗi",
  retry_wait: "lần trước lỗi, chờ giãn cách rồi thử lại (5 → 15 → 45 phút)",
  retries_exhausted: "đã thử lại 3 lần vẫn lỗi; đợi lượt cào/chu kỳ kế tiếp",
};
const RUN_REASONS: Record<string, string> = {
  after_crawl: "sau lượt cào", interval_due: "theo chu kỳ", continue_batch: "lô tiếp theo", retry_failed: "thử lại",
  forced: "bấm tay",
};
const TRIGGERS: Record<string, string> = { auto: "Tự động", forced: "Đồng bộ ngay", manual: "Gọi API /api/rag/sync" };
const MODES: { value: RagSyncSettings["mode"]; label: string }[] = [
  { value: "after_crawl", label: "Cùng lúc với cào báo (mặc định)" },
  { value: "interval", label: "Theo chu kỳ" },
  { value: "off", label: "Tắt" },
];

const minutesLabel = (m: number) => (m % 60 === 0 ? `${m / 60} giờ` : `${m} phút`);
const secondsLabel = (s: number) => (s % 60 === 0 ? minutesLabel(s / 60) : `${s} giây`);
const seconds = (s: number | null | undefined) => (s == null ? "—" : s < 90 ? `${s.toFixed(0)} giây` : `${(s / 60).toFixed(1)} phút`);

function StatusLine({ error, ok }: { error: unknown; ok?: string | null }) {
  if (error) return <p className="form-error" role="alert">{errorMessage(error)}</p>;
  if (ok) return <p className="form-ok" role="status">{ok}</p>;
  return null;
}

function RunStatus({ status }: { status: string }) {
  const cls = ["ok", "completed"].includes(status) ? "ok" : ["failed", "partial", "interrupted"].includes(status) ? "warn" : "grey";
  const text: Record<string, string> = { ok: "xong", completed: "xong", failed: "lỗi", partial: "xong một phần",
                                         interrupted: "bị ngắt", running: "đang chạy", queued: "chờ" };
  return <span className={`tag ${cls}`}>{text[status] ?? status}</span>;
}

/** Trang Cài đặt hệ thống: chỉnh lịch cào báo, đồng bộ RAG, worker sự kiện ngay khi đang chạy. */
type Notices = { crawler?: string | null; rag?: string | null; worker?: string | null };
type NoticeProps = { notice?: string | null; setNotice: (msg: string | null) => void };

export function SettingsTab() {
  useTitle("Cài đặt hệ thống · Quản trị");
  const q = useSystemSettings();
  // Thông báo "Đã lưu" giữ ở đây: thẻ con dựng lại (key theo cài đặt máy chủ) sau khi tải lại không làm mất nó.
  const [notices, setNotices] = useState<Notices>({});
  const notice = (k: keyof Notices) => ({ notice: notices[k], setNotice: (m: string | null) => setNotices((n) => ({ ...n, [k]: m })) });
  return (
    <div className="stack fade" style={{ gap: 16 }}>
      <h1 className="sr-only">Quản trị — Cài đặt hệ thống</h1>
      <p className="info-box">
        Thay đổi ở đây có hiệu lực ngay khi các dịch vụ đang chạy, không phải sửa file cấu hình hay khởi động lại.
      </p>
      {q.isPending && <Loading lines={6} />}
      {q.error && <ErrorBox error={q.error} onRetry={() => q.refetch()} />}
      {q.data && !q.data.settings_available && (
        <p className="form-error" role="alert">
          Postgres chưa áp migration 011 (bảng <code>system_settings</code>): đồng bộ RAG và worker đang dùng mặc định, chưa lưu được
          cài đặt. Chạy <code>make db-migrate</code>.
        </p>
      )}
      {q.data && (
        <>
          <CrawlerCard key={JSON.stringify([q.data.crawler.enabled, q.data.crawler.interval_minutes, q.data.crawler.sources])}
                       crawler={q.data.crawler} {...notice("crawler")} />
          <RagCard key={`${q.data.rag_sync.updated_at ?? "mac-dinh"}`} block={q.data.rag_sync} {...notice("rag")} />
          <WorkerCard key={`${q.data.event_worker.updated_at ?? "mac-dinh"}`} block={q.data.event_worker} {...notice("worker")} />
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------- cào báo
function CrawlerCard({ crawler, notice: saved, setNotice: setSaved }: { crawler: CrawlerSettings } & NoticeProps) {
  const save = usePatchCrawlerSchedule();
  const run = useRunCrawler();
  const [enabled, setEnabled] = useState(!!crawler.enabled);
  const [interval, setIntervalMin] = useState(crawler.interval_minutes ?? 30);
  const [sources, setSources] = useState<string[]>(crawler.sources);
  const toggle = (s: string) => setSources((cur) => (cur.includes(s) ? cur.filter((x) => x !== s) : [...cur, s]));

  const submit = (e: FormEvent) => {
    e.preventDefault();
    setSaved(null);
    save.mutate({ enabled, interval_minutes: interval as 5 | 10 | 15 | 20 | 30 | 60,
                  sources: sources as NonNullable<Parameters<typeof save.mutate>[0]["sources"]> },
                { onSuccess: () => setSaved("Đã lưu lịch cào báo.") });
  };
  const active = crawler.jobs.find((j) => j.id === crawler.active_job_id);

  return (
    <section aria-labelledby="h-crawler" className="card pad-sm">
      <div className="card-head"><h2 id="h-crawler">Cào báo</h2>
        {crawler.reachable ? <span className={`tag ${crawler.enabled ? "ok" : "grey"}`}>{crawler.enabled ? "Đang bật" : "Đang tắt"}</span>
          : <span className="tag warn">Dịch vụ không chạy</span>}</div>
      {!crawler.reachable ? (
        <p className="form-error" role="alert">{crawler.message ?? "Không kết nối được dịch vụ cào báo."}</p>
      ) : (
        <div className="stack" style={{ gap: 14 }}>
          <div className="grid-auto">
            <div className="stat-card"><div className="label">Lượt kế tiếp</div>
              <div className="value" style={{ fontSize: 17, marginTop: 4 }}>{crawler.enabled ? fmtDateTime(crawler.next_run_at) : "lịch đang tắt"}</div></div>
            <div className="stat-card"><div className="label">Lượt đang chạy</div>
              <div className="value" style={{ fontSize: 17, marginTop: 4 }}>{active ? `từ ${fmtDateTime(active.started_at ?? active.created_at)}` : crawler.active_job_id ? "đang chạy" : "không có"}</div>
              {active && <div className="note">{active.sources.length} báo · {fmtInt(active.sources.reduce((a, s) => a + s.inserted, 0))} bài mới</div>}</div>
          </div>
          <form className="stack" style={{ gap: 12 }} onSubmit={submit}>
            <label className="check"><input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
              Bật lịch cào tự động</label>
            <div className="field-group" style={{ maxWidth: 260 }}>
              <label htmlFor="crawl-interval">Chu kỳ</label>
              <select id="crawl-interval" className="field" value={interval} onChange={(e) => setIntervalMin(Number(e.target.value))}>
                {crawler.interval_choices.map((m) => <option key={m} value={m}>{minutesLabel(m)} một lần</option>)}
              </select>
            </div>
            <fieldset className="field-group" style={{ border: 0, padding: 0, margin: 0 }}>
              <legend className="label" style={{ marginBottom: 6 }}>Báo được cào</legend>
              <div className="chips">
                {crawler.all_sources.map((s) => (
                  <label key={s} className="check" style={{ minWidth: 150 }}>
                    <input type="checkbox" checked={sources.includes(s)} onChange={() => toggle(s)} />{sourceName(s)}
                  </label>
                ))}
              </div>
              {!sources.length && <span className="field-error">Chọn ít nhất một báo.</span>}
            </fieldset>
            <div className="inline">
              <button type="submit" className="btn sm pill solid" disabled={save.isPending || !sources.length}>
                {save.isPending ? "Đang lưu…" : "Lưu lịch cào"}</button>
              <button type="button" className="btn-ghost sm pill" disabled={run.isPending || !!crawler.active_job_id}
                      onClick={() => run.mutate(undefined)}>{run.isPending ? "Đang gửi…" : "Cào ngay"}</button>
            </div>
            <StatusLine error={save.error} ok={saved} />
            <StatusLine error={run.error} ok={run.data?.message} />
          </form>
          {crawler.jobs.length > 0 && (
            <div className="table-wrap" tabIndex={0} aria-label="Các lượt cào gần nhất">
              <table className="wide">
                <thead><tr><th scope="col">Bắt đầu</th><th scope="col">Kích hoạt</th><th scope="col">Trạng thái</th>
                  <th scope="col" className="num">Báo</th><th scope="col" className="num">Bài mới</th><th scope="col">Xong lúc</th></tr></thead>
                <tbody>{crawler.jobs.map((j) => (
                  <tr key={j.id ?? j.created_at ?? ""}>
                    <td className="tnum">{fmtDateTime(j.started_at ?? j.created_at)}</td>
                    <td>{({ manual: "Bấm tay", scheduled: "Theo lịch", catch_up: "Bù lịch" } as Record<string, string>)[j.trigger ?? ""] ?? j.trigger ?? "—"}</td>
                    <td><RunStatus status={j.status ?? "?"} /></td>
                    <td className="num">{j.sources.length}</td>
                    <td className="num">{fmtInt(j.sources.reduce((a, s) => a + s.inserted, 0))}</td>
                    <td className="tnum">{fmtDateTime(j.finished_at)}</td>
                  </tr>))}</tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </section>
  );
}

// ---------------------------------------------------------------------- đồng bộ RAG
function RunsTable({ runs }: { runs: SystemRun[] }) {
  if (!runs.length) return <p className="hint">Chưa có lần đồng bộ tự động nào được ghi lại.</p>;
  return (
    <div className="table-wrap" tabIndex={0} aria-label="Các lần đồng bộ RAG gần nhất">
      <table className="wide">
        <thead><tr><th scope="col">Bắt đầu</th><th scope="col">Kích hoạt</th><th scope="col">Trạng thái</th>
          <th scope="col" className="num">Bài NER</th><th scope="col" className="num">Chunk mới</th>
          <th scope="col">Thời gian</th><th scope="col">Lỗi</th></tr></thead>
        <tbody>{runs.map((r) => {
          const st = r.stats as Record<string, unknown>;
          return (
            <tr key={r.run_id}>
              <td className="tnum">{fmtDateTime(r.started_at)}</td>
              <td>{TRIGGERS[r.trigger ?? ""] ?? r.trigger ?? "—"}{r.reason && RUN_REASONS[r.reason] && r.trigger === "auto"
                ? <span className="small muted"> · {RUN_REASONS[r.reason]}</span> : null}</td>
              <td><RunStatus status={r.status} />{st.limited === true && <span className="tag grey" style={{ marginLeft: 6 }}>còn lô sau</span>}</td>
              <td className="num">{fmtInt(Number(st.ner_articles ?? 0))}</td>
              <td className="num">{fmtInt(Number(st.chunks_inserted ?? 0))}</td>
              <td>{seconds(r.seconds)}</td>
              <td className="small" style={{ color: r.error ? "var(--danger)" : undefined }}>{r.error ?? "—"}</td>
            </tr>
          );
        })}</tbody>
      </table>
    </div>
  );
}

function RagCard({ block, notice: saved, setNotice: setSaved }: { block: RagSyncBlock } & NoticeProps) {
  const save = useSaveRagSync();
  const runNow = useRunRagSync();
  const [draft, setDraft] = useState<RagSyncSettings>(block.settings);
  const sched = block.scheduler;
  const maxOk = draft.max_articles_per_run >= 10 && draft.max_articles_per_run <= 1000;

  const submit = (e: FormEvent) => {
    e.preventDefault();
    setSaved(null);
    save.mutate(draft, { onSuccess: () => setSaved("Đã lưu. Bộ lập lịch dùng cài đặt mới ở lần kiểm kế tiếp (≤ 1 phút).") });
  };

  return (
    <section aria-labelledby="h-rag" className="card pad-sm">
      <div className="card-head"><h2 id="h-rag">Đồng bộ RAG (chatbot)</h2>
        <span className={`tag ${block.running ? "ok" : "grey"}`}>{block.running ? "Đang đồng bộ" : "Đang rảnh"}</span></div>
      <div className="stack" style={{ gap: 14 }}>
        <p className="info-box">
          Mỗi lần đồng bộ: BamiBERT nhận diện thực thể bài mới (CPU, có thể vài phút), rồi Qwen trên Modal tạo vector —
          việc này <strong>có thể bật GPU Modal (tốn tiền)</strong>. Trong lúc ghi chỉ mục, chatbot tạm báo “đang đồng bộ”
          và người dùng phải hỏi lại sau ít phút.
        </p>
        {!block.env_enabled && (
          <p className="form-error" role="alert">Bộ lập lịch đang tắt bằng biến môi trường <code>RAG_AUTO_SYNC=0</code>: chỉ đồng bộ khi bấm
            “Đồng bộ ngay”.</p>
        )}
        <div className="grid-auto">
          <div className="stat-card"><div className="label">Bài chờ đồng bộ</div>
            <div className="value accent">{block.pending_articles == null ? "?" : fmtInt(block.pending_articles)}</div>
            {block.without_ner != null && <div className="note">{fmtInt(block.without_ner)} bài chưa có NER</div>}</div>
          <div className="stat-card"><div className="label">Lần kiểm gần nhất</div>
            <div className="value" style={{ fontSize: 17, marginTop: 4 }}>{sched.last_check_at ? timeAgo(sched.last_check_at) : "—"}</div>
            <div className="note">{sched.last_decision ? REASONS[sched.last_decision] ?? sched.last_decision
              : sched.scheduler_running ? "đang khởi động" : "bộ lập lịch không chạy trong tiến trình này"}
              {sched.consecutive_failures ? ` · lỗi liên tiếp ${sched.consecutive_failures} lần` : ""}</div></div>
        </div>
        <form className="stack" style={{ gap: 12 }} onSubmit={submit}>
          <div className="field-group">
            <span className="label" id="rag-mode">Chế độ</span>
            <div className="seg" role="group" aria-labelledby="rag-mode">
              {MODES.map((m) => (
                <button key={m.value} type="button" aria-pressed={draft.mode === m.value}
                        onClick={() => setDraft({ ...draft, mode: m.value })}>{m.label}</button>
              ))}
            </div>
            <span className="field-hint">
              {draft.mode === "after_crawl" && "Sau mỗi lượt cào báo nạp xong vào Postgres (và không còn lượt cào nào đang chạy)."}
              {draft.mode === "interval" && "Đều đặn theo chu kỳ, chỉ khi có bài chờ."}
              {draft.mode === "off" && "Không tự đồng bộ; vẫn bấm “Đồng bộ ngay” được."}
            </span>
          </div>
          <div className="grid-auto">
            {draft.mode === "interval" && (
              <div className="field-group">
                <label htmlFor="rag-interval">Chu kỳ</label>
                <select id="rag-interval" className="field" value={draft.interval_minutes}
                        onChange={(e) => setDraft({ ...draft, interval_minutes: Number(e.target.value) as RagSyncSettings["interval_minutes"] })}>
                  {block.interval_choices.map((m) => <option key={m} value={m}>{minutesLabel(m)} một lần</option>)}
                </select>
              </div>
            )}
            <div className="field-group">
              <label htmlFor="rag-max">Số bài tối đa mỗi lần</label>
              <input id="rag-max" className="field" type="number" min={10} max={1000} step={10} value={draft.max_articles_per_run}
                     onChange={(e) => setDraft({ ...draft, max_articles_per_run: Number(e.target.value) })} />
              <span className={maxOk ? "field-hint" : "field-error"}>Từ 10 đến 1000; bài mới đăng trước. Còn bài thì lô sau chạy tiếp ngay.</span>
            </div>
            <div className="field-group">
              <label htmlFor="rag-mem">Bỏ qua khi RAM trống dưới (MB)</label>
              <input id="rag-mem" className="field" type="number" min={0} max={16384} step={100} value={draft.min_mem_available_mb}
                     onChange={(e) => setDraft({ ...draft, min_mem_available_mb: Number(e.target.value) })} />
            </div>
          </div>
          <div className="inline">
            <button type="submit" className="btn sm pill solid" disabled={save.isPending || !maxOk}>{save.isPending ? "Đang lưu…" : "Lưu cài đặt"}</button>
            <button type="button" className="btn-ghost sm pill" disabled={runNow.isPending || block.running}
                    onClick={() => runNow.mutate()}>{runNow.isPending ? "Đang gửi…" : "Đồng bộ ngay"}</button>
            {block.updated_at && <span className="small muted">Lưu lần cuối {fmtDateTime(block.updated_at)}{block.updated_by ? ` bởi ${block.updated_by}` : ""}</span>}
          </div>
          <StatusLine error={save.error} ok={saved} />
          <StatusLine error={runNow.error} ok={runNow.data?.message} />
        </form>
        {block.dense_published === false && (
          <p className="form-error" role="alert">Tìm kiếm ngữ nghĩa (Qdrant) đang tạm tắt, chatbot chỉ dùng BM25 cho tới lượt
            đồng bộ thành công.</p>
        )}
        {block.last_error && <p className="form-error" role="alert">Lỗi gần nhất: {block.last_error}</p>}
        <RunsTable runs={block.recent_runs} />
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------- worker sự kiện
function WorkerCard({ block, notice: saved, setNotice: setSaved }: { block: EventWorkerBlock } & NoticeProps) {
  const save = useSaveEventWorker();
  const [draft, setDraft] = useState<EventWorkerSettings>(block.settings);
  const last = block.last_run;

  const submit = (e: FormEvent) => {
    e.preventDefault();
    setSaved(null);
    save.mutate(draft, { onSuccess: () => setSaved("Đã lưu. Worker đọc lại cài đặt trong vòng 30 giây.") });
  };

  return (
    <section aria-labelledby="h-worker" className="card pad-sm">
      <div className="card-head"><h2 id="h-worker">Worker sự kiện</h2>
        <span className={`tag ${block.settings.enabled ? "ok" : "warn"}`}>{block.settings.enabled ? "Đang bật" : "Tạm dừng"}</span></div>
      <div className="stack" style={{ gap: 14 }}>
        <p className="hint">Bài mới trong Postgres → embedding → gom cụm giữ mã sự kiện → đặt tên → điểm xu hướng (<code>make worker</code>).</p>
        <div className="grid-auto">
          <div className="stat-card"><div className="label">Tiến trình worker</div>
            <div className="value" style={{ fontSize: 17, marginTop: 4 }}>{block.worker_alive ? "đang chạy" : "không thấy"}</div>
            {!block.worker_alive && <div className="note">Bật bằng <code>make worker</code></div>}</div>
          <div className="stat-card"><div className="label">Bước chạy gần nhất</div>
            <div className="value" style={{ fontSize: 17, marginTop: 4 }}>{last ? timeAgo(last.started_at) : "chưa có"}</div>
            {last && <div className="note">{last.step} · <RunStatus status={last.status} /> · {seconds(last.seconds)}</div>}
            {last?.error && <div className="note" style={{ color: "var(--danger)" }}>{last.error}</div>}</div>
        </div>
        <form className="stack" style={{ gap: 12 }} onSubmit={submit}>
          <label className="check"><input type="checkbox" checked={draft.enabled}
                                         onChange={(e) => setDraft({ ...draft, enabled: e.target.checked })} />
            Bật worker (bỏ chọn = tạm dừng: tiến trình vẫn sống nhưng bỏ qua các vòng)</label>
          <div className="field-group" style={{ maxWidth: 260 }}>
            <label htmlFor="worker-interval">Chu kỳ</label>
            <select id="worker-interval" className="field" value={draft.interval_seconds}
                    onChange={(e) => setDraft({ ...draft, interval_seconds: Number(e.target.value) as EventWorkerSettings["interval_seconds"] })}>
              {block.interval_choices.map((s) => <option key={s} value={s}>{secondsLabel(s)} một vòng</option>)}
            </select>
            {!block.updated_at && <span className="field-hint">Chưa lưu lần nào: worker đang dùng {secondsLabel(block.yaml_interval_seconds)} trong
              <code> configs/pipeline.yaml</code>.</span>}
          </div>
          <div className="inline">
            <button type="submit" className="btn sm pill solid" disabled={save.isPending}>{save.isPending ? "Đang lưu…" : "Lưu cài đặt"}</button>
            {block.updated_at && <span className="small muted">Lưu lần cuối {fmtDateTime(block.updated_at)}{block.updated_by ? ` bởi ${block.updated_by}` : ""}</span>}
          </div>
          <StatusLine error={save.error} ok={saved} />
        </form>
      </div>
    </section>
  );
}
