# Bàn giao: pipeline chạy liên tục (crawler → Postgres → worker → web) — 09/11/2026

## Trạng thái

| Phần | Trạng thái |
|---|---|
| Cào 8 báo, nạp `articles` | Chạy được qua `make crawler`. 4 báo mới đã thử thật (12 bài); 4 báo cũ mới kiểm robots.txt thật |
| Worker embedding → gom cụm → đặt tên → xu hướng | Đã chạy thật trên DB tạm, **chưa chạy trên DB chính** |
| Web tự thấy dữ liệu mới | API tự nạp lại sau tối đa 60 giây khi `EVENTS_BACKEND=db` |
| RAG cho bài mới | **Chưa làm**: repo không có code chạy NER, embedding chạy trên Modal |
| Bù khoảng 20/09 → 09/11 | Không làm (đã chốt): chỉ chạy tiếp từ hiện tại |

## Chạy

Cần trong `.env`: `CRAWLER_USER_AGENT` (tên bot + liên hệ thật, không bắt đầu bằng `Mozilla/`), `DATABASE_URL`,
`EVENTS_BACKEND=db`.

```bash
make db-migrate   # nếu còn migration chưa áp
make crawler      # terminal 1: :8002, CÀO NGAY khi bật rồi 30 phút/lần
make worker       # terminal 2: 5 phút/vòng (ARGS="--once" chạy một vòng)
make dev          # terminal 3: web
```

Theo dõi: `make ingest-status`, `GET http://127.0.0.1:8002/crawl/jobs`, bảng `worker_runs` (cột `status`, `error`, `stats`).

`make crawler` và `make worker` tự cài thư viện còn thiếu (`uv run --group embed`). Đừng chạy `make install` để cài cho chúng: lệnh đó là
`uv sync` không kèm `--group embed`, sẽ gỡ PyTorch khỏi `.venv`.

## Luồng dữ liệu

1. `automation/` cào, ghi `data/{bronze,silver,clean_silver}/` và `data/jobs/<job>/clean_silver/<báo>.jsonl`.
2. Khi `CRAWLER_DB_SINK=1` (`make crawler` tự đặt), `automation/db_sink.py` nạp export của job vào `articles` qua hợp đồng ingest.
   Nạp xong tạo file `<báo>.db-imported`; DB hỏng thì export còn nguyên và job sau nạp bù.
3. `src/eventrank/serving/worker.py` mỗi vòng: `embed` → `recluster` → `name` → `trend`, ghi `worker_runs`.
4. `apps/api/event_reload.py` so `worker_runs` rồi thay dữ liệu trong RAM.

## Quy tắc đối chiếu `event_id`

`reconcile` khớp cụm mới với sự kiện cũ theo Jaccard trên tập bài, một-một. Cụm không khớp → sự kiện mới. Sự kiện bị rút hết bài → `status = merged`,
`merged_into`, bookmark/theo dõi chuyển sang sự kiện nhận. Không xoá sự kiện.

## Số đo

Phát lại 12–15/09 (2.662 bài) vào DB tạm, nhịp 30 phút, vector có sẵn. B-Cubed trên tập vàng; chọn cấu hình trên 14/09, báo cáo 15/09 một lần.
CI 95%: bootstrap 1.000 lần theo cụm vàng. Baseline: gom một lần (batch) cùng mô hình, trên cùng bài.

| 15/09 (n = 755) | Precision | Recall | F1 [CI 95%] |
|---|---|---|---|
| Batch | 0,960 | 0,972 | 0,966 [0,954; 0,975] |
| Worker, không khoá (đang dùng) | 0,960 | 0,973 | 0,967 [0,955; 0,976] |

Chênh lệch worker − batch: +0,001 [−0,002; +0,004], tức ngang nhau.

| Chọn trên 14/09 (batch 0,952) | F1 | Lượt bài đổi sự kiện | Sự kiện bị gộp |
|---|---|---|---|
| Khoá ≥ 3 bài, Jaccard 0 | 0,949 | 73 | 40 |
| Khoá ≥ 5 bài, Jaccard 0,3 | 0,957 | 103 | 39 |
| Không khoá | 0,961 | 298 | 46 |

Luật khoá ≥ 3 bài của mục 9.1, đo riêng một lần trước khi chọn tham số: 15/09 F1 0,946 [0,931; 0,960], kém batch −0,020 [−0,031; −0,009].
Vì đã xem số 15/09 của cấu hình này, phép chọn sau đó chỉ dùng 14/09.

Thời gian mỗi lần `recluster` trong phép phát lại (cửa sổ quanh bài mới, không phải cả 2.662 bài): trung vị 0,25 s, tối đa 0,83 s. Chạy thật một vòng có nạp cả hai mô hình trên CPU: RSS đỉnh 1,2 GB.

**Giới hạn phải ghi khi báo cáo:** tập vàng do Claude gán, chưa có người duyệt. Chỉ đo 2 ngày. Mô phỏng coi bài đến đúng giờ đăng. Điểm xu hướng vẫn chưa
có nhãn "Xem nhiều" để đánh giá.

## Cạm bẫy

- `make crawler` **cào ngay khi bật**; lượt đầu mỗi báo tới 3 trang × 10 chuyên mục, có thể mất cả giờ với giãn cách 2 giây.
- Máy 7,6 GB: worker nạp mô hình theo từng bước rồi giải phóng, nhưng bật cùng API và Vite có thể cạn RAM (gặp 09/11: swap đầy, tác vụ treo).
- Đồng hồ DB ở chế độ replay: `db_sink` từ chối nạp bài thật.
- `DbEventStore` cần ít nhất một dòng `worker_runs` step `import`: DB mới chỉ có worker thì web báo 503. DB chính đã có.
- `make db-import-run --replace` vẫn bị chặn khi có bookmark: dùng worker, không thay cả lớp sự kiện.
- 4 báo cũ vẫn theo redirect trong đúng domain cho phép; 4 báo mới gặp redirect là dừng cả nguồn.
- Bài cũ hơn 7 ngày bị loại ở cả crawler (`CRAWLER_MAX_ARTICLE_AGE_DAYS`) và worker (`pending_max_age_days`): đổi thì đổi cả hai.

## Kiểm tra

```bash
uv run --group embed pytest -q tests/serving/test_worker.py tests/test_automation_sink.py tests/serving/test_db_store.py
```

## Còn dở

1. RAG cho bài mới: chốt ai chạy NER, rồi đồng bộ chunk và index tăng dần.
2. Bước `notify`: bảng và cột `notified_at` đã có, chưa có code gửi.
3. Đo độ ổn định `event_id` trên nhiều ngày thật; nếu thông báo trùng nhiều, cân nhắc đặt `lock_min_size` (`configs/pipeline.yaml`).
