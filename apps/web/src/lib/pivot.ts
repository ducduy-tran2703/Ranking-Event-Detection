/**
 * Chuyển dạng "dài" từ API [{bucket, source, n}, ...] sang dạng "rộng" mà biểu đồ cần:
 * [{bucket: "2026-09-01", tuoitre: 12, vnexpress: 8}, ...] — mỗi nguồn là một cột / một đường.
 */
export function pivot<K extends string>(
  rows: ({ source: string; n: number } & Record<K, string | number>)[],
  key: K,
  order?: (string | number)[],
): { data: Record<string, string | number>[]; sources: string[] } {
  const sources = [...new Set(rows.map((r) => r.source))].sort();
  const labels = order ?? [...new Set(rows.map((r) => r[key]))].sort((a, b) => (a < b ? -1 : a > b ? 1 : 0));
  const byLabel = new Map<string | number, Record<string, string | number>>(
    labels.map((l) => [l, Object.fromEntries([[key, l], ...sources.map((s) => [s, 0])])]),
  );
  for (const r of rows) {
    const row = byLabel.get(r[key]);
    if (row) row[r.source] = r.n;
  }
  return { data: [...byLabel.values()], sources };
}
