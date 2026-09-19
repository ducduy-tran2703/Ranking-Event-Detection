---
name: eval-protocol
description: >-
  Giao thức đánh giá mô hình của đề tài. Use when: đánh giá gom cụm sự kiện, so sánh hai
  mô hình embedding, đánh giá đặt tên sự kiện (ROUGE), đánh giá điểm xu hướng, dựng tập vàng,
  chia train/test, viết bảng kết quả vào báo cáo.
---

# Giao thức đánh giá

Một con số **không có baseline và không có khoảng tin cậy** thì không được đưa vào báo cáo.

## Chia dữ liệu

- **Chia theo thời gian**: cửa sổ huấn luyện kết thúc trước cửa sổ vàng, và **loại thêm ±48 giờ** quanh cửa sổ vàng khỏi dữ liệu sinh cặp nhãn yếu.
- Chia theo **cụm sự kiện**, không chia theo bài — chia theo bài làm rò rỉ xuyên tập.

## Tập vàng

- Một **khoảng thời gian liền mạch**, phủ đủ mọi báo. Lấy ngẫu nhiên từ nhiều tuần thì gần như không còn cụm nào.
- Gán nhãn **theo thứ tự thời gian**, theo `docs/annotation-guideline.md`.
- Gán **trước** khi xem output mô hình. Công cụ gán chỉ gợi ý bằng baseline TF-IDF, không gợi ý bằng mô hình đang so sánh.
- Đo đồng thuận người–người (B-Cubed giữa 2 người) — đó là trần của mọi mô hình.

## Chỉ số

| Tác vụ | Dùng | Không dùng |
|---|---|---|
| Gom cụm | **B-Cubed P/R/F1**, AMI, purity **kèm** inverse purity | Silhouette để so hai mô hình; purity đứng một mình |
| Phát hiện sự kiện mới | Tỉ lệ bỏ sót, tỉ lệ báo động giả, độ trễ | |
| Đặt tên | ROUGE word-level với **tokenizer tiếng Việt**, BERTScore, % đúng 5–10 từ, % trung thực thực thể, so cặp mù | ROUGE với tokenizer mặc định (phân mảnh dấu → thổi phồng điểm) |
| Xu hướng | Spearman, Kendall, NDCG@10 so với hộp "Xem nhiều" | "Đối chiếu cảm nhận" |

## Baseline bắt buộc

- Gom cụm: TF-IDF + thực thể IDF + thời gian; bản **zero-shot** của mỗi mô hình embedding.
- Đặt tên: tiêu đề medoid; tiêu đề medoid rút gọn.
- Xu hướng: xếp theo số bài; xếp theo số nguồn.

## Báo cáo

- Bootstrap 1.000 lần → khoảng tin cậy 95%. Fine-tune ≥ 3 seed.
- Chia kết quả gom cụm theo **mức trùng từ vựng** — giá trị của mô hình fine-tune chỉ lộ ra ở nhóm trùng thấp.
- Kết quả âm được báo cáo trung thực kèm phân tích, không gọt số.
