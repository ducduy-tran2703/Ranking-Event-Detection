import { useState, type CSSProperties, type KeyboardEvent } from "react";
import {
  COMPONENTS, DATASETS, DB_GROUPS, DISK, ENV_VARS, FLOW, KPIS, LIMITS, MEASURED_AT, MODELS, NON_MODELS, PARAMS, STACK, TRAINING,
  type Component, type ModelState, type Zone,
} from "../../content/system";
import { useTitle } from "../../lib/useTitle";
import { DataNav } from "./DataNav";

const delay = (s: number): CSSProperties => ({ animationDelay: `${s}s` });

const ZONE: Record<Zone, { label: string; hint: string }> = {
  ngoai: { label: "Bên ngoài", hint: "nguồn tin và người dùng" },
  trong: { label: "Trong hệ thống", hint: "máy chủ của nhóm" },
  "dich-vu": { label: "Dịch vụ bên ngoài", hint: "đám mây, bên thứ ba" },
};
const KIND: Record<Component["kind"], { label: string; cls: string }> = {
  "dich-vu": { label: "Dịch vụ", cls: "outline" },
  "luu-tru": { label: "Lưu trữ", cls: "grey" },
  "mo-hinh": { label: "Mô hình", cls: "sys-model" },
  nguoi: { label: "Tác nhân", cls: "outline" },
};
const STATE: Record<ModelState, { label: string; cls: string }> = {
  "dang-dung": { label: "Đang chạy", cls: "ok" },
  "du-phong": { label: "Dự phòng / so sánh", cls: "outline" },
  moc: { label: "Mốc so sánh", cls: "grey" },
  "huan-luyen": { label: "Chỉ khi dựng dữ liệu", cls: "warn" },
};

const SECTIONS = [
  ["so-do", "Sơ đồ"], ["thanh-phan", "Trong / ngoài"], ["hanh-trinh", "Luồng dữ liệu"], ["mo-hinh", "Mô hình"],
  ["du-lieu", "Bộ dữ liệu"], ["luu-tru", "Nơi lưu"], ["thong-so", "Thông số"], ["cong-nghe", "Công nghệ"], ["gioi-han", "Giới hạn"],
] as const;

/** Trang mô tả toàn bộ hệ thống để thuyết trình — nội dung tĩnh ở src/content/system.ts (mỗi nhóm số ghi nguồn). */
export function SystemPage() {
  useTitle("Kiến trúc hệ thống");
  const [sel, setSel] = useState("Worker");
  const picked = COMPONENTS.find((c) => c.name === sel) ?? COMPONENTS[0];

  return (
    <div className="page">
      <DataNav />
      <div className="page-head rise">
        <h1>Kiến trúc hệ thống EventRank</h1>
        <p>
          Từ bài báo của 8 trang tin đến bảng xu hướng và hỏi đáp: thành phần nào chạy trong hệ thống, phần nào thuê ngoài,
          đâu là mô hình học máy, dữ liệu nằm ở đâu. Số liệu đo ngày {MEASURED_AT} trên máy chạy demo.
        </p>
      </div>

      <nav aria-label="Các phần của trang" className="chips sys-toc rise" style={delay(.03)}>
        {SECTIONS.map(([id, label]) => <a key={id} className="chip" href={`#${id}`}>{label}</a>)}
      </nav>

      <ul className="sys-kpis" aria-label="Số liệu tổng quan">
        {KPIS.map((k, i) => (
          <li key={k.label} className="stat-card rise" style={delay(.05 + i * .04)}>
            <div className="label">{k.label}</div>
            <div className="value accent tnum">{k.value}</div>
            <p className="sys-kpi-note">{k.note}</p>
          </li>
        ))}
      </ul>

      {/* ── 1. Sơ đồ ── */}
      <section id="so-do" aria-labelledby="h-so-do" className="card pad-sm rise sys-anchor" style={delay(.1)}>
        <h2 id="h-so-do" style={{ fontSize: 18 }}>1. Sơ đồ kiến trúc</h2>
        <p className="hint" style={{ marginBottom: 10 }}>
          Bấm vào một khối để xem chi tiết. Nét liền: gọi khi hệ thống đang chạy (chấm chạy theo chiều dữ liệu). Nét đứt: làm tay
          hoặc chỉ lúc huấn luyện.
        </p>
        <div className="sys-diagram-wrap" tabIndex={0} aria-label="Sơ đồ kiến trúc (cuộn ngang được trên màn hình hẹp)">
          <Diagram sel={sel} onSelect={setSel} />
        </div>
        <div className="sys-legend" aria-hidden="true">
          <span><i className="lg-zone in" />Trong hệ thống</span>
          <span><i className="lg-zone out" />Bên ngoài</span>
          <span><i className="lg-node svc" />Dịch vụ</span>
          <span><i className="lg-node store" />Lưu trữ</span>
          <span><i className="lg-node model" />Mô hình học máy</span>
          <span><i className="lg-line" />Khi chạy</span>
          <span><i className="lg-line dash" />Làm tay / huấn luyện</span>
        </div>
        <div className="sys-detail" aria-live="polite">
          <div className="inline" style={{ gap: 8 }}>
            <strong style={{ fontSize: 16 }}>{picked.name}</strong>
            <span className={`tag ${KIND[picked.kind].cls}`}>{KIND[picked.kind].label}</span>
            <span className="tag outline">{ZONE[picked.zone].label}</span>
          </div>
          <div className="small muted" style={{ marginTop: 4 }}>{picked.where}</div>
          <p style={{ margin: "6px 0" }}>{picked.detail}</p>
          <div className="small">Mã nguồn / cấu hình: <code>{picked.code}</code></div>
        </div>
      </section>

      {/* ── 2. Trong / ngoài ── */}
      <section id="thanh-phan" aria-labelledby="h-tp" className="sys-anchor rise" style={delay(.12)}>
        <h2 id="h-tp" className="sys-h2">2. Phần nào trong, phần nào ngoài hệ thống</h2>
        <div className="sys-zones">
          {(Object.keys(ZONE) as Zone[]).map((z) => (
            <div key={z} className={`card pad-sm sys-zone ${z}`}>
              <h3>{ZONE[z].label}<span className="small muted"> · {ZONE[z].hint}</span></h3>
              <ul>
                {COMPONENTS.filter((c) => c.zone === z).map((c) => (
                  <li key={c.name}>
                    <button type="button" className={`sys-comp${c.name === sel ? " on" : ""}`}
                      onClick={() => { setSel(c.name); document.getElementById("so-do")?.scrollIntoView({ behavior: "smooth" }); }}>
                      <span className="sys-comp-name">{c.name}</span>
                      <span className={`tag ${KIND[c.kind].cls}`}>{KIND[c.kind].label}</span>
                      <span className="small muted sys-comp-where">{c.where}</span>
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
        <p className="small" style={{ marginTop: 10, color: "var(--body-2)", maxWidth: "95ch" }}>
          Ranh giới quan trọng: khi chạy, hệ thống chỉ gọi ra ngoài để <b>cào báo</b> và để <b>hỏi đáp</b> (Modal). Gom cụm, đặt tên,
          xu hướng chạy hoàn toàn trên máy chủ bằng CPU. R2, Kaggle, HuggingFace chỉ dùng khi dựng dữ liệu, huấn luyện và cài đặt.
        </p>
      </section>

      {/* ── 3. Luồng ── */}
      <section id="hanh-trinh" aria-labelledby="h-flow" className="card pad-sm rise sys-anchor" style={delay(.14)}>
        <h2 id="h-flow" style={{ fontSize: 18 }}>3. Đường đi của một bài báo</h2>
        <p className="hint" style={{ marginBottom: 12 }}>
          Bước 1–5 lặp tự động (crawler 30 phút/lần, worker 5 phút/vòng). Một vòng worker với 852 bài mới: 240 giây, RAM đỉnh 2,2 GB.
        </p>
        <ol className="sys-flow">
          {FLOW.map((s) => (
            <li key={s.n}>
              <span className="sys-flow-n" aria-hidden="true">{s.n}</span>
              <div>
                <div className="inline" style={{ gap: 8 }}>
                  <strong>{s.title}</strong>
                  {s.model && <span className="tag sys-model">{s.model}</span>}
                </div>
                <p style={{ margin: "4px 0" }}>{s.body}</p>
                <div className="small muted">Ghi vào: <code>{s.out}</code></div>
              </div>
            </li>
          ))}
        </ol>
      </section>

      {/* ── 4. Mô hình ── */}
      <section id="mo-hinh" aria-labelledby="h-models" className="card pad-sm rise sys-anchor" style={delay(.16)}>
        <h2 id="h-models" style={{ fontSize: 18 }}>4. Mô hình: tên, thông số, nơi chạy, nơi lưu</h2>
        <p className="hint" style={{ marginBottom: 12 }}>
          Số tham số đếm trực tiếp từ file trọng số. Số trong ngoặc vuông là khoảng tin cậy 95% (bootstrap). Chi tiết so sánh: trang Mô hình.
        </p>
        <div className="table-wrap" tabIndex={0} aria-label="Bảng mô hình (cuộn ngang được)">
          <table className="sys-table" style={{ minWidth: 1090 }}>
            <thead>
              <tr>
                <th scope="col">Mô hình</th><th scope="col">Kiến trúc gốc</th><th scope="col">Tham số</th>
                <th scope="col">Thông số</th><th scope="col">Chạy ở</th><th scope="col">Lưu ở</th><th scope="col">Kết quả đo</th>
              </tr>
            </thead>
            <tbody>
              {MODELS.map((m) => (
                <tr key={m.name} className={m.state === "dang-dung" ? "sys-used" : undefined}>
                  <th scope="row">
                    <div style={{ fontWeight: 700 }}>{m.name}</div>
                    <div className="small muted" style={{ fontWeight: 500 }}>{m.role}</div>
                    <span className={`tag ${STATE[m.state].cls}`} style={{ marginTop: 4 }}>{STATE[m.state].label}</span>
                  </th>
                  <td className="small">{m.base}</td>
                  <td className="tnum nowrap" style={{ fontWeight: 700 }}>{m.params}</td>
                  <td className="small">{m.shape}</td>
                  <td className="small">{m.runs}</td>
                  <td className="small sys-path wide"><Paths text={m.stored} /></td>
                  <td className="small">{m.metric}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <h3 className="sys-h3">Không phải mô hình học máy (không có trọng số, không huấn luyện)</h3>
        <ul className="sys-plain">
          {NON_MODELS.map((n) => <li key={n.name}><b>{n.name}</b>: {n.what}</li>)}
        </ul>
        <h3 className="sys-h3">Huấn luyện (ngoài hệ thống)</h3>
        <ul className="sys-plain">{TRAINING.map((t) => <li key={t}>{t}</li>)}</ul>
      </section>

      {/* ── 5. Bộ dữ liệu ── */}
      <section id="du-lieu" aria-labelledby="h-ds" className="card pad-sm rise sys-anchor" style={delay(.18)}>
        <h2 id="h-ds" style={{ fontSize: 18 }}>5. Các bộ dữ liệu</h2>
        <p className="hint" style={{ marginBottom: 12 }}>
          R2 = bucket <code>vietnam-news-datalake</code> trên Cloudflare R2, không có versioning nên mỗi bản mới ghi vào thư mục mới.
        </p>
        <div className="table-wrap" tabIndex={0} aria-label="Bảng bộ dữ liệu (cuộn ngang được)">
          <table className="sys-table" style={{ minWidth: 1090 }}>
            <thead>
              <tr>
                <th scope="col">Bộ dữ liệu</th><th scope="col">Nội dung</th><th scope="col">Dung lượng</th>
                <th scope="col">Dùng cho</th><th scope="col">Trên máy</th><th scope="col">Trên R2</th>
              </tr>
            </thead>
            <tbody>
              {DATASETS.map((d) => (
                <tr key={d.name}>
                  <th scope="row" style={{ fontWeight: 700 }}>{d.name}</th>
                  <td className="small">{d.content}</td>
                  <td className="tnum small nowrap">{d.size}</td>
                  <td className="small">{d.use}</td>
                  <td className="small sys-path wide"><Paths text={d.local} /></td>
                  <td className="small sys-path wide"><Paths text={d.r2} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* ── 6. Nơi lưu ── */}
      <section id="luu-tru" aria-labelledby="h-store" className="sys-anchor rise" style={delay(.2)}>
        <h2 id="h-store" className="sys-h2">6. Nơi lưu dữ liệu khi hệ thống chạy</h2>
        <p className="hint" style={{ marginBottom: 12 }}>PostgreSQL 586 MB, 34 bảng theo 9 migration. Số dòng và dung lượng đo {MEASURED_AT}.</p>
        <div className="sys-db">
          {DB_GROUPS.map((g) => (
            <div key={g.migration} className="card pad-sm">
              <h3 className="sys-h3" style={{ marginTop: 0 }}>{g.title} <span className="small muted">· migration {g.migration}</span></h3>
              <ul className="sys-tables">
                {g.tables.map((t) => (
                  <li key={t.name}>
                    <div className="sys-tbl-names">
                      {t.name.split(", ").map((n) => <code key={n}>{n}</code>)}
                      {(t.rows || t.size) && <span className="small tnum sys-tbl-num">{[t.rows, t.size].filter(Boolean).join(" · ")}</span>}
                    </div>
                    <div className="small muted">{t.what}</div>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
        <div className="card pad-sm" style={{ marginTop: 16 }}>
          <h3 className="sys-h3" style={{ marginTop: 0 }}>File trên máy chủ (thư mục <code>data/</code>, không đưa lên git)</h3>
          <ul className="sys-disk">
            {DISK.map((d) => (
              <li key={d.path}>
                <code>{d.path}</code>
                <span className="small muted">{d.what}</span>
                <span className="tnum" style={{ fontWeight: 700, textAlign: "right" }}>{d.size}</span>
              </li>
            ))}
          </ul>
        </div>
      </section>

      {/* ── 7. Thông số ── */}
      <section id="thong-so" aria-labelledby="h-params" className="sys-anchor rise" style={delay(.22)}>
        <h2 id="h-params" className="sys-h2">7. Thông số cấu hình</h2>
        <div className="sys-params">
          {PARAMS.map((g) => (
            <div key={g.title} className="card pad-sm">
              <h3 className="sys-h3" style={{ marginTop: 0 }}>{g.title}</h3>
              <div className="small muted" style={{ marginBottom: 8 }}><code>{g.file}</code></div>
              <dl className="sys-dl">
                {g.rows.map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{v}</dd></div>)}
              </dl>
            </div>
          ))}
        </div>
        <div className="card pad-sm" style={{ marginTop: 16 }}>
          <h3 className="sys-h3" style={{ marginTop: 0 }}>Biến môi trường (<code>.env</code>, chỉ tên, không công bố giá trị)</h3>
          <dl className="sys-dl">
            {ENV_VARS.map((e) => <div key={e.name}><dt><code>{e.name}</code></dt><dd>{e.what}</dd></div>)}
          </dl>
        </div>
      </section>

      {/* ── 8. Công nghệ ── */}
      <section id="cong-nghe" aria-labelledby="h-stack" className="card pad-sm rise sys-anchor" style={delay(.24)}>
        <h2 id="h-stack" style={{ fontSize: 18 }}>8. Công nghệ và lệnh vận hành</h2>
        <dl className="sys-dl" style={{ marginTop: 8 }}>
          {STACK.map((s) => <div key={s.layer}><dt>{s.layer}</dt><dd>{s.items}</dd></div>)}
        </dl>
        <p className="small" style={{ marginTop: 10, color: "var(--body-2)" }}>
          Bật toàn bộ: <code>make up</code> · xem trạng thái: <code>make status</code> · tắt: <code>make down</code> · cào ngay:{" "}
          <code>make crawl-now</code>. Hướng dẫn đầy đủ: <code>docs/huong-dan-chay.md</code>.
        </p>
      </section>

      {/* ── 9. Giới hạn ── */}
      <section id="gioi-han" aria-labelledby="h-limits" className="info-box rise sys-anchor" style={delay(.26)}>
        <h2 id="h-limits">9. Giới hạn cần nói rõ khi trình bày</h2>
        <ul>{LIMITS.map((l) => <li key={l}>{l}</li>)}</ul>
      </section>
    </div>
  );
}

/** Tách "a · b" và "a, b" (đường dẫn) thành từng dòng cho dễ đọc. */
function Paths({ text }: { text: string }) {
  return <>{text.split(/ · |, (?=[a-z…])/).map((t) => <div key={t}>{t}</div>)}</>;
}

// ───────────────────────────── Sơ đồ SVG ─────────────────────────────

type NodeKind = "svc" | "store" | "model" | "actor";
interface DNode { id: string; comp: string; x: number; y: number; w: number; h: number; title: string; sub: string; kind: NodeKind }

const NODES: DNode[] = [
  { id: "news", comp: "8 báo điện tử", x: 30, y: 70, w: 170, h: 80, title: "8 báo điện tử", sub: "RSS · sitemap", kind: "actor" },
  { id: "user", comp: "Người dùng", x: 30, y: 470, w: 170, h: 80, title: "Người dùng", sub: "trình duyệt", kind: "actor" },
  { id: "crawler", comp: "Crawler", x: 245, y: 70, w: 160, h: 80, title: "Crawler", sub: ":8002 · 30 phút/lần", kind: "svc" },
  { id: "pg", comp: "PostgreSQL 18", x: 450, y: 70, w: 170, h: 80, title: "PostgreSQL", sub: ":5432 · 34 bảng", kind: "store" },
  { id: "worker", comp: "Worker", x: 655, y: 50, w: 155, h: 200, title: "Worker", sub: "5 phút/vòng · CPU", kind: "svc" },
  { id: "qdrant", comp: "Qdrant 1.20", x: 245, y: 255, w: 160, h: 70, title: "Qdrant", sub: ":6333 · Docker", kind: "store" },
  { id: "bm25", comp: "Chỉ mục BM25", x: 245, y: 350, w: 160, h: 64, title: "Chỉ mục BM25", sub: "file 145 MB", kind: "store" },
  { id: "api", comp: "API FastAPI", x: 450, y: 290, w: 170, h: 80, title: "API FastAPI", sub: ":8000", kind: "svc" },
  { id: "web", comp: "Web React", x: 450, y: 470, w: 170, h: 80, title: "Web React", sub: ":5173", kind: "svc" },
  { id: "r2", comp: "Cloudflare R2", x: 860, y: 60, w: 215, h: 90, title: "Cloudflare R2", sub: "kho chung của nhóm", kind: "store" },
  { id: "kaggle", comp: "Kaggle (GPU T4)", x: 860, y: 185, w: 215, h: 75, title: "Kaggle T4 + HuggingFace", sub: "chỉ lúc huấn luyện", kind: "svc" },
  { id: "modal", comp: "Modal (GPU thuê)", x: 860, y: 300, w: 215, h: 175, title: "Modal (GPU thuê)", sub: "tự tắt sau 120 s rảnh", kind: "svc" },
];
/** Khối mô hình nằm bên trong worker / Modal. */
const CHIPS: { comp: string; x: number; y: number; w: number; label: string }[] = [
  { comp: "bkai fine-tune v1", x: 667, y: 150, w: 131, label: "bkai v1 · 135 tr" },
  { comp: "ViT5 đặt tên v1", x: 667, y: 196, w: 131, label: "ViT5 · 226 tr" },
  { comp: "Qwen3-Embedding 0.6B", x: 875, y: 365, w: 185, label: "Qwen3-Embedding 0.6B" },
  { comp: "Gemma 4 12B (4-bit)", x: 875, y: 415, w: 185, label: "Gemma 4 12B · vLLM" },
];
interface DEdge { d: string; dash?: boolean; label?: string; lx?: number; ly?: number; dur?: number }
const EDGES: DEdge[] = [
  { d: "M200 110 L243 110", dur: 1.4 },
  { d: "M405 110 L448 110", dur: 1.4 },
  { d: "M620 95 L653 95", dur: 1.2 },
  { d: "M655 128 L622 128", dur: 1.2 },
  { d: "M535 150 L535 288", label: "sự kiện, điểm", lx: 545, ly: 222, dur: 2 },
  { d: "M450 318 L407 298", dur: 1.3 },
  { d: "M450 345 L407 372", dur: 1.3 },
  { d: "M620 345 L858 345", label: "HTTPS · câu hỏi", lx: 740, ly: 336, dur: 2.2 },
  { d: "M535 470 L535 372", label: "/api · JSON", lx: 545, ly: 425, dur: 1.6 },
  { d: "M200 510 L448 510", label: "HTTP", lx: 324, ly: 500, dur: 2 },
  { d: "M967 185 L967 152", dash: true },
  { d: "M860 100 L812 100", dash: true, label: "tải tay", lx: 836, ly: 90 },
];

function Diagram({ sel, onSelect }: { sel: string; onSelect: (c: string) => void }) {
  const act = (c: string) => ({
    role: "button" as const, tabIndex: 0, "aria-pressed": sel === c, "aria-label": c,
    onClick: (e: React.MouseEvent) => { e.stopPropagation(); onSelect(c); },
    onKeyDown: (e: KeyboardEvent) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onSelect(c); } },
  });
  return (
    <svg className="sys-diagram" viewBox="0 0 1100 600" role="group" aria-label="Sơ đồ kiến trúc hệ thống">
      <defs>
        <marker id="sys-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M0 0 L10 5 L0 10 z" className="sys-arrowhead" />
        </marker>
      </defs>

      <rect className="sys-z out" x="10" y="10" width="205" height="580" rx="18" />
      <rect className="sys-z in" x="225" y="10" width="605" height="580" rx="18" />
      <rect className="sys-z out" x="840" y="10" width="250" height="580" rx="18" />
      <text className="sys-z-label" x="22" y="36">BÊN NGOÀI</text>
      <text className="sys-z-label in" x="240" y="36">TRONG HỆ THỐNG · MÁY CHỦ</text>
      <text className="sys-z-label" x="852" y="36">DỊCH VỤ BÊN NGOÀI</text>

      {EDGES.map((e, i) => (
        <g key={i}>
          <path d={e.d} className={`sys-edge${e.dash ? " dash" : ""}`} markerEnd="url(#sys-arrow)" />
          {e.label && <text className="sys-edge-label" x={e.lx} y={e.ly} textAnchor={e.lx && e.lx > 540 && e.lx < 560 ? "start" : "middle"}>{e.label}</text>}
          {!e.dash && (
            <circle r="3.6" className="sys-dot">
              <animateMotion dur={`${e.dur ?? 1.6}s`} repeatCount="indefinite" path={e.d} begin={`${(i % 4) * .35}s`} />
            </circle>
          )}
        </g>
      ))}

      {NODES.map((n) => (
        <g key={n.id} className={`sys-node ${n.kind}${sel === n.comp ? " on" : ""}`} {...act(n.comp)}>
          <rect x={n.x} y={n.y} width={n.w} height={n.h} rx="14" />
          <text className="sys-node-title" x={n.x + n.w / 2} y={n.y + (n.h > 120 ? 30 : n.h / 2 - 2)} textAnchor="middle">{n.title}</text>
          <text className="sys-node-sub" x={n.x + n.w / 2} y={n.y + (n.h > 120 ? 50 : n.h / 2 + 18)} textAnchor="middle">{n.sub}</text>
        </g>
      ))}
      <text className="sys-node-sub" x="732" y="118" textAnchor="middle">embed → gom cụm</text>
      <text className="sys-node-sub" x="732" y="136" textAnchor="middle">→ đặt tên → xu hướng</text>

      {CHIPS.map((c) => (
        <g key={c.comp} className={`sys-chip${sel === c.comp ? " on" : ""}`} {...act(c.comp)}>
          <rect x={c.x} y={c.y} width={c.w} height="36" rx="10" />
          <text x={c.x + c.w / 2} y={c.y + 23} textAnchor="middle">{c.label}</text>
        </g>
      ))}
    </svg>
  );
}
