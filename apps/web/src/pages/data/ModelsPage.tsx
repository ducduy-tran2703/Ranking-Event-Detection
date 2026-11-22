import type { CSSProperties } from "react";
import {
  CAVEATS, CLUSTERING, CLUSTERING_AXIS_FROM, CLUSTERING_NOTE, EMB_NOTE, EMBEDDINGS, NAMING, NAMING_NOTE, STEPS,
  type BarRow, type Status,
} from "../../content/models";
import { fmtDec } from "../../lib/format";
import { useTitle } from "../../lib/useTitle";
import { DataNav } from "./DataNav";

const f3 = (x: number) => fmtDec(x, 3);
const delay = (s: number): CSSProperties => ({ animationDelay: `${s}s` });
const STATUS: Record<Status, { label: string; cls: string }> = {
  "dang-dung": { label: "Đang dùng", cls: "ok" },
  "chua-danh-gia": { label: "Chưa đánh giá", cls: "warn" },
  "dang-huan-luyen": { label: "Đang huấn luyện", cls: "" },
};

/** Mô hình trong hệ thống (thiết kế Models) — nội dung tĩnh ở src/content/models.ts, mỗi số có nguồn. */
export function ModelsPage() {
  useTitle("Mô hình");
  return (
    <div className="page">
      <DataNav />
      <div className="page-head rise">
        <h1>Mô hình trong hệ thống</h1>
        <p>Bốn bước từ bài báo đến bảng xu hướng. Mỗi con số kèm mốc so sánh; số trong ngoặc vuông là khoảng tin cậy 95% (bootstrap).</p>
      </div>

      <ol className="grid-auto" style={{ listStyle: "none", margin: 0, padding: 0, gridTemplateColumns: "repeat(auto-fit, minmax(230px, 1fr))" }}>
        {STEPS.map((s, i) => (
          <li key={s.n} className="stat-card rise" style={{ ...delay(.05 + i * .06), display: "flex", flexDirection: "column", gap: 6, padding: 16 }}>
            <div className="inline" style={{ gap: 10 }}>
              <span aria-hidden="true" style={{ width: 30, height: 30, borderRadius: "50%", background: "var(--soft-2)", color: "var(--accent)",
                display: "grid", placeItems: "center", fontWeight: 800, fontSize: 14 }}>{s.n}</span>
              <h2 style={{ fontSize: 15 }}><span className="sr-only">Bước {s.n}: </span>{s.step}</h2>
            </div>
            <div style={{ fontSize: 14.5, fontWeight: 600, color: "var(--accent-dark)" }}>{s.model}</div>
            <div className="small muted">{s.detail}</div>
            <div className="inline" style={{ marginTop: "auto", paddingTop: 6 }}>
              <span className={`tag ${STATUS[s.status].cls}`}>{STATUS[s.status].label}</span>
              {s.metric && <span className="small tnum" style={{ fontWeight: 600 }}>{s.metric}</span>}
            </div>
          </li>
        ))}
      </ol>

      <section aria-labelledby="h-emb" className="card pad-sm rise" style={delay(.15)}>
        <h2 id="h-emb" style={{ fontSize: 17 }}>1. Embedding: so sánh {EMBEDDINGS.length} mô hình</h2>
        <p className="hint" style={{ marginBottom: 12, maxWidth: "90ch" }}>
          Tập đo 644 cặp bài + 193 cặp khó, không dùng khi huấn luyện. <b>AUC 3&gt;2</b>: phân biệt “cùng sự kiện” với “cùng câu
          chuyện nhưng khác sự kiện”. <b>AP</b>: tìm đúng các cặp cùng sự kiện. Cao hơn là tốt hơn.
        </p>
        <div className="table-wrap" tabIndex={0} aria-label="Bảng so sánh mô hình embedding (cuộn ngang được)">
          <table style={{ minWidth: 860 }}>
            <thead>
              <tr>
                <th scope="col">Mô hình</th><th scope="col" style={{ width: 230 }}>AUC 3&gt;2</th>
                <th scope="col" className="num">AUC 2&gt;1</th><th scope="col" style={{ width: 230 }}>AP</th>
                <th scope="col" className="num">AUC 3&gt;2 khó</th><th scope="col" className="num">AP khó</th>
              </tr>
            </thead>
            <tbody>
              {EMBEDDINGS.map((m) => (
                <tr key={m.name} style={m.used ? { background: "var(--soft)" } : undefined}>
                  <th scope="row" style={{ background: "none", color: "var(--text)", fontSize: 14 }}>
                    <div style={{ fontWeight: 600 }}>{m.name}</div><div className="small muted" style={{ fontWeight: 400 }}>{m.note}</div>
                  </th>
                  <td><MiniBar v={m.auc32} /></td>
                  <td className="num">{f3(m.auc21)}</td>
                  <td><MiniBar v={m.ap} /></td>
                  <td className="num">{f3(m.hardAuc)}</td>
                  <td className="num">{f3(m.hardAp)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="small" style={{ marginTop: 10, color: "var(--body-2)", maxWidth: "95ch" }}>{EMB_NOTE}</p>
      </section>

      <div className="grid-2">
        <section aria-labelledby="h-clu" className="card pad-sm rise" style={delay(.2)}>
          <h2 id="h-clu" style={{ fontSize: 17 }}>2. Gom cụm: B-Cubed F1</h2>
          <p className="hint" style={{ marginBottom: 12 }}>Tập vàng ngày 15/09 (ngưỡng chọn trên 14/09). Trục bắt đầu từ {fmtDec(CLUSTERING_AXIS_FROM, 2)}.</p>
          <Bars rows={CLUSTERING} from={CLUSTERING_AXIS_FROM} />
          <p className="small" style={{ marginTop: 12, color: "var(--body-2)" }}>{CLUSTERING_NOTE}</p>
        </section>
        <section aria-labelledby="h-name" className="card pad-sm rise" style={delay(.25)}>
          <h2 id="h-name" style={{ fontSize: 17 }}>3. Đặt tên: ROUGE-L</h2>
          <p className="hint" style={{ marginBottom: 12 }}>320 sự kiện tập dev, so với tên tham chiếu. Trục bắt đầu từ 0.</p>
          <Bars rows={NAMING} from={0} />
          <p className="small" style={{ marginTop: 12, color: "var(--body-2)" }}>{NAMING_NOTE}</p>
        </section>
      </div>

      <section aria-labelledby="h-caveat" className="info-box rise" style={delay(.3)}>
        <h2 id="h-caveat">Đọc các con số này thế nào</h2>
        <ul>{CAVEATS.map((c) => <li key={c}>{c}</li>)}</ul>
      </section>
    </div>
  );
}

function MiniBar({ v }: { v: number }) {
  return (
    <div className="inline" style={{ flexWrap: "nowrap" }}>
      <span className="heat lg" style={{ flex: "1 1 auto" }} aria-hidden="true">
        <span style={{ width: `${Math.round(v * 100)}%`, background: "var(--accent)" }} />
      </span>
      <span className="tnum" style={{ width: 44, textAlign: "right" }}>{f3(v)}</span>
    </div>
  );
}

function Bars({ rows, from, extra }: { rows: BarRow[]; from: number; extra?: React.ReactNode }) {
  return (
    <ul className="hbars ci">
      {rows.map((r) => (
        <li key={r.name}>
          <span style={{ fontWeight: r.used ? 700 : 400 }}>{r.name}</span>
          <span className="track" aria-hidden="true">
            <span className={`grow${r.used ? "" : " dim"}`} style={{ width: `${Math.max(1, Math.round(((r.value - from) / (1 - from)) * 100))}%` }} />
          </span>
          <span className="val" style={{ textAlign: "left" }}>{f3(r.value)}{r.ci ? ` ${r.ci}` : ""}</span>
        </li>
      ))}
      {extra}
    </ul>
  );
}
