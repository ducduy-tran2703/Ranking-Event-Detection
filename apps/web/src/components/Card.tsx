export function Card({ title, hint, actions, children }: {
  title: string; hint?: string; actions?: React.ReactNode; children: React.ReactNode;
}) {
  return (
    <section className="card">
      <div className="card-head">
        <div>
          <h2>{title}</h2>
          {hint && <p className="muted hint">{hint}</p>}
        </div>
        {actions}
      </div>
      {children}
    </section>
  );
}

export function Kpi({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="kpi">
      <div className="value">{value}</div>
      <div className="label">{label}</div>
      {note && <div className="note">{note}</div>}
    </div>
  );
}

/** Nhãn % có màu: ≥ 20% đỏ, ≥ 5% vàng. */
export function Pct({ value }: { value: number }) {
  const cls = value >= 20 ? "bad" : value >= 5 ? "warn" : "";
  return cls ? <span className={`badge ${cls}`}>{value}%</span> : <>{value}%</>;
}
