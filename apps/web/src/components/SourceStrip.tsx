import { fmtInt } from "../lib/format";
import { sourceMeta, sourceName } from "../lib/sources";

/** Rãnh chia theo báo của một sự kiện: mỗi đoạn dài theo số bài thật của báo đó, màu theo báo. */
export function SourceStrip({ sources, total }: { sources: { source: string; n: number }[]; total: number }) {
  const label = `${fmtInt(total)} bài từ ${sources.length} báo: ${sources.map((s) => `${sourceName(s.source)} ${s.n}`).join(", ")}`;
  return (
    <div className="strip" role="img" aria-label={label} data-testid="source-strip">
      <div className="strip-groove">
        {sources.map((s, i) => (
          <span key={s.source} style={{ flexGrow: s.n, background: sourceMeta(s.source).fg, animationDelay: `${i * 70}ms` }} />
        ))}
      </div>
      <p className="strip-note" aria-hidden="true">{fmtInt(total)} bài từ {sources.length} báo, mỗi đoạn màu là một báo</p>
    </div>
  );
}
