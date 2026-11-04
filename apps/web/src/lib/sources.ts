// Tên hiển thị, chữ viết tắt và màu ô viết tắt của từng báo (theo bản thiết kế EventDetail.dc.html).
// Báo chưa có trong bảng: dùng mã báo, 2 chữ cái đầu, màu xám.
type SourceMeta = { name: string; ini: string; bg: string; fg: string };

const META: Record<string, SourceMeta> = {
  tuoitre: { name: "Tuổi Trẻ", ini: "TT", bg: "#E0F2FE", fg: "#075985" },
  vietnamnet: { name: "VietnamNet", ini: "VN", bg: "#DBEAFE", fg: "#1E40AF" },
  baochinhphu: { name: "Báo Chính phủ", ini: "CP", bg: "#CCFBF1", fg: "#115E59" },
  thanhnien: { name: "Thanh Niên", ini: "TN", bg: "#E0E7FF", fg: "#3730A3" },
  vnexpress: { name: "VnExpress", ini: "VE", bg: "#F1F5F9", fg: "#334155" },
  nhandan: { name: "Nhân Dân", ini: "ND", bg: "#CFFAFE", fg: "#155E75" },
};

export const DEFAULT_SOURCES = ["tuoitre", "thanhnien", "vietnamnet", "nhandan", "vnexpress", "baochinhphu"];

export function sourceMeta(code: string): SourceMeta {
  return META[code] ?? { name: code, ini: code.slice(0, 2).toUpperCase(), bg: "#EEF2F6", fg: "#334155" };
}

export const sourceName = (code: string) => sourceMeta(code).name;
