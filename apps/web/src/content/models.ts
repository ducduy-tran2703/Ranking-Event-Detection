// Nội dung TĨNH của trang "Mô hình" (/du-lieu/mo-hinh). Số liệu chép đúng bản thiết kế đã duyệt
// (data/temp/thiet_ke_web/Models.dc.html, phần renderVals), mỗi nhóm số ghi nguồn đo gốc bên dưới.
// KHÔNG đưa tên sự kiện nào vào file này (đặc biệt cửa sổ 14–15/09 của tập test đặt tên).
// Sửa số → sửa ở nguồn trước, rồi chép lại đây kèm nguồn.

export type Status = "dang-dung" | "chua-danh-gia" | "dang-huan-luyen";

export interface Step { n: number; step: string; model: string; detail: string; status: Status; metric: string }

/** 4 bước pipeline. Nguồn: data/runs/2026-11-03_v2/manifest.json (phiên bản đang phục vụ) + các bảng bên dưới. */
export const STEPS: Step[] = [
  { n: 1, step: "Embedding", model: "bkai fine-tune v1 (seed 44)", detail: "PhoBERT 768 chiều, fine-tune CoSENT trên nhãn yếu 4 mức",
    status: "dang-dung", metric: "AP 0,636" },
  { n: 2, step: "Gom cụm", model: "Agglomerative, average-linkage", detail: "Ngưỡng cosine 0,83, cửa sổ 48 giờ",
    status: "dang-dung", metric: "B-Cubed F1 0,967" },
  { n: 3, step: "Đặt tên", model: "ViT5 v1 (seed 42) + hậu kiểm", detail: "Sinh tên 5–10 từ từ tiêu đề và sapo các bài",
    status: "dang-dung", metric: "ROUGE-L 0,632" },
  { n: 4, step: "Xu hướng", model: "Công thức t2", detail: "Vận tốc đưa tin, mỗi bài giảm một nửa sau 3 giờ",
    status: "chua-danh-gia", metric: "" },
];

export interface EmbRow { name: string; note: string; auc32: number; auc21: number; ap: number; hardAuc: number; hardAp: number; used?: boolean }

/** So sánh 7 mô hình embedding trên tập đo 644 cặp + 193 cặp khó (nhãn 4 mức do Claude gán, 100 cặp người duyệt).
 *  Nguồn: `make compare` → data/temp/compare_models/ (CI bootstrap ghép cặp); bản v2 fine-tune 30/10 trên Kaggle
 *  (data/temp/kaggle_runs/). */
export const EMBEDDINGS: EmbRow[] = [
  { name: "bkai zero-shot", note: "mốc so sánh", auc32: 0.684, auc21: 0.639, ap: 0.426, hardAuc: 0.585, hardAp: 0.456 },
  { name: "bkai fine-tune v1", note: "đang dùng trong hệ thống", auc32: 0.699, auc21: 0.846, ap: 0.636, hardAuc: 0.653, hardAp: 0.465, used: true },
  { name: "bkai v2", note: "fine-tune 30/10", auc32: 0.812, auc21: 0.778, ap: 0.745, hardAuc: 0.712, hardAp: 0.583 },
  { name: "e5 zero-shot", note: "multilingual-e5-base", auc32: 0.719, auc21: 0.625, ap: 0.526, hardAuc: 0.74, hardAp: 0.518 },
  { name: "e5 v2", note: "fine-tune 30/10", auc32: 0.824, auc21: 0.794, ap: 0.775, hardAuc: 0.814, hardAp: 0.723 },
  { name: "TABERT zero-shot", note: "mốc so sánh", auc32: 0.578, auc21: 0.595, ap: 0.364, hardAuc: 0.664, hardAp: 0.302 },
  { name: "TABERT v2", note: "fine-tune 30/10", auc32: 0.858, auc21: 0.705, ap: 0.783, hardAuc: 0.77, hardAp: 0.64 },
];
export const EMB_NOTE =
  "Bản v2 tốt hơn v1 trên cặp bài (bkai v2 so với v1: AUC 3>2 +0,112 [+0,074; +0,154]) nhưng gom cụm trên tập vàng không khác biệt "
  + "có ý nghĩa, nên hệ thống vẫn dùng v1. TABERT dùng giấy phép AGPL-3.0.";

export interface BarRow { name: string; value: number; ci?: string; used?: boolean }

/** B-Cubed F1 gom cụm, tập vàng ngày 15/09 (ngưỡng chọn trên 14/09), CI bootstrap theo cụm vàng.
 *  Nguồn: docs/tong-hop.md mục 10.2 "Chấm gom cụm (21/10/2026)" + data/temp/cluster_eval/. */
export const CLUSTERING: BarRow[] = [
  { name: "Mỗi bài một cụm (mốc)", value: 0.838 },
  { name: "TF-IDF", value: 0.928, ci: "[0,902; 0,951]" },
  { name: "bkai v1 (đang dùng)", value: 0.967, ci: "[0,955; 0,976]", used: true },
  { name: "bkai v2", value: 0.96 },
  { name: "e5 zero-shot", value: 0.955 },
  { name: "e5 v2", value: 0.952 },
];
export const CLUSTERING_NOTE =
  "bkai v1 hơn TF-IDF +0,040 [+0,020; +0,064]. Với các cặp ít trùng chữ, bkai v1 bắt được 87,9% so với 56,3% của TF-IDF.";
export const CLUSTERING_AXIS_FROM = 0.8;

/** ROUGE-L đặt tên, 320 sự kiện tập dev (tên tham chiếu do Claude viết).
 *  Nguồn: notebook huấn luyện ViT5 trên Kaggle (data/temp/kaggle_kernel_vit5_naming/), hậu kiểm: data/temp/kiem_tra_pipeline/BAO_CAO.md. */
export const NAMING: BarRow[] = [
  { name: "Tiêu đề bài đại diện (mốc)", value: 0.517 },
  { name: "ViT5 v1", value: 0.632, ci: "[0,610; 0,655]" },
  { name: "ViT5 v1 + hậu kiểm (đang dùng)", value: 0.622, ci: "[0,599; 0,645]", used: true },
  // Nguồn: README R2 models/naming/bartpho_{large_s44,base_s42}_NguyenDinhHieu/ (05/11/2026), chưa tích hợp vào pipeline.
  { name: "BARTpho-syllable (chưa tích hợp)", value: 0.654, ci: "[0,632; 0,676]" },
  { name: "BARTpho-syllable base", value: 0.631, ci: "[0,609; 0,653]" },
];
export const NAMING_NOTE =
  "Hậu kiểm thay tên mô hình bằng tiêu đề rút gọn ở 2,8% sự kiện (tên không khớp nội dung, lặp, quá dài). Trên 85 tên được chấm lại, "
  + "11,8% [6,5%; 20,3%] sai nghĩa hoặc bịa.";

/** Cách đọc các con số. Nguồn: AGENTS.md mục 4b (nhãn Claude chưa phải nhãn người), README của run v2 (xu hướng chưa đánh giá). */
export const CAVEATS = [
  "Nhãn dùng để đo do Claude gán; 100 cặp bài có người duyệt. Tập vàng gom cụm chưa có nhãn người.",
  "Tập vàng được dựng có dùng bkai v1, nên kết quả gom cụm có thể thiên về v1.",
  "BARTpho-syllable hơn ViT5 +0,022 [+0,001; +0,042] ROUGE-L trên dev (sát ngưỡng ý nghĩa) nhưng chưa được tích hợp vào pipeline.",
  "Điểm xu hướng là công thức, chưa đánh giá được vì chưa có dữ liệu \"Xem nhiều\" của các báo để đối chiếu.",
];
