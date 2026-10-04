# Bàn giao: module nhãn yếu (`src/eventrank/weak_labels/`)

> Viết cho người hoặc AI agent nhận tiếp module. Đọc file này trước. Lịch sử chi tiết (v1 → v3, mọi số đo, mọi lỗi đã
> gặp) ở [docs/nhan-yeu-chi-tiet.md](../nhan-yeu-chi-tiet.md). Định nghĩa "sự kiện" đã chốt ở
> [docs/dinh-nghia-su-kien.md](../dinh-nghia-su-kien.md).
> Cập nhật: 04/10/2026 · Người làm: Nguyễn Đình Hiếu (cùng Claude Code).

## 1. Module này làm gì

Sinh dữ liệu huấn luyện cho **mô hình embedding**: các cặp / bộ ba bài báo được gán nhãn **tự động** "cùng sự kiện" hay
"khác sự kiện". Không có nhãn người cho hàng chục nghìn cặp, nên dùng **giám sát yếu**: nhiều hàm gán nhãn (LF) bỏ phiếu,
một label model gộp phiếu thành xác suất `p`, rồi hiệu chỉnh `p` bằng một tập nhỏ có nhãn.

```
gold (NER cả bài) + silver (văn bản) ──► chuẩn hoá thực thể ──► sinh cặp ứng viên ──► đặc trưng
      ──► 8 LF bỏ phiếu ──► label model (Dawid–Skene/EM) ──► chặn + phủ quyết ──► hiệu chỉnh isotonic ──► p
      ──► chọn bộ ba (anchor, positive, negative khó) ──► train_triplets.jsonl
```

**Mô hình embedding chỉ đọc `tiêu đề + ". " + sapo`.** Thực thể và điểm số chỉ dùng để *quyết định nhãn*, không đưa vào mô hình.

## 2. Trạng thái

| Phiên bản | Precision cặp dương | Recall | Bộ ba | Ghi chú |
|---|---|---|---|---|
| v1 | 0,81 | 0,57 | 10.005 | đã lên R2 `weak_label_NguyenDinhHieu/`; negative khó **sai ≥ 29%**, không nên dùng |
| v2 | 0,93 | 0,20 | 4.051 | sạch nhưng recall thấp |
| **v3 (hiện tại)** | **0,93** [0,85; 0,98] | **0,28** [0,22; 0,37] | **5.381** | thêm tín hiệu ngữ nghĩa (MiniLM) |
| v3 mở rộng (p ≥ 0,6) | 0,83 | 0,43 | 7.596 | phần thêm vào chỉ đúng 0,69 → chỉ dùng làm thí nghiệm |

Mọi số đo: **Claude gán mù** trên mẫu holdout độc lập (`v2/audit_labeled_llm.csv`, 400 cặp), precision/recall **có trọng
số theo tầng** (`evaluate.py`), CI 95% bootstrap. Negative khó của v3: sai 2%.

**Dùng để train:** `data/weak_labels/v3/train_triplets.jsonl`.

## 3. Bản đồ mã

| File | Vai trò | Hàm chính |
|---|---|---|
| `entities.py` | chuẩn hoá thực thể, tính độ nổi bật theo vùng (tiêu đề 3 · sapo 2 · đoạn đầu 1,2 · thân 0,6) | `EntityNormalizer`, `article_entities`, `zone_bounds` |
| `corpus.py` | join gold + silver, IDF, đánh dấu bài đăng lại | `load_corpus`, `Article.head_text` |
| `pairs.py` | sinh ứng viên (thực thể, TF-IDF, ngữ nghĩa, ngẫu nhiên), đặc trưng cặp | `entity_candidates`, `dense_candidates`, `pair_features`, `title_dates`, `title_conflicts` |
| `lfs.py` | 8 LF, nhóm bằng chứng, phủ quyết | `LFS`, `FAMILY`, `positive_families`, `only_semantic`, `veto_mask` |
| `label_model.py` | Dawid–Skene nhị phân bằng EM; prior cố định; chặn cặp không có phiếu dương | `LabelModel` |
| `dense.py` | tải mô hình ONNX (nối tiếp khi đứt mạng, kiểm SHA-256), nhúng văn bản | `download_model`, `OnnxEncoder`, `load_dense` |
| `build.py` | **điểm vào chính**: chạy toàn bộ, ghi file | `main`, `gate`, `finalize`, `Calibrator`, `select_training`, `content_negative` |
| `evaluate.py` | precision/recall có trọng số theo tầng (Horvitz–Thompson) | `weighted_pr` |
| `agreement.py` | Cohen's κ giữa nhãn người và nhãn LLM | `compare` |
| `configs/entity_aliases.yaml` | alias thực thể viết tay | – |
| `tests/weak_labels/` | 45+ test; mọi luật đều có test kèm bằng chứng | – |

## 4. Chạy

```bash
# Dữ liệu đầu vào (đọc R2, cần khoá trong .env) → data/lake/{gold,silver}/  (xem skill data-lake)
make embed          # MiniLM ONNX int8 (~135 MB lần đầu), nhúng ~9 phút CPU → data/weak_labels/cache/*.npz
make weak-labels    # ~2,5 phút → data/weak_labels/v3/
uv run --group embed python -m eventrank.weak_labels.evaluate \
    --system v3=data/weak_labels/v3/pairs.jsonl          # đo lại trên mẫu audit v2
uv run --group embed pytest tests/weak_labels -q
```

Tham số quan trọng (`python -m eventrank.weak_labels.build --help`): `--pos-threshold 0.80`, `--ext-threshold 0.60`,
`--prior 0.10`, `--dense-pos 0.80 --dense-neg 0.30` (**phụ thuộc mô hình embedding**), `--neg-max-dense 0.55`,
`--holdout-start 2026-09-13`, `--calibration`, `--force-pairs`.

## 5. Dữ liệu nằm ở đâu

`data/` **không được commit** (`.gitignore`). Trên máy người làm hiện có:

| Đường dẫn | Là gì | Có trên R2? |
|---|---|---|
| `data/weak_labels/v1/audit_labeled_llm_ids.csv` | **tập chỉnh**: 399 cặp, nhãn Claude | **không** |
| `data/weak_labels/v1/human_label_100.csv` | 100 cặp chờ **người** gán (đo κ) | **không** |
| `data/weak_labels/v2/audit_labeled_llm.csv` + `audit_ids.csv` | **tập đo**: 400 cặp holdout, nhãn Claude | **không** |
| `data/weak_labels/v3/check_*.csv`, `v2/negative_check_llm.csv` | các lần kiểm tra (dương mới, tầng mở rộng, negative) | **không** |
| `data/weak_labels/v1/` (pairs, train…) | nhãn yếu v1 | **có**: `weak_label_NguyenDinhHieu/` |
| `data/weak_labels/v3/` | nhãn yếu hiện tại | **không** |

⚠️ Các file CSV có nhãn (tập chỉnh, tập đo, kiểm tra; tổng < 2 MB) **không tái tạo được** nếu không gán lại bằng Claude.
Nên đưa lên R2 (prefix mới) hoặc vào repo trước khi đổi máy.

## 6. Quyết định thiết kế quan trọng (kèm bằng chứng)

| Quyết định | Vì sao |
|---|---|
| Prior label model **cố định 0,10** | EM tự học thì suy biến: 94 nghìn cặp "dương" không có phiếu dương nào |
| Cặp không có phiếu dương → p ≤ 0,5 | như trên |
| Chuỗi bài khác ngày ("Giá vàng ngày 16/9" / "14/9") là **phủ quyết**, không phải phiếu | làm phiếu thì label model coi là LF kém (độ chính xác ước lượng 0,31) vì TF-IDF luôn bất đồng |
| Gộp 2 LF TF-IDF thành `lf_lexical` | bỏ phiếu giống nhau 75% → đếm trùng, tự tin quá mức |
| Cặp **cùng báo** cần ≥ 2 nhóm bằng chứng | cùng báo 1 nhóm: precision 0,57; ≥ 2 nhóm: 0,86 |
| **Ngữ nghĩa không được là bằng chứng dương duy nhất** | chỉ ngữ nghĩa: 58% đúng (điểm chuẩn hai trường khác nhau…) |
| **Áp lại chốt chặn sau hiệu chỉnh** (`finalize`) | isotonic ánh xạ 0,5 → 0,68, cặp bị chặn lọt lại |
| Negative khó phải khác **cả** từ vựng (cos < 0,15) **và** thực thể (wjacc < 0,10), khác nghĩa (cos ngữ nghĩa < 0,55), không nối qua bài trung gian, giống anchor < 95% positive | chỉ dựa "cách > 72h": 29% negative là cùng sự kiện → 12% → 2% |
| Mô hình ngữ nghĩa **khác họ** với mô hình sẽ fine-tune (MiniLM ≠ PhoBERT/e5) | tránh học vòng tròn |
| Chia train / gap 48h / holdout theo thời gian (holdout từ 13/9) | chống rò rỉ cặp giữa train và đánh giá |

## 7. Cạm bẫy

1. **Đừng chỉnh ngưỡng trên tập đo** (`v2/audit_labeled_llm.csv`). Chỉnh trên tập chỉnh (v1), xác nhận trên mẫu mới chưa từng xem.
2. **Đừng đọc tỉ lệ thô trên mẫu phân tầng là precision/recall** (recall thô của v2 là 0,52, thật 0,20). Dùng `evaluate.py`.
3. `pairs.jsonl`: `a`, `b` xếp theo **thứ tự bài trong kho**, không theo `article_id` → tra cặp bằng `frozenset((a, b))`.
4. Offset NER khớp văn bản ghép `Tiêu đề: …\n\nSapo: …\n\nNội dung:\n…` ở 99,26%; 247 bài (chủ yếu BAOCHINHPHU) lệch 1–6 ký tự — không ảnh hưởng vì chỉ cần biết vùng.
5. `uv run` không kèm `--group embed` sẽ **gỡ** PyTorch/onnxruntime khỏi `.venv`.
6. Đổi mô hình embedding (ví dụ `bge-m3`) → **phải** chỉnh lại `--dense-pos/--dense-neg` (thang cosine khác nhau).
7. Chạy lại `build` **ghi đè** `audit_sample.csv` / `audit_ids.csv` của thư mục `--out`; các file đã gán nhãn (`*_labeled_*`, `check_*`) không bị đụng, nhưng phải giữ `audit_ids.csv` khớp với chúng.
8. Script trong bash: `pkill -f <mẫu>` khớp cả chính dòng lệnh của nó → tự giết shell. Dùng `kill <pid>`.

## 8. Bước tiếp theo (theo định nghĩa đã chốt: Gói 1 / hướng E)

1. **Ghi phiếu quyết định** vào `docs/dinh-nghia-su-kien.md` mục 6 và xác nhận 3 điểm còn mở: loại sự kiện được cửa sổ
   dài (chuyến thăm, hội nghị, phiên toà, thiên tai); câu chuyện chỉ gán khi ≥ 2 sự kiện cùng chuỗi; mỗi giai đoạn vụ án
   là một sự kiện.
2. **Hướng dẫn gán theo cụm** (`event_id` + `story_id`) + bảng tính mẫu 2–3 ngày holdout (~1.000 bài) + script suy ra cặp
   và đo đồng thuận (κ, B-Cubed).
3. 2 người gán chung 150 bài → đồng thuận; Claude gán cùng 150 bài → có gán thay người được không.
4. **Nhãn yếu v4**: cửa sổ theo loại sự kiện; loại chuỗi bài định kỳ và bài tổng hợp; lớp mới "cùng câu chuyện, khác sự
   kiện" làm negative khó (luật: chung nhân vật / sự kiện lớn **và** khác địa điểm / đối thủ / ngày / văn bản — các đặc
   trưng `conflict_*`, `date_conflict` đã có trong `pairs.py`). Đo lại bằng Claude theo hướng dẫn mới.
5. Song song: **fine-tune thử trên v3** (người phụ trách EMB), so với baseline TF-IDF, MiniLM zero-shot, mô hình gốc zero-shot.
6. Tuỳ chọn: `bge-m3` qua Kaggle/Colab (chỉ tải về file `.npz` ~60 MB); hiệu chỉnh lại `p` bằng ~1.300 nhãn Claude đã có
   (giữ một phần làm tập kiểm tra).
