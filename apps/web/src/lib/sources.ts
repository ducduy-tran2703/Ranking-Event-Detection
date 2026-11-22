// Tên hiển thị, chữ viết tắt và màu nhận diện của từng báo.
// Báo chưa có trong bảng: dùng mã báo, 2 chữ cái đầu, màu xám.
type SourceMeta = { name: string; ini: string; bg: string; fg: string };

const META: Record<string, SourceMeta> = {
  tuoitre: { name: "Tuổi Trẻ", ini: "TT", bg: "#DFE1EA", fg: "#22397A" },
  vietnamnet: { name: "VietnamNet", ini: "VN", bg: "#DCE6DA", fg: "#2F5D3D" },
  baochinhphu: { name: "Báo Chính phủ", ini: "CP", bg: "#D6E3E3", fg: "#2F5A63" },
  thanhnien: { name: "Thanh Niên", ini: "TN", bg: "#ECDFD0", fg: "#7A3B12" },
  vnexpress: { name: "VnExpress", ini: "VE", bg: "#E5DFE9", fg: "#5A3F78" },
  nhandan: { name: "Nhân Dân", ini: "ND", bg: "#EED9D3", fg: "#8C2A22" },
  dantri: { name: "Dân Trí", ini: "DT", bg: "#ECDAE6", fg: "#8A2F6B" },
  qdnd: { name: "Quân đội Nhân dân", ini: "QĐ", bg: "#E3E4CF", fg: "#5F6418" },
};

export const DEFAULT_SOURCES = ["tuoitre", "thanhnien", "vietnamnet", "nhandan", "vnexpress", "baochinhphu"];

export function sourceMeta(code: string): SourceMeta {
  return META[code] ?? { name: code, ini: code.slice(0, 2).toUpperCase(), bg: "#E4DFD3", fg: "#4A4036" };
}

export const sourceName = (code: string) => sourceMeta(code).name;
