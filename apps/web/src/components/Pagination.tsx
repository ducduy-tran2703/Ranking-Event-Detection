type Props = { page: number; pageSize: number; total: number; onChange: (page: number) => void };

export function Pagination({ page, pageSize, total, onChange }: Props) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  return (
    <div className="pager">
      <button disabled={page <= 1} onClick={() => onChange(page - 1)}>‹ Trước</button>
      <span>Trang {page} / {pages}</span>
      <button disabled={page >= pages} onClick={() => onChange(page + 1)}>Sau ›</button>
    </div>
  );
}
