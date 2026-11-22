// Nội dung TĨNH của trang "Kiến trúc hệ thống" (/du-lieu/he-thong) — dùng khi thuyết trình.
// Số liệu đo ngày 10/11/2026 trên máy chạy demo, nguồn ghi cạnh từng nhóm:
//   - đếm dòng / dung lượng bảng: truy vấn Postgres (pg_stat_user_tables, pg_total_relation_size, count(*))
//   - dung lượng thư mục: `du -sh data/*` ở gốc repo
//   - tham số mô hình: đếm từ header *.safetensors + config.json trong data/models/
//   - cấu hình: configs/{clustering,pipeline,rag,sources}.yaml, infra/docker-compose*.yml, infra/modal_models.py
//   - số đo chất lượng: chép từ content/models.ts, docs/handoff/worker.md, README mô hình trên R2
// KHÔNG ghi giá trị biến môi trường (.env), chỉ ghi tên biến.

export const MEASURED_AT = "10/11/2026";

/** Số tổng quan. Nguồn: Postgres 10/11/2026. */
export const KPIS: { label: string; value: string; note: string }[] = [
  { label: "Báo nguồn", value: "8", note: "6 báo có dữ liệu lịch sử + Dân Trí, QĐND cào mới" },
  { label: "Bài báo trong DB", value: "29.714", note: "bảng articles; 28.725 bài lịch sử đến 19/09" },
  { label: "Sự kiện", value: "20.675", note: "4.334 sự kiện có ≥ 2 bài" },
  { label: "Đoạn văn cho hỏi đáp", value: "96.230", note: "chunk RAG, mỗi đoạn ≤ 320 từ" },
  { label: "Mô hình đang chạy", value: "4", note: "2 trên máy chủ (CPU), 2 trên GPU thuê (Modal)" },
  { label: "Dung lượng Postgres", value: "586 MB", note: "34 bảng, migration 001–009" },
];

// ───────────────────────────── Sơ đồ kiến trúc ─────────────────────────────

export type Zone = "ngoai" | "trong" | "dich-vu";
export interface Component {
  name: string;
  zone: Zone;
  kind: "dich-vu" | "luu-tru" | "mo-hinh" | "nguoi";
  where: string;
  detail: string;
  code: string;
}

/** Bảng thành phần (đi kèm sơ đồ). "trong" = chạy trên máy chủ của nhóm; "dich-vu" = dịch vụ bên thứ ba. */
export const COMPONENTS: Component[] = [
  { name: "8 báo điện tử", zone: "ngoai", kind: "nguoi", where: "Internet",
    detail: "Tuổi Trẻ, Thanh Niên, VietnamNet, VnExpress, Nhân Dân, Báo Chính phủ, Dân Trí, QĐND. Đọc qua RSS/sitemap, tôn trọng robots.txt, tối thiểu 2 giây/request mỗi báo.",
    code: "configs/sources.yaml" },
  { name: "Người dùng", zone: "ngoai", kind: "nguoi", where: "Trình duyệt",
    detail: "Xem bảng xu hướng, chi tiết sự kiện, theo dõi/lưu sự kiện, hỏi đáp (cần đăng nhập).", code: "—" },
  { name: "Crawler", zone: "trong", kind: "dich-vu", where: "Máy chủ · cổng 8002",
    detail: "Cào 8 báo mỗi 30 phút (:00, :30 giờ VN), lấy lùi 24 giờ, bỏ bài cũ hơn 7 ngày. Báo nào cào xong mới nạp vào bảng articles.",
    code: "automation/, crawler/harvester_*.py, automation/db_sink.py" },
  { name: "PostgreSQL 18", zone: "trong", kind: "luu-tru", where: "Máy chủ · cổng 5432",
    detail: "Nơi lưu chính khi chạy: bài báo, vector, sự kiện, tên, điểm xu hướng, tài khoản, hội thoại hỏi đáp. Chỉ nghe 127.0.0.1.",
    code: "infra/db/migrations/001–009" },
  { name: "Worker", zone: "trong", kind: "dich-vu", where: "Máy chủ · CPU, 5 phút/vòng",
    detail: "Mỗi vòng: embed bài mới → gom cụm lại (giữ event_id cũ) → đặt tên → tính điểm xu hướng. Ghi một dòng worker_runs mỗi bước. Cần ~2,2 GB RAM.",
    code: "src/eventrank/serving/worker.py" },
  { name: "API FastAPI", zone: "trong", kind: "dich-vu", where: "Máy chủ · cổng 8000",
    detail: "64 endpoint: sự kiện, xu hướng, thống kê, tài khoản, quản trị, hỏi đáp. Tự nạp lại dữ liệu mới sau tối đa 60 giây.",
    code: "apps/api/, src/eventrank/{serving,accounts,rag}/" },
  { name: "Web React", zone: "trong", kind: "dich-vu", where: "Máy chủ · cổng 5173",
    detail: "React 19 + Vite 8 + TypeScript 5.9. Chỉ gọi backend qua /api.", code: "apps/web/" },
  { name: "Qdrant 1.20", zone: "trong", kind: "luu-tru", where: "Máy chủ · Docker · cổng 6333",
    detail: "Cơ sở dữ liệu vector cho hỏi đáp: 96.230 vector 1.024 chiều (collection rag_v1_qwen_text_v1).",
    code: "infra/docker-compose.rag.yml" },
  { name: "Chỉ mục BM25", zone: "trong", kind: "luu-tru", where: "Máy chủ · file",
    detail: "Tìm theo từ khoá cho hỏi đáp, chạy hoàn toàn trên máy (145 MB).", code: "src/eventrank/rag/bm25.py, data/rag/bm25/" },
  { name: "bkai fine-tune v1", zone: "trong", kind: "mo-hinh", where: "Trong worker · CPU",
    detail: "Biến tiêu đề + sapo thành vector 768 chiều để gom cụm.", code: "data/models/bkai_ft_v1_s44" },
  { name: "ViT5 đặt tên v1", zone: "trong", kind: "mo-hinh", where: "Trong worker · CPU",
    detail: "Sinh tên 5–10 từ cho sự kiện ≥ 2 bài.", code: "data/models/vit5-naming-s42_2026-11-03" },
  { name: "Modal (GPU thuê)", zone: "dich-vu", kind: "dich-vu", where: "Đám mây · gọi qua HTTPS + proxy token",
    detail: "Chạy hai mô hình lớn của hỏi đáp. GPU tự tắt sau 120 giây rảnh; câu hỏi đầu tiên sau khi tắt chờ 6–15 phút để khởi động.",
    code: "infra/modal_models.py" },
  { name: "Qwen3-Embedding 0.6B", zone: "dich-vu", kind: "mo-hinh", where: "Modal · GPU L4",
    detail: "Vector hoá câu hỏi (và trước đó cả 96.230 đoạn văn).", code: "configs/rag.yaml › models.embedding" },
  { name: "Gemma 4 12B (4-bit)", zone: "dich-vu", kind: "mo-hinh", where: "Modal · GPU L4/A10 · vLLM 0.33",
    detail: "Viết câu trả lời tiếng Việt có trích dẫn từ tối đa 8 đoạn văn.", code: "configs/rag.yaml › models.llm" },
  { name: "Cloudflare R2", zone: "dich-vu", kind: "luu-tru", where: "Đám mây · bucket vietnam-news-datalake",
    detail: "Kho chung của nhóm: Silver, NER Gold, nhãn, tập vàng, mô hình, bản dump DB. Hệ thống KHÔNG đọc R2 khi chạy; tải về máy bằng tay.",
    code: "docs/tong-hop.md mục 5.2" },
  { name: "Kaggle (GPU T4)", zone: "dich-vu", kind: "dich-vu", where: "Đám mây · chỉ lúc huấn luyện",
    detail: "Fine-tune embedding và mô hình đặt tên (~15 phút/lần, 3 seed). Mô hình gốc tải từ HuggingFace.",
    code: "training/*.ipynb" },
];

// ───────────────────────────── Hành trình một bài báo ─────────────────────────────

export interface FlowStep { n: number; title: string; body: string; model?: string; out: string }

/** Nguồn: docs/handoff/worker.md, configs/pipeline.yaml, src/eventrank/rag/. Số đo vòng worker 10/11/2026 (852 bài). */
export const FLOW: FlowStep[] = [
  { n: 1, title: "Cào", body: "Crawler đọc RSS/sitemap, tải trang, tách tiêu đề, sapo, nội dung, giờ đăng. Khoá bài = sha256(url).",
    out: "data/jobs/<job>/clean_silver/<báo>.jsonl → bảng articles" },
  { n: 2, title: "Embedding", body: "Tiêu đề + \". \" + sapo, chuẩn hoá NFC, tách từ pyvi, rồi mã hoá thành vector.",
    model: "bkai fine-tune v1", out: "article_embeddings (vector 768 chiều, bytea)" },
  { n: 3, title: "Gom cụm", body: "Agglomerative average-linkage trong cửa sổ 48 giờ, ngưỡng cosine 0,83. Đối chiếu cụm mới với sự kiện cũ theo Jaccard để giữ event_id.",
    out: "events, event_articles, event_assignment_log" },
  { n: 4, title: "Đặt tên", body: "Cụm ≥ 2 bài: ViT5 sinh tên từ ≤ 12 tiêu đề + 3 sapo; tên lỗi hoặc > 22 âm tiết thì thay bằng tiêu đề bài đại diện. Cụm 1 bài: dùng tiêu đề. Đặt lại khi số bài tăng 1,5 lần.",
    model: "ViT5 đặt tên v1", out: "event_names" },
  { n: 5, title: "Xu hướng", body: "Mỗi giờ tính điểm nóng: số báo đưa tin × log(1 + tốc độ đưa tin / mức nền theo giờ). Mỗi bài giảm nửa sức nặng sau 3 giờ.",
    out: "trend_scores, trend_baselines" },
  { n: 6, title: "Hiển thị", body: "API nạp sự kiện + điểm vào RAM, web hiện bảng xu hướng theo giờ, chi tiết sự kiện, các báo đưa tin.",
    out: "/api/trending, /api/events" },
  { n: 7, title: "Hỏi đáp (RAG)", body: "Câu hỏi → tìm song song BM25 (từ khoá) và Qdrant (ngữ nghĩa) → trộn bằng RRF → chọn ≤ 8 đoạn (≤ 2 đoạn/bài, ≤ 3 đoạn/báo) → Gemma viết câu trả lời có trích dẫn.",
    model: "Qwen3-Embedding + Gemma 4 12B", out: "rag_conversations, rag_messages" },
];

// ───────────────────────────── Mô hình ─────────────────────────────

export type ModelState = "dang-dung" | "du-phong" | "moc" | "huan-luyen";
export interface ModelRow {
  name: string; role: string; base: string; params: string; shape: string;
  runs: string; stored: string; metric: string; state: ModelState;
}

/** Tham số: đếm phần tử trong *.safetensors (data/models/…), config.json; Qwen/Gemma theo configs/rag.yaml.
 *  Số đo: content/models.ts (embedding, gom cụm, ViT5), README R2 models/naming/bartpho_* (BARTpho). */
export const MODELS: ModelRow[] = [
  { name: "bkai fine-tune v1 (seed 44)", role: "Embedding bài báo để gom cụm",
    base: "bkai-foundation-models/vietnamese-bi-encoder (PhoBERT-base, RoBERTa)", params: "135,0 triệu",
    shape: "768 chiều · 12 lớp · tối đa 256 token · mean pooling", runs: "Worker, CPU",
    stored: "data/models/bkai_ft_v1_s44 (518 MB) · R2 models/embedding/bkai_v1_s44_NguyenDinhHieu/",
    metric: "Gom cụm B-Cubed F1 0,967 [0,955; 0,976], TF-IDF 0,928", state: "dang-dung" },
  { name: "ViT5 đặt tên v1 (seed 42)", role: "Sinh tên sự kiện 5–10 từ",
    base: "VietAI/vit5-base (T5 encoder–decoder)", params: "226,0 triệu",
    shape: "d_model 768 · 12 lớp · vào ≤ 512 token · ra ≤ 48 token · beam 4", runs: "Worker, CPU (~2,1 s/cụm)",
    stored: "data/models/vit5-naming-s42_2026-11-03 (867 MB) · R2 models/naming/vit5_v1_s42_NguyenDinhHieu/",
    metric: "ROUGE-L dev 0,622 [0,599; 0,645] sau hậu kiểm, tiêu đề đại diện 0,517", state: "dang-dung" },
  { name: "Qwen3-Embedding-0.6B", role: "Vector hoá câu hỏi và đoạn văn cho hỏi đáp",
    base: "Qwen/Qwen3-Embedding-0.6B (revision 97b0c61)", params: "0,6 tỷ",
    shape: "1.024 chiều · tối đa 2.048 token · batch 8", runs: "Modal, GPU L4",
    stored: "Trọng số: Modal Volume eventrank-rag-model-cache · vector: Qdrant", metric: "Chưa có bộ đo RAG", state: "dang-dung" },
  { name: "Gemma 4 12B-it (QAT w4a16)", role: "Viết câu trả lời có trích dẫn",
    base: "google/gemma-4-12B-it-qat-w4a16-ct (revision 1d2c2d7)", params: "12 tỷ (trọng số 4-bit)",
    shape: "ngữ cảnh 8.192 token · trả lời ≤ 1.024 token", runs: "Modal, GPU L4/A10, vLLM",
    stored: "Modal Volume eventrank-rag-model-cache · tokenizer: data/rag/tokenizers", metric: "Chưa có bộ đo RAG", state: "dang-dung" },
  { name: "bkai v2 (seed 42)", role: "Embedding, phương án dự phòng (ngưỡng 0,85)",
    base: "bkai vietnamese-bi-encoder", params: "135,0 triệu", shape: "768 chiều", runs: "Không chạy",
    stored: "data/models/bkai-v4-cosent-s42_2026-10-30 · R2 models/embedding/bkai_v2_s42_NguyenDinhHieu/",
    metric: "Gom cụm F1 0,960 (không khác v1 có ý nghĩa)", state: "du-phong" },
  { name: "e5 v2 (seed 43)", role: "Embedding, mô hình fine-tune thứ hai để so",
    base: "intfloat/multilingual-e5-base (XLM-RoBERTa)", params: "278,0 triệu", shape: "768 chiều · tối đa 512 token", runs: "Không chạy",
    stored: "data/models/e5-v4-cosent-s43_2026-10-30 · R2 models/embedding/e5_v2_s43_NguyenDinhHieu/",
    metric: "Gom cụm F1 0,952; cặp khó AUC 0,814 (tốt nhất)", state: "du-phong" },
  { name: "TABERT v2 (seed 44)", role: "Embedding, mô hình so sánh",
    base: "Tuibingu03/TABERT_SimCSE (PhoBERT-base-v2 + SimCSE)", params: "135,0 triệu", shape: "768 chiều · [CLS] pooling", runs: "Không chạy",
    stored: "data/models/tabert-v4-cosent-s44_2026-11-02 · R2 models/embedding/tabert_v2_s44_NguyenDinhHieu/",
    metric: "AUC 3>2 0,858 (cao nhất), giấy phép AGPL-3.0", state: "du-phong" },
  { name: "BARTpho-syllable đặt tên (seed 44)", role: "Đặt tên, ứng viên thay ViT5",
    base: "vinai/bartpho-syllable (mBART)", params: "395,9 triệu", shape: "d_model 1.024 · vào ≤ 1.024 token", runs: "Không chạy (chưa tích hợp)",
    stored: "data/models/bartpho-naming-s44_2026-11-04 (1,5 GB) · R2 models/naming/bartpho_large_s44_NguyenDinhHieu/",
    metric: "ROUGE-L dev 0,654 [0,632; 0,676], hơn ViT5 +0,022 [+0,001; +0,042]", state: "du-phong" },
  { name: "MiniLM-L12 đa ngôn ngữ", role: "Tín hiệu ngữ nghĩa khi sinh nhãn yếu",
    base: "paraphrase-multilingual-MiniLM-L12-v2 (bản ONNX của Xenova)", params: "~118 triệu", shape: "384 chiều", runs: "Chỉ lúc dựng dữ liệu",
    stored: "data/weak_labels/models/ (130 MB)", metric: "—", state: "huan-luyen" },
  { name: "bkai / e5 / TABERT zero-shot, TF-IDF", role: "Mốc so sánh (chưa fine-tune)",
    base: "Mô hình gốc từ HuggingFace; TF-IDF của scikit-learn", params: "135 / 278 / 135 triệu", shape: "768 chiều", runs: "Chỉ lúc đánh giá",
    stored: "data/models/bkai_zs, tabert_zs · HuggingFace cache", metric: "Gom cụm F1: bkai zs 0,950, e5 zs 0,955, TF-IDF 0,928", state: "moc" },
];

/** Thành phần tính toán KHÔNG phải mô hình học máy (không có trọng số, không huấn luyện). */
export const NON_MODELS: { name: string; what: string }[] = [
  { name: "Agglomerative average-linkage", what: "Thuật toán gom cụm. Ngưỡng 0,83 là siêu tham số chọn bằng thử 91 giá trị trên ngày 14/09." },
  { name: "Công thức xu hướng t2", what: "Điểm nóng theo giờ, chưa đánh giá được vì chưa có dữ liệu \"Xem nhiều\" của các báo." },
  { name: "BM25", what: "Xếp hạng theo từ khoá cho hỏi đáp." },
  { name: "RRF (Reciprocal Rank Fusion)", what: "Trộn hai danh sách BM25 và Qdrant, k = 60." },
  { name: "Hậu kiểm tên", what: "Luật thay tên mô hình bằng tiêu đề rút gọn khi tên quá dài, lặp, hoặc không khớp nội dung (2,8% sự kiện)." },
];

// ───────────────────────────── Bộ dữ liệu ─────────────────────────────

export interface DatasetRow { name: string; content: string; size: string; use: string; local: string; r2: string }

/** Nguồn: docs/tong-hop.md mục 5.2, 5.4, 10.2; memory/nhật ký dự án; `du -sh`. */
export const DATASETS: DatasetRow[] = [
  { name: "Silver (bài báo sạch)", content: "6 báo, 28.746 bài, 2008 → 19/09/2026; 76% nằm trong 01/08–19/09", size: "141 MB",
    use: "Nguồn của mọi bước ML; đã nạp vào bảng articles", local: "data/lake/silver/", r2: "silver/<báo>/*.jsonl" },
  { name: "Gold NER", content: "28.746 bài, 940.474 thực thể, 6 nhãn PER · ORG · LOC · EVENT · DOC · PRODUCT (do thành viên khác làm)", size: "93 MB",
    use: "Nhãn yếu, chia đoạn RAG (bảng article_ner)", local: "data/lake/gold/", r2: "gold/gold_data.jsonl" },
  { name: "Bài cào mới", content: "Bronze (HTML gốc), Silver, clean_silver theo báo và theo lượt cào, từ 01/11/2026", size: "~1,4 GB",
    use: "Nạp vào articles cho worker", local: "data/{bronze,silver,clean_silver}/, data/jobs/", r2: "Không tải lên" },
  { name: "Nhãn yếu v1, v3", content: "Cặp bài cùng/khác sự kiện từ luật + thực thể + MiniLM (v1: 327.230 cặp)", size: "~480 MB",
    use: "Thế hệ nhãn đầu, đã thay bằng v4", local: "data/weak_labels/v1, v3", r2: "weak_label_NguyenDinhHieu/ (gốc), …/v3/" },
  { name: "Cặp 4 mức v4 (bản 3)", content: "Train 25.006 · test 644 · test khó 193 cặp; mức 3 cùng sự kiện / 2 cùng câu chuyện / 1 cùng chủ đề / 0 khác. Claude gán theo quy tắc, 100 cặp người duyệt", size: "47 MB",
    use: "Fine-tune và đo embedding", local: "data/datasets/cap_su_kien_v4.csv", r2: "datasets_NguyenDinhHieu/v2/, weak_label_NguyenDinhHieu/v4/final_v3/" },
  { name: "Tập vàng gom cụm 14–15/09", content: "1.496 bài → 1.003 cụm (176 cụm nhiều bài); chọn ngưỡng trên 14/09, báo cáo trên 15/09. Claude đề xuất, chưa có người duyệt", size: "27 MB",
    use: "Chấm B-Cubed cho gom cụm", local: "data/gold_clusters/v1/", r2: "gold_clusters_NguyenDinhHieu/v1/, datasets_NguyenDinhHieu/v2/cum_su_kien_14-15_09.csv" },
  { name: "Dữ liệu đặt tên v1", content: "Train 2.751 · dev 320 cụm, tên tham chiếu do LLM viết, 3 vòng rà", size: "25 MB",
    use: "Fine-tune ViT5, BARTpho", local: "data/naming/v1/", r2: "Chưa có (Kaggle dataset riêng tư pbl-naming-v1)" },
  { name: "Kết quả chạy pipeline", content: "Sự kiện, tên, điểm xu hướng của các lần chạy theo lô (run 2026-11-03_v2)", size: "166 MB",
    use: "Nạp vào DB lần đầu (db_import)", local: "data/runs/, data/events/", r2: "events_NguyenDinhHieu/v1/, v2/" },
  { name: "Kho đoạn văn RAG", content: "96.230 đoạn từ 28.725 bài (≤ 320 từ, chồng 48 từ), chỉ đến 19/09/2026", size: "181 MB + 145 MB + 831 MB",
    use: "Hỏi đáp", local: "Postgres rag_chunks · data/rag/bm25/ · data/rag/qdrant/", r2: "rag_NguyenDinhHieu/ (bàn giao)" },
  { name: "Bản dump Postgres", content: "pg_dump -Fc ngày 04/11: bài + sự kiện + điểm + vector", size: "147 MB",
    use: "Cài đặt máy mới, sao lưu", local: "data/temp/db_dump/", r2: "db_NguyenDinhHieu/v1/" },
];

// ───────────────────────────── Lưu trữ khi chạy ─────────────────────────────

export interface TableGroup { migration: string; title: string; tables: { name: string; rows?: string; size?: string; what: string }[] }

/** Nguồn: infra/db/migrations/*.sql + Postgres 10/11/2026 (count(*), pg_total_relation_size). */
export const DB_GROUPS: TableGroup[] = [
  { migration: "001", title: "Thu thập", tables: [
    { name: "articles", rows: "29.714", size: "100 MB", what: "bài báo: tiêu đề, sapo, nội dung, giờ đăng, báo, chuyên mục" },
    { name: "sources", rows: "8", what: "danh sách báo, nạp từ configs/sources.yaml" },
    { name: "crawl_runs, app_clock", what: "lịch sử lượt cào, đồng hồ (giả lập khi phát lại)" },
  ] },
  { migration: "002", title: "Sự kiện", tables: [
    { name: "article_embeddings", rows: "29.684", size: "130 MB", what: "vector bkai 768 chiều, theo model_version" },
    { name: "events", rows: "20.675", size: "14 MB", what: "sự kiện, bài đại diện, trạng thái open/closed/merged" },
    { name: "event_articles", size: "10 MB", what: "bài nào thuộc sự kiện nào" },
    { name: "event_names", rows: "20.690", size: "6,7 MB", what: "tên theo từng phiên bản, nguồn tên (mô hình/tiêu đề)" },
    { name: "trend_scores, trend_baselines", rows: "18.506", size: "4,7 MB", what: "điểm nóng theo giờ, mức nền theo giờ trong ngày" },
    { name: "event_assignment_log, worker_runs", size: "10 MB", what: "lịch sử bài đổi sự kiện, nhật ký từng vòng worker" },
  ] },
  { migration: "003–006", title: "Tài khoản & quản trị", tables: [
    { name: "users, user_sessions, auth_tokens, login_attempts", rows: "7 người dùng", what: "đăng nhập, mật khẩu Argon2id, khoá khi sai nhiều lần" },
    { name: "event_bookmarks, event_follows, topic_subscriptions, user_settings", what: "lưu, theo dõi sự kiện, đăng ký chủ đề" },
    { name: "notifications, email_outbox", what: "thông báo, thư chờ gửi" },
    { name: "feedback_reports, audit_logs, api_tokens", what: "báo sai, nhật ký quản trị, khoá API" },
  ] },
  { migration: "007–009", title: "Hỏi đáp", tables: [
    { name: "article_ner", rows: "28.725", size: "102 MB", what: "thực thể của từng bài (từ Gold NER)" },
    { name: "rag_chunks", rows: "96.230", size: "181 MB", what: "đoạn văn đã chia để tìm kiếm" },
    { name: "rag_index_status", size: "11 MB", what: "đoạn nào đã có trong BM25, Qdrant" },
    { name: "rag_conversations, rag_messages", what: "hội thoại, câu hỏi, trạng thái, trích dẫn" },
  ] },
];

/** Nguồn: `du -sh data/*` ngày 10/11/2026. Thư mục data/ không đưa lên git. */
export const DISK: { path: string; size: string; what: string }[] = [
  { path: "data/models/", size: "11 GB", what: "15 mô hình; hệ thống chỉ cần 2 thư mục (1,4 GB)" },
  { path: "data/rag/", size: "1,2 GB", what: "BM25, bản snapshot Qdrant, tokenizer Gemma" },
  { path: "data/bronze/", size: "1,2 GB", what: "HTML gốc của bài cào mới" },
  { path: "data/weak_labels/", size: "763 MB", what: "nhãn yếu v1–v4" },
  { path: "data/lake/", size: "230 MB", what: "Silver + Gold tải từ R2" },
  { path: "data/events/, data/runs/", size: "166 MB", what: "kết quả gom cụm, pipeline theo lô" },
  { path: "data/jobs/", size: "93 MB", what: "bản xuất mỗi lượt cào" },
  { path: "Docker volume qdrant_data", size: "~870 MB", what: "dữ liệu Qdrant đang chạy" },
];

// ───────────────────────────── Thông số cấu hình ─────────────────────────────

export interface ParamGroup { title: string; file: string; rows: [string, string][] }

/** Chép từ các file cấu hình (không chứa bí mật). */
export const PARAMS: ParamGroup[] = [
  { title: "Gom cụm", file: "configs/clustering.yaml", rows: [
    ["Mô hình", "bkai_ft_v1_s44"], ["Tiền xử lý", "NFC + tách từ pyvi"], ["Thuật toán", "agglo (average-linkage)"],
    ["Ngưỡng cosine", "0,83"], ["Cửa sổ thời gian", "48 giờ"], ["Phiên bản", "algo_version v1"],
  ] },
  { title: "Đặt tên", file: "configs/pipeline.yaml › naming", rows: [
    ["Mô hình", "vit5_v1_s42"], ["Đầu vào", "≤ 12 tiêu đề + ≤ 3 sapo, ≤ 512 token"], ["Sinh", "beam 4, ≤ 48 token, không lặp 3-gram"],
    ["Độ dài tối đa", "22 âm tiết"], ["Đặt lại tên", "khi số bài ≥ 1,5 lần"],
  ] },
  { title: "Xu hướng", file: "configs/pipeline.yaml › trending", rows: [
    ["Công thức", "t2: n_hd^α · log(1 + Σ 2^(−Δt/H) / b(t))"], ["Nửa đời H", "3 giờ"], ["α", "1,0"],
    ["Điều kiện xếp hạng", "≥ 2 bài"], ["Báo chỉ đăng lại", "trọng số 0,5"], ["Bước", "1 giờ, giữ top 20"],
  ] },
  { title: "Worker", file: "configs/pipeline.yaml › worker", rows: [
    ["Chu kỳ", "300 giây"], ["Bài quá cũ", "> 7 ngày không gán"], ["Khoá sự kiện lớn", "không (đo: khoá làm F1 giảm)"],
    ["Tính lại", "6 mốc giờ gần nhất"], ["Đóng sự kiện", "48 giờ không có bài mới"], ["RAM cần", "~2,2 GB (852 bài, 240 s)"],
  ] },
  { title: "Hỏi đáp (RAG)", file: "configs/rag.yaml", rows: [
    ["Chia đoạn", "320 từ, chồng 48"], ["Mỗi nhánh tìm", "30 kết quả"], ["Trộn", "RRF k = 60"],
    ["Ngữ cảnh", "≤ 8 đoạn, ≤ 2/bài, ≤ 3/báo"], ["GPU tắt sau", "120 giây rảnh"], ["Giới hạn", "RAG_DAILY_LIMIT câu/ngày (admin không giới hạn)"],
  ] },
  { title: "Crawler", file: "automation/config.py, .env", rows: [
    ["Lịch", "30 phút/lần (:00, :30)"], ["Lấy lùi", "24 giờ"], ["Bỏ bài", "cũ hơn 7 ngày"],
    ["Lịch sự", "≥ 2 giây/request mỗi báo, theo robots.txt"], ["Định danh", "CRAWLER_USER_AGENT (tên bot + email liên hệ)"],
  ] },
];

/** Tên biến môi trường cần có (KHÔNG ghi giá trị). Nguồn: .env.example, docs/huong-dan-chay.md. */
export const ENV_VARS: { name: string; what: string }[] = [
  { name: "DATABASE_URL", what: "chuỗi kết nối Postgres" },
  { name: "EVENTS_BACKEND=db", what: "API đọc sự kiện từ Postgres (thay vì CSV)" },
  { name: "CRAWLER_USER_AGENT", what: "định danh bot khi cào" },
  { name: "RAG_EMBEDDING_URL, RAG_LLM_URL", what: "địa chỉ hai dịch vụ mô hình trên Modal" },
  { name: "MODAL_PROXY_TOKEN_ID, MODAL_PROXY_TOKEN_SECRET", what: "khoá gọi Modal" },
  { name: "R2_* (chỉ máy dựng dữ liệu)", what: "khoá đọc kho R2; hệ thống chạy không cần" },
];

// ───────────────────────────── Công nghệ & huấn luyện ─────────────────────────────

export const STACK: { layer: string; items: string }[] = [
  { layer: "Giao diện", items: "React 19 · React Router 8 · TanStack Query 5 · Vite 8 · TypeScript 5.9" },
  { layer: "Backend", items: "Python 3.12 · FastAPI · Uvicorn · psycopg 3 + pool · Argon2id" },
  { layer: "Học máy", items: "PyTorch (CPU) · sentence-transformers · transformers 5 · pyvi · scikit-learn" },
  { layer: "Lưu trữ", items: "PostgreSQL 18 · Qdrant 1.20 (Docker) · file JSONL/CSV · Cloudflare R2" },
  { layer: "GPU thuê", items: "Modal (L4, A10) · vLLM 0.33 · Kaggle T4 khi huấn luyện" },
  { layer: "Vận hành", items: "uv · Makefile (make up / down / status) · Docker Desktop trên WSL" },
];

export const TRAINING: string[] = [
  "Huấn luyện ở NGOÀI hệ thống: notebook trong training/ chạy trên Kaggle (GPU T4), ~15 phút một lần, 3 seed (42, 43, 44), chọn seed theo MRR trên tập dev.",
  "Embedding: hàm mất mát CoSENT trên cặp 4 mức (điểm 1,0 / 0,6 / 0,3 / 0). Đặt tên: seq2seq, chọn epoch theo ROUGE-L dev.",
  "Mô hình xong được tải về data/models/ bằng training/import_kaggle_run.py, rồi đưa lên R2 models/{embedding,naming}/.",
  "Đổi mô hình embedding thì phải chọn lại ngưỡng trên 14/09 và tăng algo_version: bảng sự kiện mới, không ghi đè.",
];

export const LIMITS: string[] = [
  "Nhãn đo embedding và tập vàng gom cụm do Claude gán; chỉ 100 cặp có người duyệt. Tập vàng được dựng có dùng bkai v1 nên có thể thiên về v1.",
  "Điểm xu hướng là công thức, chưa đánh giá vì chưa có dữ liệu \"Xem nhiều\" của các báo.",
  "Kho hỏi đáp chỉ có bài đến 19/09/2026; bài cào mới chưa được chia đoạn và đưa vào RAG.",
  "Câu hỏi đầu tiên sau khi GPU nghỉ chờ 6–15 phút. Trên máy 7,6 GB RAM, Qdrant có thể quá hạn khi bật đủ API + web + worker.",
  "Hệ thống chạy trên một máy (WSL), chưa triển khai công khai.",
];
