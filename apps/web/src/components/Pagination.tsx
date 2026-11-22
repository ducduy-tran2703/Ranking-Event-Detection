type Props = { page: number; pageSize: number; total: number; onChange: (page: number) => void };

export function Pagination({ page, pageSize, total, onChange }: Props) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  if (pages <= 1) return null;
  return (
    <nav className="pager" aria-label="Phân trang">
      <button type="button" className="btn-ghost sm" disabled={page <= 1} onClick={() => onChange(page - 1)}>Trang trước</button>
      <span className="tnum" aria-current="page">Trang {page} / {pages}</span>
      <button type="button" className="btn-ghost sm" disabled={page >= pages} onClick={() => onChange(page + 1)}>Trang sau</button>
    </nav>
  );
}
