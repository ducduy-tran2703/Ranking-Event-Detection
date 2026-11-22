# PBL: Nhận diện sự kiện đa nguồn & xếp hạng xu hướng tin tức tiếng Việt

> **Tài liệu tổng hợp duy nhất** cho toàn bộ dữ kiện của đồ án, gộp từ 20 file giải thích/tóm tắt (danh sách ở
> [Phụ lục B](#phụ-lục-b-các-file-nguồn-đã-gộp)). Tổng hợp ngày 10/10/2026.
>
> **Cách đọc:** mỗi mục ghi rõ là **HIỆN TRẠNG** (đã làm, đã đo) hay **KẾ HOẠCH** (đề xuất, chưa làm). Khi các tài liệu gốc
> mâu thuẫn, tài liệu này giữ **số mới nhất** và ghi lại chỗ lệch ở [mục 13](#13-mâu-thuẫn-giữa-các-tài-liệu-gốc-và-cách-hiểu-đúng).
> Các file gốc vẫn còn nguyên; code mẫu dài (schema SQL, crawler mẫu) chỉ có trong file gốc.

---

## Mục lục

1. [Đề tài](#1-đề-tài)
2. [Trạng thái hiện tại](#2-trạng-thái-hiện-tại-1010-2026)
3. [Kiến trúc tổng thể](#3-kiến-trúc-tổng-thể)
4. [Định nghĩa "sự kiện"](#4-định-nghĩa-sự-kiện)
5. [Dữ liệu](#5-dữ-liệu)
6. [Thiết kế data lake (kế hoạch ban đầu và hạ tầng cloud)](#6-thiết-kế-data-lake-kế-hoạch-ban-đầu-và-hạ-tầng-cloud)
7. [Nhãn yếu "cặp cùng sự kiện"](#7-nhãn-yếu-cặp-cùng-sự-kiện)
8. [Fine-tune mô hình embedding](#8-fine-tune-mô-hình-embedding)
9. [Gom cụm, đặt tên, xu hướng (kế hoạch)](#9-gom-cụm-đặt-tên-xu-hướng-kế-hoạch)
10. [Kế hoạch đánh giá và các cổng kiểm chứng](#10-kế-hoạch-đánh-giá-và-các-cổng-kiểm-chứng)
11. [Ứng dụng: cài đặt, chạy, API, triển khai](#11-ứng-dụng-cài-đặt-chạy-api-triển-khai)
12. [Phân công, lịch, rủi ro](#12-phân-công-lịch-rủi-ro)
13. [Mâu thuẫn giữa các tài liệu gốc](#13-mâu-thuẫn-giữa-các-tài-liệu-gốc-và-cách-hiểu-đúng)
14. [Thuật ngữ](#14-thuật-ngữ)
15. [Tài liệu tham khảo](#15-tài-liệu-tham-khảo)

---

## 1. Đề tài

### 1.1 Mục tiêu

Cùng một sự kiện thời sự được nhiều báo tiếng Việt đưa tin cùng lúc với cách viết khác nhau. Hệ thống cần:

1. **Gom cụm sự kiện**: tự nhận ra các bài từ nhiều báo đang nói về cùng một sự kiện thực tế.
2. **Đặt tên sự kiện**: sinh tên ngắn **5–10 từ** cho mỗi sự kiện (không phải tóm tắt dài).
3. **Xếp hạng xu hướng**: xếp sự kiện theo độ "nóng" (nhiều báo đưa, lan nhanh) thành bảng trending.

**Đơn vị phân tích là sự kiện, không phải bài báo**: 12 báo cùng đưa một tin → 1 sự kiện.

**Sản phẩm cuối:** web dashboard bảng xu hướng; mobile app xem feed sự kiện + thông báo đẩy khi có sự kiện mới nổi;
**ít nhất 2 mô hình fine-tune và so sánh** cho mỗi tác vụ ML chính (embedding, đặt tên).

### 1.2 Vì sao khó (khác tóm tắt tin thông thường)

- Số sự kiện **không cố định**, sinh liên tục → không phải phân loại có nhãn cố định, mà là **đo tương đồng ngữ nghĩa +
  gom cụm tăng dần**. Đây là khung kinh điển **Topic Detection and Tracking (TDT)**.
- **Không có dữ liệu gán nhãn** "bài nào cùng sự kiện với bài nào" → tự tạo dữ liệu huấn luyện bằng **giám sát yếu**.

### 1.3 Ngoài phạm vi

Phát hiện tin giả, tóm tắt văn bản dài. Điểm xu hướng dùng **công thức**, không ép học máy (không có nhãn độ nóng).

### 1.4 Đánh giá ban đầu của bản đề xuất (phân tích phản biện)

Hướng đi đúng, nhưng bản mô tả đầu tiên có 3 lỗi khiến kết quả ML "trông đẹp mà vô nghĩa". **Cả ba đã được sửa trong thiết
kế hiện tại:**

| Lỗi trong bản đầu | Đã sửa thành |
|---|---|
| Luật nhãn yếu "trùng ≥2 thực thể + 48h + **cùng chuyên mục**"; cặp âm "khác ngày, khác chuyên mục" | Nhiều hàm gán nhãn + label model; "cùng chuyên mục" **không bao giờ là phiếu dương** (nó chặn đúng cặp khác báo); negative khó (mục 7) |
| Nhãn tham chiếu đặt tên = tiêu đề bài uy tín nhất → baseline "chọn tiêu đề" thắng theo định nghĩa | Nhãn đánh giá do **người viết mù**; baseline tiêu đề medoid (mục 9.2) |
| Đánh giá gom cụm bằng silhouette / purity / NMI trên 500–1.000 bài ngẫu nhiên | **B-Cubed** trên một **cửa sổ thời gian liền mạch** (mục 10) |
| Tiền đề "không thể chạy batch" → gom cụm tăng dần thuần | Kiến trúc **lai**: gán nhanh + gom lại cửa sổ 48h mỗi 15 phút + đối chiếu ID (mục 9.1). Gom 48h (~4.000 bài) mất **<10 giây** |
| Silver **xoá** bài gần trùng | **Đánh dấu** `dup_group_id`, không xoá: "nhiều báo cùng đưa" là tín hiệu chính |
| Phạm vi web + mobile + push + 4 tác vụ ML trong ~480 giờ | Mobile cắt về **bản tối thiểu** |

---

## 2. Trạng thái hiện tại (10/10/2026)

| Phần | Trạng thái | Chi tiết |
|---|---|---|
| Thu thập + kho Silver | **Chạy được.** 6 báo, ~28,7 nghìn bài | Mục 5.2 |
| Gold (NER) | **Có trên R2**, do thành viên khác làm. 28.746 bài, 940.474 thực thể, 6 nhãn | Mục 5.4 |
| Nhãn yếu | **v3 xong**: precision cặp dương 0,93, recall 0,28 (Claude gán mù, có trọng số theo tầng) | Mục 7 |
| Định nghĩa "sự kiện" | **Đã chốt Gói 1 / hướng E**: đơn vị = sự kiện tin tức, nhóm cha = câu chuyện. Phiếu quyết định chưa ghi vào tài liệu | Mục 4 |
| Fine-tune embedding | **Notebook đã có, chưa có kết quả lưu về.** Đang dùng dữ liệu train **tạm** | Mục 8 |
| Gom cụm, đặt tên, xu hướng | **Chưa làm** | Mục 9 |
| Web / API kiểm soát dữ liệu | **Chạy được** (FastAPI + React) | Mục 11 |
| Mobile | Chưa làm | — |
| Nhãn người | **Chưa có.** Mọi số đo chất lượng dùng nhãn Claude | Mục 7.8 |

**Repo:** `github.com/ducduy-tran2703/Ranking-Event-Detection` (private, chủ repo Trần Đức Duy).

---

## 3. Kiến trúc tổng thể

### 3.1 Năm tầng (dữ liệu chỉ chảy lên trên)

| Tầng | Thành phần | Lưu ở đâu |
|---|---|---|
| 1. Thu thập | Crawler: sitemap (backfill), RSS (tin mới), hộp "Xem nhiều" | R2 `silver/` (hiện tại) · `bronze/` (hướng tới) |
| 2. Kho dữ liệu | Hiện có Silver (JSONL) + Gold (NER) + nhãn yếu. Hướng tới Bronze → Silver → Gold → snapshots | Cloudflare R2, bucket `vietnam-news-datalake` |
| 3. Xử lý / ML | NER → nhãn yếu → embedding → gom cụm → đặt tên → xu hướng | Đọc/ghi R2; huấn luyện trên Kaggle/Colab |
| 4. Phục vụ | FastAPI + Postgres (sự kiện, tên, điểm, thông báo đã gửi) | Postgres |
| 5. Giao diện | Web dashboard, mobile app (thông báo đẩy) | — |

Chiều phụ thuộc trong `src/`: `common ← ingest ← lake ← nlp ← weak_labels ← embeddings ← clustering ← naming, trending ← serving ← apps`.
Hiện `src/eventrank/` mới có `common/`, `lake/`, `weak_labels/`; `apps/` có `api/`, `web/`.

### 3.2 Kiến trúc mục tiêu (sau khi sửa các lỗi thiết kế)

```
 NGUỒN: RSS (bài mới) + sitemap/lưu trữ (backfill) + hộp "Xem nhiều" (mỗi giờ)
 ══ BRONZE ══  html.gz theo url_hash/crawl_ts · snapshot RSS/sitemap · snapshot "xem nhiều"  (chạy lại được mọi bước sau)
 ══ SILVER ══  tách bài → bài sạch · chuyên mục → bảng ánh xạ liên báo
               trùng URL (xoá) · gần trùng → dup_group_id (ĐÁNH DẤU, không xoá)
 ══ GOLD ════  NER → chuẩn hoá (alias, chức danh, ngày tương đối → tuyệt đối)
               hàm gán nhãn → label model → cặp yếu (chia theo thời gian, loại cửa sổ vàng)
               embedding: [TF-IDF] [A zero-shot] [A fine-tune] [B zero-shot] [B fine-tune]  (lưu theo model_version)
 ══ SERVING ═  gán nhanh single-pass (mỗi bài)
               gom lại cửa sổ 48h + ĐỐI CHIẾU ID (mỗi 15') ──► events (event_id ổn định)
                    ├──► đặt tên (ViT5 | BARTpho) + kiểm tra trung thực + chính sách ổn định tên
                    └──► điểm xu hướng (công thức)
               cổng thông báo: sự kiện ỔN ĐỊNH (≥k nguồn, đã qua đối chiếu) + chưa gửi + tên đã kiểm tra
                    ──► FastAPI ──► Web dashboard + Mobile (feed + chi tiết + push, bản tối thiểu)
```

Hai quy tắc giúp các giai đoạn không chờ nhau:
1. Nhóm ML **chỉ đọc snapshot đóng băng** (có manifest), không đọc thẳng dữ liệu đang cào.
2. Mọi bảng dẫn xuất có **cột phiên bản** (`parser_version`, `model_version`, `algo_version`); đổi logic thì tăng phiên bản, không ghi đè.

---

## 4. Định nghĩa "sự kiện"

### 4.1 Vì sao phải chốt

Định nghĩa quyết định: cặp nào là dương / negative khó và cửa sổ thời gian (nhãn yếu); chuẩn gán của người và Claude (tập
vàng, κ); cụm to hay nhỏ (gom cụm); có đặt tên 5–10 từ được không; đếm độ nóng trên đơn vị nào (xu hướng).

### 4.2 Các phương án

TDT định nghĩa **event** = "một việc xảy ra tại một thời điểm và địa điểm cụ thể" (gần A), **topic** = "sự kiện gốc cùng
các sự kiện liên quan trực tiếp" (gần C).

| | Định nghĩa | Ví dụ |
|---|---|---|
| **A** Hành động đơn lẻ | Một việc cụ thể, tại một thời điểm, địa điểm | Lễ đón TBT tại Australia (11/8) và tuyên bố chung (12/8) → 2 sự kiện; nhận định trước trận và kết quả cùng trận → 2 |
| **B** Sự kiện tin tức | Một việc cụ thể **cùng các tin tiếp nối trực tiếp** trong vài ngày (phản ứng, cập nhật) | "X bị bắt" và "X bị khởi tố" → 1; trước/sau cùng trận → 1; lễ đón, hội đàm, tuyên bố chung cùng chuyến thăm → 1; hai trận khác nhau cùng giải → 2; giá vàng 16/9 và 14/9 → 2 |
| **C** Câu chuyện | Toàn bộ diễn biến của một câu chuyện, không giới hạn ngày | Mọi bài về ASIAD 2026 → 1; cả vụ án Mường Thanh → 1 |
| **D** Chủ đề | Mọi bài cùng chủ đề ("giá vàng") | **Không phải sự kiện**, chỉ để tham chiếu. MiniLM zero-shot nghiêng về mức này |
| **E** Hai tầng | **B làm đơn vị**, C làm nhóm cha "câu chuyện" | Nhãn yếu và tập vàng gán theo B; thêm cột "câu chuyện" tuỳ chọn |

Nhãn yếu v1–v3 và mọi lần Claude gán mù đều ngầm dùng **phương án B**.

### 4.3 Chấm điểm (1–5, trọng số bằng nhau)

| Tiêu chí | A | B | C | **E** |
|---|---|---|---|---|
| T1 Dễ gán nhất quán | 5 | 3 | 2 | 3 |
| T2 Precision nhãn yếu ≥ 0,8 | 5 | 5 | 3 | 5 |
| T3 Đủ dữ liệu train | 2 | 3 | 5 | 3 |
| T4 Giá trị của fine-tune | 3 | 4 | 1 | **5** |
| T5 Gom cụm khả thi | 4 | 4 | 2 | 4 |
| T6 Đặt tên 5–10 từ | 5 | 4 | 2 | 4 |
| T7 Giá trị cho người dùng | 2 | 4 | 3 | **5** |
| T8 Bảo vệ trước hội đồng | 4 | 4 | 3 | **5** |
| T9 Chi phí chuyển đổi | 3 | 5 | 1 | 4 |
| **Tổng** | 33 | 36 | 22 | **38** |

Nếu T4 và T8 nặng gấp đôi: E 48, B 44, A 40, C 26.

### 4.4 Quyết định đã chốt: **Gói 1 (hướng E, cửa sổ theo loại sự kiện)**

| Quyết định | Chọn |
|---|---|
| Đơn vị | B: sự kiện tin tức |
| Nhóm cha | C: câu chuyện, gán thưa cho cụm lớn |
| Cửa sổ | Mặc định 72h; chuyến thăm / hội nghị / phiên toà theo lịch trình của chính sự kiện (tối đa 7 ngày) |
| Chuỗi bài định kỳ ("Giá vàng hôm nay"), bài tổng hợp nhiều tin | **Loại khỏi gom cụm** |
| Bài phân tích, bình luận | **Không thuộc** sự kiện |
| "Sắp diễn ra" ↔ "đã diễn ra" cùng một việc | **Cùng** sự kiện |

**Ba điểm còn mở cần xác nhận:** loại sự kiện nào được cửa sổ dài (chuyến thăm, hội nghị, phiên toà, thiên tai); câu
chuyện chỉ gán khi ≥ 2 sự kiện cùng chuỗi; mỗi giai đoạn vụ án là một sự kiện.

Các gói khác để tham khảo: **Gói 2** = B, 72h + loại chuỗi định kỳ / bài tổng hợp (đơn giản nhất, nâng lên Gói 1 sau được);
**Gói 3** = B, cửa sổ cố định 7 ngày (precision ước giảm); **Gói 4** = A, 48h (chọn khi κ với B quá thấp). **C làm đơn vị:
không khuyến nghị.**

### 4.5 Ca biên (dữ liệu thật tháng 8–9/2026): 1 = cùng, 0 = khác

| # | Cặp bài (rút gọn) | A | **B** | C |
|---|---|---|---|---|
| 1 | Ngộ độc bánh mì Gia Lai (Nhân Dân) ↔ Cục ATTP yêu cầu điều tra (Tuổi Trẻ), cách 1h | 1 | **1** | 1 |
| 2 | U23 VN: Kuwait ↔ U23 VN gặp Philippines (hai trận) | 0 | **0** | 1 |
| 3 | Nhận định MU–Ipswich ↔ MU đại thắng (cùng trận) | 0 | **1** | 1 |
| 4 | Lễ đón TBT tại Australia (11/8) ↔ Tuyên bố chung (12/8) | 0 | **1** | 1 |
| 5 | TBT sắp thăm Australia ↔ Australia hỗ trợ VN thành trung tâm khoa học (cách 129h) | 0 | **1?** | 1 |
| 6 | Truy tố Chủ tịch Mường Thanh ↔ Truy tố ông Lê Thanh Thản (cùng quyết định) | 1 | **1** | 1 |
| 7 | Xét xử tài xế xe tải ↔ quan hệ cựu phó thủ trưởng điều tra với tài xế (cách 7 ngày) | 0 | **?** | 1 |
| 8 | Giá vàng 16/9 ↔ Giá vàng 14/9 | 0 | **0** | 0 |
| 9 | Lịch thi đấu 13/9 ↔ Kết quả 13/9 (bài tổng hợp nhiều trận) | 0 | **0** | 0 |
| 10 | Điểm chuẩn ĐH Thủy lợi ↔ ĐH Điện lực | 0 | **0** | 0 |
| 11 | Điện đàm Trump–Putin ↔ đặc phái viên Mỹ tới Kyiv | 0 | **0** | 1 |
| 12 | Sắp xếp trường phường Xuân Hòa ↔ phường Bảy Hiền | 0 | **0** | 0? |
| 13 | Bỏ điểm cộng IELTS ↔ bỏ quy định trường tự ra đề (cùng dự thảo) | 1? | **1** | 1 |
| 14 | Bóng chuyền nữ ASIAD: VN 3-0 Hồng Kông ↔ VN 3-0 Qatar | 0 | **0** | 1 |
| 15 | Phân tích "Nguy cơ Iran leo thang" ↔ Tổng thống Iran "thách đấu" Mỹ | 0 | **0?** | 1 |
| 16 | Bài tổng hợp "Tin tức thế giới 1-9" ↔ tin riêng một mục trong đó | 0 | **?** | ? |
| 17 | Cháy nhà 5 người chết ở Tây Hồ ↔ Bí thư Hà Nội thăm nạn nhân | 0? | **1** | 1 |

### 4.6 Định nghĩa dùng khi gán nhãn (mọi lần Claude gán mù)

- **1**: cùng một việc cụ thể đã xảy ra (cùng vụ án, trận đấu, chuyến thăm, quyết định, tai nạn); bài cập nhật diễn biến
  của chính việc đó trong vài ngày cũng là 1.
- **0**: chỉ cùng chủ đề / nhân vật nhưng khác việc (hai trận khác nhau, giá vàng hai ngày, điểm chuẩn hai trường).

### 4.7 Việc sau khi chốt

1. Cập nhật hướng dẫn gán cho người (`human_label_100.csv`) và Claude; 15–20 ví dụ chuẩn.
2. Chỉnh `POS_MAX_HOURS` và luật trong `src/eventrank/weak_labels/lfs.py`; đo lại bằng `evaluate.py`.
3. 2–3 người cùng gán 50 cặp → đo κ. **κ < 0,6** thì định nghĩa còn mơ hồ, bổ sung ví dụ trước khi gán quy mô lớn.

---

## 5. Dữ liệu

### 5.1 Khảo sát nguồn (đo 15/09/2026)

| Báo | `robots.txt` | Sitemap lịch sử | Lượng bài | Kết luận |
|---|---|---|---|---|
| Thanh Niên | Cho phép | `sitemaps/sitemaps-YYYY-M-D1-D2.xml`, mỗi file 5 ngày | 1.361 URL / 6–10/9 ≈ **270 bài/ngày** | Backfill được. JSON-LD `NewsArticle` đầy đủ (`headline`, `description`, `datePublished` có múi giờ, `articleSection`) |
| Tuổi Trẻ | Cho phép | `StaticSitemaps/sitemaps-YYYY-M-D1-D2.xml`, 5 ngày | 1.232 URL / 6–10/9 ≈ **250 bài/ngày** | Backfill được. ⚠️ `lastmod` ghi **2011-01-01** → lọc theo tên file |
| Dân Trí | Cho phép, `Crawl-delay: 1` | `sitemaps/Article-YYYY-MM-01.xml`, mỗi file 1 tháng, 258 file | 7.544 URL tháng 6, 5.038 tháng 7 ≈ 160–250/ngày | Backfill **đến hết 7/2026** (tháng 9 trả 404). ⚠️ File có **BOM** |
| VietnamNet | Cho phép | `sitemap-article-MM-YYYY-NN.xml`, mỗi phần ≤ 1.000 URL | 6 phần/tháng ≈ ~200/ngày | Backfill được, phải duyệt **hết các phần** |
| VnExpress | Cho phép `*`, **chặn đích danh `Scrapy`, `news-please`** và bot AI | File sitemap theo ngày **302 → trang chủ** | — | **Không backfill qua sitemap**, chỉ RSS. **Không vượt chặn** |

Chuyên mục **không có trong RSS**: lấy từ JSON-LD `articleSection` / meta `article:section` / breadcrumb.

### 5.2 Kho thực tế trên R2 (HIỆN TRẠNG)

**Kho local của crawler `automation/` (09/11/2026):** tách biệt với R2 bên dưới.
Tuổi Trẻ, Thanh Niên, VietnamNet và VnExpress dùng `data/{bronze,silver,clean_silver}/<source>/<article_id>.json`
và bản xuất `data/jobs/<job_id>/{bronze,silver,clean_silver}/<source>.jsonl`,
với `<source>` là `tuoitre`, `thanhnien`, `vietnamnet` hoặc `vnexpress`, cùng cấu trúc các báo automation khác.
Không tự upload hoặc thay đổi các object Silver trên R2.

| | |
|---|---|
| Nhà cung cấp / bucket | Cloudflare R2 · **`vietnam-news-datalake`** (không có versioning: xoá hay ghi đè là mất vĩnh viễn) |
| Lớp đang có | **Silver** (JSONL, UTF-8, mỗi dòng một bài) + **Gold** (NER) + nhãn yếu v1. **Chưa có Bronze** |
| Quy ước | Mỗi báo một thư mục `silver/<source>/`, viết thường, không dấu. Đọc toàn bộ bằng `silver/*/*.jsonl` (biến `LAKE_SILVER_GLOB`). Mỗi người chỉ ghi vào thư mục của báo mình phụ trách |

Ảnh chụp 19/09/2026 (4 nguồn, 18.124 bài, 96,6 MB):

```
vietnam-news-datalake/
├── silver/
│   ├── baochinhphu/article_silver.jsonl     4.477 bài · 29,6 MB
│   ├── baodantri/silver_nhandan.jsonl       4.517 bài · 24,2 MB   ⚠ tên thư mục, tên file, trường source lệch nhau
│   ├── vietnamnet/articles_silver.jsonl     4.645 bài · 22,2 MB
│   └── vnexpress/articles_silver.jsonl      4.485 bài · 20,5 MB
├── gold/                                    (thêm sau)
│   ├── README.md
│   └── gold_data.jsonl                      28.746 bài · 940.474 thực thể · 93 MB
└── weak_label_NguyenDinhHieu/               nhãn yếu v1 (01/10/2026), ghi một lần, không ghi đè
    ├── train_triplets.jsonl  10.005 bộ ba · 13 MB
    ├── train_pairs.jsonl     177.499 cặp · 153 MB
    ├── pairs.jsonl           327.230 cặp · 152 MB
    ├── articles.jsonl        28.725 bài · 18 MB
    └── report.json
```

**Các prefix nhãn / mô hình / tập vàng (cập nhật 21/10/2026)** — mỗi prefix ghi một lần, bản mới sang prefix mới:

```
weak_label_NguyenDinhHieu/
├── (gốc)        nhãn yếu v1 — như trên
├── v3/          nhãn yếu v3 (pairs.jsonl 239 MB, train_pairs/triplets, articles, check_*_llm.csv, README) — tải lên 21/10/2026
└── v4/          nhãn 4 mức v4: final/ (14/10), final_v2/ (15/10), ★ final_v3/ (30/10/2026, gán lại theo quy tắc 29/10 —
                 bản đang dùng; kèm nhan_gan_lai/ từng vòng + README), hard/hardtest, human_label_100
models/embedding_v1_NguyenDinhHieu/      bkai fine-tune v1 (CoSENT, v4 bản 2, s44) + results + README
models/naming_vit5_v1_NguyenDinhHieu/    ViT5 đặt tên sự kiện v1 (03/11/2026, s42 epoch 4, 904 MB fp32): model/ + results +
                                         dự đoán dev 3 seed + notebook + README (cách dựng đầu vào bắt buộc)
models/embedding_v2_{bkai,e5,tabert}_NguyenDinhHieu/
                                         embedding v2 (CoSENT, v4 bản 3, 30/10–02/11/2026): bkai s42, e5 s43, tabert s44 —
                                         model/ + results + PREPROCESS + README (so sánh có CI); pipeline vẫn dùng v1.
                                         tabert: giấy phép AGPL-3.0
events_NguyenDinhHieu/v1/                sự kiện từ pipeline gom cụm v1 (02/11/2026): su_kien.csv, bai_su_kien.csv,
                                         manifest.json, cache/emb_bkai_ft_v1_s44.npz, README
events_NguyenDinhHieu/v2/                ★ lần chạy pipeline đầy đủ 2026-11-03_v2 (gom cụm + đặt tên ViT5 + xu hướng t2):
                                         su_kien.csv (tên, điểm), ten_su_kien.csv, xu_huong*.csv, events.json, manifest,
                                         trang mo-ta-pipeline.html, cum/. ⚠ Có tên ViT5 cho 14–15/09: người viết tên mù
                                         cho tập test không mở
datasets_NguyenDinhHieu/v2/              ★ HAI FILE GỌN, dùng cái này trước (02/11/2026, = final_v3): cap_su_kien_v4.csv
                                         (25.843 cặp: train 25.006 / test 644 / test_hard 193, kèm văn bản + trọng số) và
                                         cum_su_kien_14-15_09.csv (1.496 bài, event_id, split tune/test, tóm tắt);
                                         cùng dữ liệu cặp tách sẵn: train.csv (25.006) + test.csv (837 = test 644 +
                                         test_hard 193) + README.md giải thích cột và mức
datasets_NguyenDinhHieu/v1/              bản cũ (30.552 cặp, nhãn theo quy tắc trước 29/10) — sinh bằng evaluation/gold_export.py
db_NguyenDinhHieu/v1/                    bản dump Postgres `eventrank` (04/11/2026, pg_dump 18 -Fc, 147 MB): bài + sự kiện run
                                         2026-11-03_v2 (tên đã ẩn 14–15/09) + điểm xu hướng + vector bkai v1; SHA256SUMS,
                                         schema/001–002.sql, README (cài Postgres, tải, pg_restore ≥ 18, xem dữ liệu)
gold_clusters_NguyenDinhHieu/v1/         tập vàng gom cụm 14–15/09 (1.496 bài): gold_clusters_v2.csv (đáp án hiện tại),
                                         proposals*.json, emb_bkai_ft.npz (vector bkai v1), tóm tắt toàn văn, nhật ký kiểm tra,
                                         3 trang HTML, README — chi tiết mục 10.2
```

Sau đó kho có **6 báo, 28.746 bài**: tuoitre 5.447 · thanhnien 5.175 · vietnamnet 4.645 · nhandan 4.517 · vnexpress 4.485 ·
baochinhphu 4.477. Bài trải từ 2008 đến 19/9/2026 nhưng **76% nằm trong 1/8–19/9/2026** (50 ngày, trung vị ~420
bài/ngày, cao nhất 829): giai đoạn phù hợp nhất để gom cụm. Tháng 9: 11.667 bài, tháng 8: 10.202, tháng 7: 2.491.

**Hướng tới (chưa làm):** người đọc không phải sửa code, chỉ đổi `LAKE_SILVER_GLOB`.

```
bronze/articles/source=<báo>/dt=<ngày CÀO>/<article_id>__<YYYYMMDDTHHMMSS>.html.gz
silver/articles/source=<báo>/dt=<ngày ĐĂNG>/part-<uuid>.jsonl
snapshots/<tên>_v<n>/…  + MANIFEST.json
models/<tên>/<phiên bản>/…
```

Thêm Bronze (sửa parser chạy lại được), chia Silver theo ngày đăng thành nhiều file (thêm dữ liệu = thêm file, không ghi
đè), tên file có uuid, snapshot đóng băng. Giữ JSONL được tới vài trăm MB rồi mới cân nhắc Parquet.

**Lớp Postgres cho hệ thống chạy liên tục (HIỆN TRẠNG từ 04/11/2026, giai đoạn 1).** Postgres là nơi lưu chính của bản
"web chạy như thật" (cào liên tục → embedding → gom cụm tăng dần → đặt tên → xu hướng → API). Giai đoạn 1 mới có tầng Thu
thập; R2 Silver vẫn là kho chung của nhóm ML và không đổi. Hướng dẫn cho người viết crawler: `docs/handoff/ingest.md`.

| Bảng (`infra/db/migrations/001_ingest.sql`) | Khoá | Nội dung |
|---|---|---|
| `sources` | `source` | tên hiển thị, homepage, `enabled`, `crawler` ("module:Lớp"), ghi chú — nạp từ `configs/sources.yaml` |
| `articles` | `article_id` (char 64 = sha256(url)); `url` UNIQUE | 9 trường hợp đồng 5.3 + `crawled_at` (lần đầu, không đổi), `updated_at`, `ingested_via` (`import_jsonl` / `replay` / `crawler:<tên>`), `parser_version`, `content_hash`, `quality_flags text[]`, `dup_group_id` (NULL, đánh dấu không xoá). Chỉ mục `published_at`, `(source, published_at)`, `updated_at` |
| `crawl_runs` | `run_id` | mỗi lần một crawler/import chạy cho một báo: giờ, `status` running/ok/failed/blocked, `n_seen/new/updated/unchanged/rejected`, `reject_reasons`, `error` — chống "crawler chết âm thầm" |
| `app_clock` | một dòng | `mode` real/replay, `sim_now`, `speed`; hàm `app_now()` = "bây giờ" của hệ thống (giai đoạn 2 worker/API đọc ở đây) |
| `schema_migrations` | tên file | sha256 + thời điểm áp; file đã áp bị sửa → báo lỗi |

Chỉ dùng Postgres ≥ 14, **không pgvector** (vector giai đoạn 2 lưu `bytea`). Migration = SQL thuần đánh số, không ORM.
Ghi idempotent (`INSERT … ON CONFLICT (article_id)`, chỉ UPDATE khi `content_hash` đổi). Đo 04/11/2026 (Postgres 18 tạm):
`import-jsonl` toàn bộ Silver ở máy = 28.725 bài ghi / 21 loại (`published_at` rỗng, đều Thanh Niên) trong 8,3 s, bảng
`articles` 96 MB; chạy lại = 0 bài mới. Cờ: `missing_author` 2.195, `no_body` 183, `short_body` 146, `missing_sapo` 8.

**Tầng Sự kiện trong Postgres (`infra/db/migrations/002_events.sql`, từ 04/11/2026).** Hiện được NẠP từ một lần chạy
pipeline offline (`make db-import-run` = `python -m eventrank.serving.db_import [data/runs/<run_id>]`); worker gom cụm
liên tục (giai đoạn 2) sẽ ghi vào cùng các bảng. **API web đọc DB khi `EVENTS_BACKEND=db`** (`serving/db_store.py`,
`DbEventStore`; mặc định `files` = CSV của run qua `serving/store.py`): dữ liệu lấy từ Postgres lúc khởi động (~2 s), mọi
logic truy vấn dùng chung `EventStore._index` → đối chiếu run v2 (04/11/2026): bảng xu hướng 1.200 mốc, 10 bộ lọc danh
sách, thống kê và trang chi tiết của cả 19.938 sự kiện khớp bản CSV (số thực lệch ≤ 1e-4 do cột `real`). URL bài lấy từ
`articles`; bản đồ 2D vẫn là file `ban_do/` của thư mục run nếu có. DB đổi → khởi động lại API.

| Bảng | Khoá | Nội dung |
|---|---|---|
| `events` | `event_id` (`E<ngày>-<8 hex>`) | `status` open/closed/merged/hidden (+ `merged_into`), `first_seen`, `last_seen`, `size`, `n_sources`, `sources` jsonb, `medoid_article_id`, `medoid_title`, `display_name` (ĐÃ áp luật ẩn tên), `name_source` model/medoid/title/editor, `name_hidden`, `category_std`, `is_stable`, `notified_at`, `peak_score/peak_at`, `total_score`, `top10_hours`, `algo/model/trend_version` |
| `event_articles` | `article_id` (mỗi bài đúng một sự kiện) | `event_id`, `assigned_at`, `method` fast/recluster/import, `similarity` (cosine TB với các bài khác trong cụm), `is_medoid` (≤ 1 mỗi sự kiện) |
| `event_assignment_log` | `log_id` | mỗi lần bài đổi sự kiện: `from_event` (NULL = gán đầu), `to_event`, `reason`, `worker_run_id` |
| `event_names` | `name_id`; ≤ 1 dòng `is_current` mỗi sự kiện | `name`, `source`, `naming_version`, `size_at_naming`, `checks` jsonb (lý do rơi về medoid / `an_ten`) |
| `trend_scores` | (`trend_version`, `t`, `event_id`) | MỌI ứng viên mỗi mốc giờ: `score`, `rank`, `n_articles`, `n_articles_3h`, `n_sources`, `n_sources_eff`, `velocity` |
| `trend_baselines` | (`trend_version`, `hour_of_day`) | mức nền theo giờ trong ngày (TB = 1) |
| `article_embeddings` | (`article_id`, `model_version`) | `vec` bytea float32 LE đã chuẩn hoá L2, `dim`, `content_hash` (khác bài hiện tại → tính lại) |
| `worker_runs` | `run_id` | mỗi vòng worker / lần nạp (`step` import/embed/assign/recluster/name/trend/notify), `versions`, `stats`, `status` |
| `category_map` | (`source`, `category_raw`) | chuyên mục chung (`norm_category`) |
| `most_read_snapshots` | `snapshot_id`; UNIQUE (`source`, `captured_at`, `rank`) | hộp "Xem nhiều" mỗi giờ (chưa có crawler ghi) |

Ẩn tên tập test đặt tên: sự kiện bị ẩn (cửa sổ 14–15/09 + tên gần trùng, cùng luật `EventStore`) chỉ có tên medoid
trong DB; tên mô hình bị loại (`ten_mo_hinh`) không được ghi. Nạp với `EVENTS_HIDE_NAMES_WINDOW=off` bị từ chối. Điểm xu hướng
tính lại bằng `trending.score_at` và đối chiếu top-K từng mốc với `xu_huong.csv` (lệch → dừng). Nạp run `2026-11-03_v2`
(04/11/2026): 19.938 sự kiện (1.027 ẩn tên), 28.725 bài + vector, 18.396 dòng điểm trên 1.200 mốc, 13–15 s (nạp lại cùng thời gian). Similarity trong cụm (≥ 2 bài): TB 0,895, thấp nhất 0,797.

**Tầng Tài khoản trong Postgres (migration 003–006, từ 04/11/2026).** Theo bản thiết kế database (`pbl/thiet-ke-database.html`);
nghiệp vụ `src/eventrank/accounts/` (auth, me, admin, cli), HTTP `apps/api/accounts.py`, test `tests/api/test_accounts_api.py`.

| File | Bảng | Ghi chú |
|---|---|---|
| `003_auth.sql` | `users`, `user_sessions`, `auth_tokens`, `login_attempts`, `user_settings` | Mật khẩu Argon2id (PHC); token phiên/email chỉ lưu sha256; email duy nhất trong tài khoản CÒN SỐNG (`deleted_at IS NULL`) |
| `004_user_features.sql` | `event_bookmarks`, `event_follows`, `topic_subscriptions`, `feedback_reports` | FK vào `events`; chủ đề duy nhất theo `lower(value)`, ≤ 50/người; báo sai: khách gửi được (IP giữ 90 ngày) |
| `005_notifications.sql` | `notifications`, `email_outbox` | Bản demo CHƯA gửi thư: thư nằm ở `email_outbox` + link ghi vào log máy chủ |
| `006_admin.sql` | `audit_logs`, `api_tokens` | Khoá API chỉ hiện đầy đủ một lần; DB giữ sha256 + 10 ký tự đầu |

Chưa làm (migration sau): `oauth_identities` (Google), `event_views` (cá nhân hoá), `push_devices`,
`notification_deliveries` (cổng thông báo + mobile). Luật: sai mật khẩu 5 lần/15 phút → khoá 15 phút (423); 30 lần sai/15
phút từ một IP → 429; không lộ email đã đăng ký (đăng ký/quên mật khẩu/đăng nhập trả cùng phản hồi, email lạ vẫn chạy Argon2
trên băm giả); phiên "giữ đăng nhập" trượt 30 ngày (không thì 12 giờ), tối đa 90 ngày; đặt lại mật khẩu thu hồi MỌI phiên,
đổi mật khẩu thu hồi các phiên khác; CSRF: cookie `csrf_token` + header `X-CSRF-Token` cho mọi POST/PUT/DELETE khi đã đăng
nhập. Đăng ký trên web luôn là `user` — admin đầu tiên: `uv run python -m eventrank.accounts create-user --email … --role
admin` (mật khẩu từ `ACCOUNT_PASSWORD` hoặc hỏi). Dọn dữ liệu cá nhân quá hạn: `python -m eventrank.accounts cleanup`.
Nạp lại lớp sự kiện (`db_import`) bị CHẶN khi đã có dòng nào trong các bảng này trỏ vào một sự kiện.

**Tầng RAG local (migration `007_rag.sql`, 04/11/2026).** Đồng bộ nguyên bản migration 003–006
(tài khoản, tính năng người dùng, thông báo, quản trị) từ `db_NguyenDinhHieu/v1/schema/`; không thay đổi dump R2.
Ba bảng dưới đây giữ phiên bản hiện hành. Đã nhập NER và chia chunk từ snapshot Silver/NER (04/11/2026).
Vector retrieval sẽ lưu ở Qdrant;
BM25 lưu trên disk (Tantivy), không lưu thêm vector retrieval trong Postgres.

| Bảng | Khoá / quan hệ | Cột |
|---|---|---|
| `article_ner` | `article_id` PK, FK → `articles` | `canonical_text`, `text_hash` SHA256 UTF-8 của canonical text, `ner_version`, `entities` jsonb array, `updated_at` |
| `rag_chunks` | `chunk_id` UUID PK (dùng làm point ID Qdrant), `article_id` FK → `article_ner`; UNIQUE (`article_id`, `chunking_version`, `chunk_index`) | `chunk_index` từ 0, `text` nguyên văn, `start_char`, `end_char`, `chunking_version` |
| `rag_index_status` | `chunk_id` PK, FK → `rag_chunks` | `index_version`, `bm25_status`, `qdrant_status` (pending/ready/failed), `error`, `updated_at` |

URL, nguồn, ngày và mapping sự kiện lấy qua `articles`/`event_articles`, không lưu lặp trong các bảng RAG.
Tên collection Qdrant, đường dẫn BM25 và cấu hình model gắn với `index_version` trong cấu hình bên ngoài.
`updated_at` có mặc định khi INSERT; code ghi phải cập nhật tường minh khi UPDATE. FK không tự xoá dây chuyền.
Chi tiết môi trường: [bàn giao RAG](handoff/rag.md). Lộ trình triển khai và điểm tiếp nhận chat mới:
[kế hoạch RAG](plan-rag.md).

Migration tính checksum theo byte: `.gitattributes` ghim `infra/db/migrations/*.sql` về LF để Windows/Linux
không báo sai `modified` chỉ vì CRLF. Không sửa checksum trong `schema_migrations` để bỏ qua sai khác.

**Preparation RAG bước 1–2:** `python -m eventrank.rag.prepare --ner-version …` (`make rag-prepare ARGS="…"`),
cấu hình `configs/rag.yaml`. Dùng Silver nguyên gốc để dựng canonical text, kiểm content hash với DB theo hợp đồng
ingest và kiểm mọi entity slice trước khi ghi theo lô. Bài ngoài DB được đếm và bỏ qua; thiếu NER cho bài trong DB
thì dừng preflight. Bản đầu chunk theo whitespace units (mục tiêu 320, overlap 48), ưu tiên đoạn/câu và không cắt
entity; UUIDv5 phụ thuộc bài, hash text, cấu hình và offset. Chưa tune theo đánh giá RAG.
Lần chạy thật: 28.725 dòng `article_ner`, 939.203 entity, 96.230 chunk/trạng thái pending; 21 bài ngoài DB không nhập.
Kiểm toàn kho: 0 sai hash/slice, 0 boundary cắt entity, 0 bài hở nội dung và 0 entity không nằm trọn trong chunk.
4 chunk có 321 units, các chunk còn lại không quá 320. Report và dấu vân tay nguồn ở `data/rag/reports/`
(artifact local, không commit). Vector retrieval chưa tạo.

**BM25 baseline (05/11/2026):** `src/eventrank/rag/bm25.py`, Tantivy 0.27.0, analyzer
`vi_syllable_codes_v1` (NFC + casefold, giữ dấu; âm tiết + mã `57-NQ/TW`/`TP.HCM` nguyên dạng và thành phần).
Không stem/stopword/bỏ dấu; cùng analyzer cho corpus và query; bỏ tiền tố template NER chỉ trên bản index.
96.230 chunk đã index ở `data/rag/bm25/` (~151 MB), bộ ID khớp toàn bộ DB; BM25 ready, Qdrant vẫn pending.
`make rag-bm25` dựng snapshot mới nếu fingerprint/config đổi, giữ snapshot cũ và publish pointer nguyên tử
sau commit/kiểm tra corpus; cùng input thì reuse, không update timestamp lặp. Search CLI:
`make rag-search ARGS='"câu hỏi" --limit 5'`, lọc `--source`, `--date-from`, `--date-to` theo ngày đăng giờ VN.
Chưa tune lexical analyzer hay có số đo chất lượng retrieval; chưa có hybrid/NER boost/cluster expansion
hoặc worker cập nhật index tăng dần. Chi tiết giới hạn và vận hành: `docs/handoff/rag.md`.

**Model services RAG (05/11/2026):** Qwen/Qwen3-Embedding-0.6B và
google/gemma-4-12B-it-qat-w4a16-ct đã deploy trên Modal, cấu hình ghim trong `configs/rag.yaml`.
Smoke query/document embedding đều 1024 chiều, Gemma trả lời câu thử có citation `[1]`;
không coi đây là đánh giá retrieval/grounding. Proxy auth bật ở cả hai endpoint; `.env.client` riêng
cho inference, không chứa token quản trị/R2/DB. Đã kiểm idle về 0 container.
Mốc 06/11/2026: dense Qdrant đủ 96.230 point, cả BM25/Qdrant ready; hybrid RRF,
context selection và pipeline hỏi đáp CLI/API đã có, đã smoke thật với citation/quote kiểm được.
Chưa có đánh giá chất lượng retrieval/grounding hay worker delta. Trạng thái và tiêu chí
trong [kế hoạch RAG](plan-rag.md), lệnh kiểm thử trong [bàn giao](handoff/rag.md).

### 5.3 Hợp đồng dữ liệu lớp Silver

**Luồng crawl local `automation/` (09/11/2026):** đã đăng ký thêm Tuổi Trẻ
(`tuoitre`), Thanh Niên (`thanhnien`), VietnamNet (`vietnamnet`) và VnExpress (`vnexpress`), dùng cùng định dạng file theo bài và bản xuất theo job của bốn
nguồn hiện có; độc lập với kho R2 và tầng ingest Postgres. Bronze giữ HTML
cả trang để không mất JSON-LD/meta. Silver bốn nguồn tuân thủ 9 trường dưới
đây, `source` trùng thư mục (`tuoitre`/`thanhnien`/`vietnamnet`/`vnexpress`), `published_at` có `+07:00`, thiếu tác giả = `null`;
clean_silver cũng giữ `null` khi thiếu tác giả. Nhãn chuyên mục của luồng
automation kế thừa ánh xạ 10 zone từ script cũ (không thay category của dữ liệu
R2). Chi tiết đường dẫn, lịch và giới hạn: [bàn giao Tuổi Trẻ](handoff/crawl-tuoitre.md).
Thanh Niên có selector, đồng tác giả và ngày đăng dự phòng riêng:
[bàn giao Thanh Niên](handoff/crawl-thanhnien.md).
VietnamNet phân trang từ `-page0`, có parser `.html` và JSON-LD riêng:
[bàn giao VietnamNet](handoff/crawl-vietnamnet.md).
VnExpress dùng trang đầu nguyên URL rồi `-p2`, `-p3`; redirect/chặn dừng nguồn:
[bàn giao VnExpress](handoff/crawl-vnexpress.md).

| Trường | Kiểu | Bắt buộc | Quy tắc | Thực tế 19/09 |
|---|---|---|---|---|
| `article_id` | hex 64 ký tự | ✅ | **`sha256(url)`**, khoá duy nhất | 100% |
| `url` | chuỗi | ✅ | bắt đầu `https://` | 100%, không trùng |
| `source` | chuỗi | ✅ | viết thường, không dấu, **trùng tên thư mục** | ⚠️ baochinhphu ghi `BAOCHINHPHU` |
| `category` | chuỗi | ✅ | chuyên mục nguyên văn trên trang báo | 9–10 chuyên mục/báo, 13 tên trên toàn kho |
| `title` | chuỗi | ✅ | bỏ khoảng trắng thừa | 100% |
| `sapo` | chuỗi | ✅ | đoạn tóm tắt đầu bài | 100% |
| `author` | chuỗi \| `null` | — | không có thì `null`, **không ghi chuỗi rỗng** | vietnamnet 100% · nhandan 96,3% · vnexpress 93,4% · baochinhphu 73,6% |
| `published_at` | ISO 8601 | ✅ | **bắt buộc có múi giờ** (`+07:00`) | 100% |
| `content_text` | chuỗi | ✅ | thân bài văn bản thuần | ~99,5–100% |

**Kiểm tra khi ghi vào Postgres** (`src/eventrank/ingest/contract.py`, mọi đường vào DB đều qua đây): `article_id` tính lại
từ `url` và phải khớp; `url` bắt buộc `https://`; `source` viết thường và phải có trong bảng `sources`; `title`, `category`
bắt buộc; `published_at` bắt buộc **có múi giờ** (thiếu/không múi giờ → loại bài, đếm lý do); NFC + bỏ khoảng trắng thừa;
`author` rỗng → `null`. Sapo/thân bài rỗng, bài ngắn, thiếu tác giả, ngày tương lai → **gắn cờ** `quality_flags`
(`missing_sapo`, `no_body`, `short_body` 1–79 từ, `missing_author`, `future_date` > hiện tại 1 giờ), không loại.
⚠ Văn bản trong DB đã NFC: offset NER Gold (tính trên Silver gốc) lệch với 264 trường NFD của kho hiện tại.

**Hợp đồng văn bản RAG:** `article_ner.canonical_text` là đúng văn bản mà offset NER tham chiếu;
entity có `{text,label,start_char,end_char}`, khoảng nửa mở `[start_char,end_char)` theo ký tự Python từ 0.
Importer phải kiểm `canonical_text[start_char:end_char] == entity.text` và tương tự cho chunk, không áp offset
lên `articles.content_text` trực tiếp. `text_hash` của NER không thay thế `articles.content_hash`.
Nội dung/NER đổi → dựng lại chunk và reset trạng thái index trong transaction; worker đồng bộ và dọn point cũ
ở cả hai chỉ mục. Đổi `index_version` → reset cả BM25 và Qdrant về pending; chỉ đặt ready sau khi ghi bền thành công.
Importer NER và chunking đã triển khai ở `src/eventrank/rag/`; worker tự động đồng bộ index chưa có.
Preparation chỉ tự dựng lại chunk cũ khi mọi nhánh index còn pending; đã ready/failed thì dừng để tránh mất
tham chiếu tới point cũ. Importer hiện nhận full snapshot đủ NER cho toàn bộ DB, chưa nhận gói delta riêng.

**Người đọc tự chuẩn hoá** (`src/eventrank/lake/reader.py`, chỉ là lưới an toàn): `source` → thường; `author` rỗng → `null`;
`published_at` nhóm theo **giờ Việt Nam**; tính thêm `n_words`, `title_words`.

**Ngưỡng chất lượng** (tab Chất lượng): thiếu tác giả (`author` null) · thân bài rỗng · thân bài quá ngắn (1–79 từ) · ngày
hỏng · ngày ở tương lai (> hiện tại 1 giờ) · URL / `article_id` trùng.

**Vấn đề đã biết của dữ liệu:**

| Vấn đề | Ảnh hưởng | Cách sửa |
|---|---|---|
| Mỗi chuyên mục bị giới hạn **~500 bài** | Trung vị vài bài/báo/ngày, trong khi báo thật đăng 200–300/ngày → không đủ dày để gom đa nguồn | Crawler cào **theo ngày qua sitemap** |
| Khoảng thời gian lệch (baochinhphu từ 2023, vnexpress từ 20/05/2026) | Chỉ từ 20/05/2026 mới đủ 4 báo | Backfill cùng khoảng cho mọi báo |
| Thư mục lệch tên nguồn (`baodantri` / `baonhandan` chứa `source = nhandan`) | Lọc theo tên thư mục ra 0 bài | Thống nhất thư mục, tên file, trường `source` |
| Tên file khác nhau (`silver_*.jsonl` / `articles_silver.jsonl`) | — | Thống nhất `articles_silver.jsonl` |
| Mỗi báo **một file duy nhất**, cào thêm là ghi đè cả file | Rủi ro mất dữ liệu | Chuyển sang cấu trúc "Hướng tới" |

### 5.4 Lớp Gold: NER (HIỆN TRẠNG)

File `gold_data.jsonl` (93 MB). Mỗi bài trong Silver (6 báo) đã được trích tên riêng ở tiêu đề, sapo, nội dung; mỗi lần
xuất hiện là một thực thể.

**Sáu nhãn:**

| Nhãn | Nghĩa | Ví dụ | Không gồm |
|---|---|---|---|
| `PER` | người | Tô Lâm, Donald Trump, Kim Sang Sik | chức danh, danh xưng |
| `ORG` | tổ chức, cơ quan, doanh nghiệp, đội tuyển/CLB, mã cổ phiếu | Chính phủ, Bộ Y tế, Apple, UBND tỉnh Quảng Ninh | tên chung (`bệnh viện`, `Công an` đứng một mình) |
| `LOC` | quốc gia, tỉnh/thành, địa danh, công trình | Việt Nam, Hà Nội, sân bay Tân Sơn Nhất | |
| `EVENT` | sự kiện có tên: giải đấu, hội nghị, lễ hội, ngày lễ, giải thưởng | ASEAN Cup 2026, Quốc khánh 2/9 | hội thảo, cuộc họp không tên |
| `DOC` | văn bản có số hiệu hoặc tên luật | Nghị quyết số 57-NQ/TW, Bộ luật Hình sự | `Nghị định`, `Luật` đứng một mình |
| `PRODUCT` | sản phẩm, nền tảng số, chỉ số tài chính, tác phẩm | iPhone 18 Pro, Facebook, VNeID, VN-Index | khái niệm chung (`AI`, `5G`) |

Không có nhãn ngày tháng. Cùng một chuỗi có thể đúng ở hai nhãn (`Việt Nam` LOC/ORG đội tuyển); 5.120 chuỗi có > 1 nhãn.

**Trường:** `article_id` (join Silver), `source`, `category` (13 cách viết), `standardized_category` (**nên dùng**, 10
chuyên mục), `published_at` (21 bài trống), `url`, `title`, `entity_count`, `entities[]` = {`text`, `label`, `start_char`,
`end_char`}. Các trường `in_gold`, `gold_split`, `windows`, `dropped`, `rule`, `orig_text`, `orig_label` là ghi chú kỹ thuật,
bỏ qua được. **Gold không có sapo và nội dung** → join Silver theo `article_id`.

**Offset** tính trên văn bản ghép: `Tiêu đề: {title}\n\nSapo: {sapo}\n\nNội dung:\n{content_text}` (khớp 99,26% thực thể;
247 bài, chủ yếu BAOCHINHPHU/NHANDAN, lệch 1–6 ký tự).

**Thống kê:** 28.746 bài · 940.474 thực thể · 149.216 chuỗi khác nhau. Thực thể/bài: trung vị 28, trung bình 32,7, nhiều
nhất 506; 90 bài không có thực thể.

| Nhãn | Lần xuất hiện | Tên khác nhau |
|---|---|---|
| LOC | 315.676 (33,6%) | 27.602 |
| ORG | 290.791 (30,9%) | 50.144 |
| PER | 208.245 (22,1%) | 37.628 |
| PRODUCT | 60.801 (6,5%) | 18.749 |
| EVENT | 44.679 (4,8%) | 14.226 |
| DOC | 20.282 (2,2%) | 6.963 |

| Chuyên mục (`standardized_category`) | Bài | TB thực thể/bài |
|---|---|---|
| Thể Thao | 2.756 | 49,6 |
| Thế Giới | 2.815 | 43,1 |
| Văn Hóa | 2.422 | 37,3 |
| Chính Trị | 2.965 | 36,3 |
| Du Lịch | 2.965 | 34,9 |
| Kinh Tế | 2.912 | 32,8 |
| Khoa học - Công nghệ | 2.925 | 29,6 |
| Pháp Luật | 3.057 | 29,4 |
| Giáo Dục | 2.940 | 23,1 |
| Sức Khỏe | 2.989 | 13,6 |

Tên phổ biến nhất (theo số bài): PER Tô Lâm 1.554, Donald Trump 883; ORG Chính phủ 3.524, Quốc hội 1.667; LOC Việt Nam
8.842, Hà Nội 4.276; EVENT ASEAN Cup 2026 379; DOC Nghị quyết số 57-NQ/TW 268; PRODUCT Facebook 458. 69% tên chỉ xuất hiện
trong 1 bài; 408 tên trong ≥ 100 bài; 20 tên trong ≥ 1.000 bài.

**Độ chính xác NER ~90%** (mẫu 400 bài có nhãn chuẩn: recall ~91%, precision ~90%). PER ~97%, ORG/LOC ~90%, **EVENT ~81%,
DOC ~86%, PRODUCT ~78%**.

**Lưu ý khi dùng để gom cụm:** nhiều cách viết chưa gộp (`Trump`/`Donald Trump`, `TP.HCM`/`TP HCM`/`Thành phố Hồ Chí Minh`,
`Nghị quyết 57`/`…số 57-NQ/TW`); tên quá phổ biến cần trọng số kiểu IDF; tên người một chữ (`Tuấn`) thường là người khác
nhau; báo tự nhắc tên mình (`Tuổi Trẻ` là ORG trong 787 bài, toàn bộ trong bài của Tuổi Trẻ) → bỏ tên tờ báo khỏi thực thể
của chính nó.

### 5.5 Làm sạch NER: kết quả đo trên mẫu 4.000 bài (`ner_gold_cleaned.jsonl`, 24/09/2026)

Mẫu **cân bằng nhân tạo** (667 bài/báo, 400 bài/chuyên mục): chỉ để xây và kiểm thử pipeline, **không dùng để kết luận tần
suất thật**. 102.691 thực thể, 27.074 chuỗi duy nhất.

**Đã sạch, không cần làm lại:** offset đúng 102.691/102.691; `article_id == sha256(url)` 100%; 100% NFC; 0 span chồng lấn,
0 khoảng trắng thừa, 0 trùng URL/id/văn bản; bài nào cũng có ≥ 1 thực thể.

| # | Vấn đề | Đo được | Xử lý |
|---|---|---|---|
| 1 | `source` viết hoa không nhất quán | `NHANDAN`, `BAOCHINHPHU` | `.strip().lower()`, giữ `source_raw` |
| 2 | `standardized_category` **chưa chuẩn hoá gì** | 13 giá trị y hệt `category`, chỉ khác 1/4.000 bản ghi | `configs/section_mapping.yaml` ánh xạ 13 → 10 chuyên mục; đặt tên cột mới `category_std` |
| 3 | **Thiếu `published_at`** trong mẫu này | — | **Chặn cứng** gom cụm và xu hướng → join từ Silver theo `article_id` |
| 4 | Cùng chuỗi nhiều nhãn | 538 chuỗi, 1.653 lần gán thiểu số (`Việt Nam` PER 37 lần) | Bỏ phiếu đa số toàn kho: > 90% ép về nhãn đa số (`label_fixed`); 60–90% gắn `label_ambiguous`; < 60% giữ nguyên. Không ép `Hồ Chí Minh` |
| 5 | Biến thể cách viết | 674 nhóm; TP.HCM có 7 cách viết, ~1.505 lần | Khoá tự động (`lower`, bỏ dấu chấm, gộp khoảng trắng) + bảng `configs/entity_aliases.yaml` → cột `text_norm`, giữ `text` gốc |
| 6 | DOC bị nhiễm | 2.090/3.966 (53%) không phải văn bản (`BHYT`, `USD`, `VN-Index`, `2030`…) | Regex `LEGAL` (Nghị định, Thông tư, Quyết định, Luật, Nghị quyết, Chỉ thị, Bộ luật, Pháp lệnh, Hiến pháp, Đề án) hoặc `NUMBERED` (`\d+/\d{2,4}`, `số \d+`): giữ ~1.876. DOC đúng là **tín hiệu gom cụm mạnh nhất** |
| 7 | PRODUCT lẫn công nghệ/chính sách; EVENT là sự kiện **có tên, lặp chu kỳ** (gần như toàn thể thao) | PRODUCT 8.749 lần; EVENT 5.562 lần | Hạ trọng số qua IDF (df > 5% → ~0). **Nhãn EVENT không phát hiện sự kiện tin tức**, đó là việc của gom cụm |
| phụ | Span dài lỗi biên | 539 span > 60 ký tự; 176/18.979 PER dính chức danh | Regex cắt chức danh (`boundary_fixed`); span > 60 ký tự gắn `long_span`, không tự sửa |

Ký tự cong và zero-width (16) giữ nguyên trong `full_text` (đổi là lệch offset); chỉ chuẩn hoá trong bản sao để so khớp.
4 cặp tiêu đề trùng, cả 4 giữa hai báo khác nhau (bản tin đăng lại).

**Thứ tự làm sạch:** Pha 0 lấy `published_at` (chặn) → Pha 1 mức bản ghi (`source`, `category_std`, tách `full_text`) → Pha 2
mức thực thể (lọc DOC, cắt chức danh, `long_span`, `text_norm`) → Pha 3 toàn kho (bỏ phiếu nhãn, df/idf, khử trùng lặp).
Pha 2 trước 3.1 vì DOC rác làm nhiễu phiếu; `text_norm` trước idf để `TP.HCM`/`TPHCM` không bị đếm là hai thực thể.

**Schema đầu ra Gold đề xuất:** `gold/articles/v=<pipeline_version>/source=<báo>/dt=<ngày>/part-*.parquet` (thêm
`source_raw`, `category_std`, `published_at`, `published_date_vn`, `flags`, `is_canonical`, `dup_group_id`, `dup_count`,
`dup_sources`); `gold/entities/` (giữ `text`, `start_char`, `end_char`; thêm `label` sau bỏ phiếu, `label_raw`,
`text_norm`, `fixed`); `gold/entity_stats/` (`df`, `n_docs`, `idf`, `is_stopword` = df > 5%). **Không ghi `idf` vào bản ghi
bài** vì nó đổi khi kho dày thêm.

**Kiểm chứng sau mỗi pha:** 100% bài có `published_at`; đúng 6 `source` viết thường; đúng 10 `category_std`; xem tay 30 DOC bị
loại + 30 được giữ (loại nhầm < 5%); nhóm TP.HCM gộp ≥ 1.250/1.505; top 50 `is_stopword` chứa Việt Nam, Hà Nội, AI, USD. Chạy
lại toàn bộ kiểm tra ở mức ký tự sau khi làm sạch.

### 5.6 Kế hoạch tiền xử lý Silver → Gold (KẾ HOẠCH, đo thời gian 19/09/2026)

Nguyên tắc: không sửa Silver; chạy lại cho cùng kết quả (`pipeline_version`); đánh dấu, không xoá.

| Bước | Việc | Ghi chú |
|---|---|---|
| 1 | Chuẩn hoá văn bản: NFC, gộp khoảng trắng, bỏ ký tự điều khiển, nháy cong → thẳng, giải mã HTML entity | `unicodedata` |
| 2 | Chuẩn hoá trường: `source`, `category_std` (bảng ánh xạ có phiên bản), `published_date_vn`, `published_hour_vn`, `author` rỗng → null | |
| 3 | Gắn cờ: `missing_author`, `empty_content`, `short_content` (< 80 từ), `bad_date`, `future_date`, `likely_video`, `likely_pr`, `out_of_window` (trước 20/05/2026) | |
| 4 | Khử trùng: tuyệt đối theo `article_id`; **gần trùng** MinHash + LSH trên 5-gram `title + sapo`, Jaccard ~0,8 → `dup_group_id` | `datasketch` |
| 5 | Tách câu, tách từ → `title_seg`, `sapo_seg`, `body_seg` | `underthesea`: 15 ms/bài → **4,4 phút** cả kho. **Chốt MỘT bộ tách từ** cho cả dự án |
| 6 | Trích thực thể **chỉ trên tiêu đề + sapo + 3 câu đầu** | Toàn bài 909 ms/bài (4,6 giờ) vs đầu bài 8 ms (2,3 phút), nhanh 121 lần. **Phải gán tay 100 câu đo NER trước** |
| 7 | Chuẩn hoá ngày trong văn bản ("Chiều 10.9", "sáng qua", "tối 14/9") về ngày tuyệt đối → `event_date` | Thanh Niên dùng dấu chấm, báo khác dùng gạch chéo |
| 8 | Đặc trưng: `lead_text` (tiêu đề + sapo + 3 câu đầu), `n_words`, `title_words`, `numbers`, `entity_idf` | |

Tổng ~**12–15 phút** cho cả kho. Cấu trúc code đề xuất: `src/eventrank/preprocess/{text,fields,flags,dedup,segment,entities,dates,pipeline}.py`,
`jobs/build_gold.py`, `configs/section_mapping.yaml`, `configs/entity_aliases.yaml`, lệnh `make gold`. Quy tắc: **bước nào chưa
đạt thì không chạy bước sau.**

Sáu quyết định cần chốt: tên nguồn `baodantri` hay `nhandan`; bộ tách từ (`underthesea`); taxonomy chuyên mục; ngưỡng gần
trùng (0,8); nguồn NER; giữ và gắn cờ bài trước 20/05/2026.

---

## 6. Thiết kế data lake (kế hoạch ban đầu và hạ tầng cloud)

> Phần này là **thiết kế và hướng dẫn** viết ngày 15–16/09/2026. Kho thực tế hiện nay đơn giản hơn (mục 5.2): chưa có
> Bronze, Silver là JSONL thay vì Parquet, bucket tên `vietnam-news-datalake` thay vì `event-lake`.

### 6.1 Nguyên tắc của kho

| Nguyên tắc | Nghĩa là |
|---|---|
| **Bronze bất biến** | Không sửa, không xoá; cào lại là file mới; parser mới chạy lại trên Bronze cũ |
| **Idempotent** | Chạy lại cho cùng kết quả, không tạo bản ghi trùng (`url_hash` làm khoá, `INSERT … ON CONFLICT`) |
| **Đánh dấu, không xoá** | Bài ngắn, video, gần trùng đều gắn cờ; bước sau tự lọc |
| **Phiên bản hoá logic** | Đổi parser → tăng `parser_version` → chạy lại → so được hai phiên bản |

### 6.2 Stack đề xuất

Python 3.12 + `uv`; `httpx` (async) + `tenacity` (retry); `feedparser` (RSS); `lxml` với `resolve_entities=False` (chống
XXE); `protego` (`robots.txt` có wildcard); tách bài **JSON-LD → meta → `trafilatura`**; Bronze `.html.gz` (349 KB → 70 KB;
50k bài ≈ 3,5 GB); PostgreSQL 16 (`pgvector/pgvector:pg16`); Parquet + DuckDB cho snapshot; `datasketch` (MinHash LSH);
`typer` (CLI); APScheduler hoặc cron (**không Airflow**); file SQL đánh số; `pytest` với HTML mẫu (không Great Expectations);
Docker Compose; cảnh báo Telegram; sao lưu `pg_dump` + `rclone`. **Không dùng Scrapy** (VnExpress chặn đích danh).
User-Agent trung thực: `PBL-EventLake/0.1 (nghien cuu sinh vien; +mailto:<email-cua-nhom>)`.

### 6.3 Luồng và bố cục

```
sitemap lịch sử / RSS (5') / "Xem nhiều" (1h) ─► url_frontier ─► fetcher (throttle theo domain) ─► .html.gz + bronze_objects
  ─► parser (JSON-LD → meta → trafilatura) ─► NFC, múi giờ, content_type ─► quality_flags ─► dedup URL + MinHash
  ─► ánh xạ chuyên mục ─► silver_articles ─► SNAPSHOT Parquet (nhóm ML) / GOLD (entities, weak_pairs, embeddings)
```

Bronze: `bronze/articles/source=<báo>/dt=<ngày CÀO>/<url_hash>__<timestamp>.html.gz` (cùng kiểu cho `sitemaps/`, `rss/`,
`most_read/…/hour=<h>/`). `dt` là **ngày cào**, không phải ngày đăng.

Bảng Postgres đề xuất: `sources`, `url_frontier` (trạng thái `pending/fetching/fetched/failed/skipped`, lấy việc bằng
`FOR UPDATE SKIP LOCKED`, gỡ kẹt sau 30 phút), `bronze_objects`, `silver_articles` (có `section_raw`, `section_std`,
`content_type`, `quality_flags`, `dup_group_id`, `parser_version`), `section_mapping`, `pipeline_runs`,
`most_read_snapshots`; Gold: `gold_entities`, `gold_embeddings` (`vector(768)`), `gold_weak_pairs`.

### 6.4 Các bước dựng kho (ước 2 tuần, 1–2 người)

| Bước | Việc | Hoàn thành khi |
|---|---|---|
| 0 | Chốt phạm vi: 4 báo backfill + VnExpress chỉ RSS; backfill **01/06–31/07/2026**; trường bắt buộc `title`, `published_at`, `url`, `source` | Có `config/sources.yaml` |
| 1 | Dựng repo, database | `docker compose up` có đủ bảng |
| 2 | `lake survey`: đọc robots, sitemap, **báo lỗi nếu nhận HTML thay vì XML**; chạy hằng tuần | Bảng `sources` đủ 5 dòng |
| 3 | Đưa URL vào hàng đợi: sitemap (lọc theo **tên file**), RSS 5–10 phút (ETag), "Xem nhiều" mỗi giờ (bắt đầu sớm, không lấy lại được) | ~50–60k URL, không ngày nào bằng 0 |
| 4 | Tải Bronze: **≥ 2 giây/request/domain**, backoff khi 429/5xx, dừng domain khi 403 liên tiếp, ghi nguyên tử | ≥ 97% `fetched`; ~3–4 GB; ~7–8 giờ/domain, 4 domain song song = 1 đêm |
| 5 | Tách bài Bronze → Silver; test 5 bài mẫu/báo | ≥ 98% có `title` + `published_at`; ≥ 95% có `section_raw` |
| 6 | Chuẩn hoá, gắn cờ (`missing_sapo`, `short_body` < 80 từ, `no_body`, `future_date`, `naive_datetime`…) | Không còn ngày tương lai chưa gắn cờ |
| 7 | Khử trùng: URL (loại), byte (không tạo bản mới), gần trùng MinHash 5-shingle `title + body`, LSH ~0,8 (**chỉ đánh dấu**) | Kiểm tay 20 nhóm đúng |
| 8 | Bảng ánh xạ ~10–12 chuyên mục chuẩn | ≥ 95% bài khác "Khác" |
| 9 | Lịch chạy, giám sát, sao lưu (cảnh báo khi một báo không có bài mới 2 giờ ban ngày; < 50% trung vị 7 ngày; > 5% thiếu trường) | Tắt crawler 2 giờ có cảnh báo; khôi phục sao lưu thành công |
| 10 | Báo cáo chất lượng + snapshot `articles_v1` + `MANIFEST.json` | Nhóm ML đọc được bằng DuckDB |
| 11 | Khung bảng Gold rỗng | Bàn giao |

### 6.5 Mười cái bẫy đã thấy trong dữ liệu thật

1. VnExpress trả **302 về trang chủ** cho sitemap → code phải ném lỗi khi không thấy XML, nếu không VnExpress âm thầm biến mất.
2. Chỉ mục Dân Trí dừng ở **7/2026** (tháng 9 trả 404).
3. `lastmod` của Tuổi Trẻ là **2011-01-01**.
4. VietnamNet chia sitemap thành **phần 1.000 URL**.
5. **BOM** đầu sitemap Dân Trí.
6. **NFC vs NFD**: không chuẩn hoá thì băm, so trùng, tách từ đều hỏng.
7. Bài **cập nhật sau khi đăng**: giữ `published_at` gốc, cập nhật `modified_at`.
8. Thanh Niên viết ngày kiểu **"10.9"**.
9. Trang **video, ảnh, trực tiếp** lẫn trong sitemap.
10. **Crawler chết âm thầm**: RSS không lấy lại được quá khứ → cảnh báo theo từng báo.

### 6.6 Hạ tầng cloud: Cloudflare R2

**Vì sao R2:** không tính phí tải ra (egress); 10 GB miễn phí; tương thích S3 (DuckDB, boto3, pandas đều dùng được); phân quyền
theo từng khoá. ⚠️ **Bắt buộc có thẻ tín dụng / PayPal để kích hoạt**, kể cả khi dùng trong hạn mức miễn phí.

| Phương án bị loại | Lý do |
|---|---|
| Supabase làm cả lake | Gói miễn phí chỉ 500 MB; dự án tạm dừng nếu 7 ngày không truy vấn |
| Postgres trên VPS mở cổng | Tự sao lưu, tự vá; **không bao giờ mở cổng 5432 ra Internet** |
| Google Drive | Không truy vấn trực tiếp, lẫn phiên bản |
| Lưu trong GitHub | Giới hạn kích thước, đưa nội dung có bản quyền lên nơi dễ công khai |
| DigitalOcean credit sinh viên | **Đã ngừng từ 01/08/2026** |

Nếu cần SQL dùng chung: Postgres trên máy crawler + **Tailscale** (gói Personal miễn phí 6 người dùng). Không có thẻ: nhờ
người có thẻ kích hoạt R2; Azure for Students ($100, tính phí egress); Postgres + Tailscale; Backblaze B2 / HF private
dataset (kiểm tra điều kiện trước).

**Khoá:** mỗi khoá **Apply to specific buckets only**. Máy crawler giữ khoá **Object Read & Write** (`crawler-rw`); mỗi thành
viên một khoá **Object Read only** (`<tên>-ro`). Secret chỉ hiện một lần. **Không dùng Global API Key.** Bucket **private**,
không bật public access, không bật `r2.dev`. Kiểm tra phân quyền: dùng khoá chỉ đọc thử ghi, **phải bị từ chối**.

**Chi phí ước lượng:** backfill Bronze ~3,5 GB + Silver Parquet 0,3–0,5 GB (trong 10 GB); tăng ~1.000–1.500 bài/ngày × 70 KB
≈ **+2 GB/tháng** (vượt 10 GB sau ~3 tháng); Class A (ghi/liệt kê) miễn phí 1 triệu/tháng, Class B (đọc) 10 triệu/tháng;
vượt thì $0,015/GB/tháng (15 GB ≈ $0,08 ≈ 2.000đ/tháng).

**Đọc dữ liệu:** DuckDB `httpfs` + `CREATE SECRET (TYPE r2, KEY_ID, SECRET, ACCOUNT_ID)`; bí mật loại r2 chỉ dùng với đường dẫn
`r2://`. Colab: Secrets (`google.colab.userdata`); Kaggle: Add-ons → Secrets (`kaggle_secrets.UserSecretsClient`). **Không
dán khoá vào notebook.** Truy vấn nhiều lần thì tải về máy một lần (R2 không tính phí tải ra).

**Runbook (16/09/2026)** đã chạy thật: backend `local` trước, đổi `LAKE_BACKEND=r2` để chuyển lên R2, không sửa code. Lát cắt
Thanh Niên: `lake.cli discover` thấy 1.407 URL; tải 12 bài, 0 lỗi; 12/12 đủ tiêu đề, ngày, chuyên mục; trung vị 598 từ.
`scripts/check_r2.py` kiểm tra ghi/đọc. Chạy định kỳ bằng cron `*/10` + `flock`. Xử lý sự cố: `ValueError: không phải sitemap
XML` → báo đó dùng RSS; nhiều `failed` → tăng `--delay` lên 3–5 giây; `AccessDenied` → đang dùng khoá chỉ đọc; `NoSuchBucket`
→ sai tên bucket hoặc Account ID.

**An toàn và pháp lý:** nội dung báo có bản quyền, chỉ dùng nội bộ; sản phẩm chỉ hiện tên sự kiện, tiêu đề, link gốc; snapshot
đưa người ngoài chỉ gồm metadata và tiêu đề; sao lưu Bronze sang nơi thứ hai hằng tuần.

---

## 7. Nhãn yếu "cặp cùng sự kiện"

Mã: `src/eventrank/weak_labels/`. Lệnh: `make embed`, `make weak-labels`. Người làm: Nguyễn Đình Hiếu (cùng Claude Code).

### 7.1 Kết quả các phiên bản (số mới nhất, đo có trọng số theo tầng)

| Phiên bản | Ngày | Precision cặp dương | Recall | Bộ ba train | Ghi chú |
|---|---|---|---|---|---|
| v1 (p ≥ 0,85) | 01/10 | 0,81 [0,74; 0,87] | 0,57 [0,47; 0,71] | 10.005 | Trên R2 `weak_label_NguyenDinhHieu/`. Negative khó **sai ≥ 29%**, không nên dùng |
| v2 (p ≥ 0,8) | 02/10 | 0,93 [0,88; 0,98] | 0,20 [0,16; 0,25] | 4.051 | Sạch nhưng recall thấp |
| **v3 lõi (p ≥ 0,8)** | 04/10 | **0,93** [0,85; 0,98] | **0,28** [0,22; 0,37] | **5.381** | **Hiện tại.** Thêm tín hiệu ngữ nghĩa (MiniLM). 90% bộ ba khác báo |
| v3 mở rộng (p ≥ 0,6) | 04/10 | 0,83 [0,75; 0,90] | 0,43 [0,35; 0,54] | 7.596 | Phần thêm chỉ đúng 0,69 → chỉ dùng làm thí nghiệm |

Đo bằng **Claude gán mù** trên mẫu holdout độc lập `v2/audit_labeled_llm.csv` (400 cặp), precision/recall **có trọng số theo
tầng** (Horvitz–Thompson, `evaluate.py`), CI 95% bootstrap. Negative khó v3 sai **2%** [0; 5%]. Recall là **recall trong tập
ứng viên**: cặp không bao giờ thành ứng viên thì không đo được.

**Dùng để train:** `data/weak_labels/v3/train_triplets.jsonl`.

### 7.2 Pipeline

```
gold (NER cả bài) + silver (văn bản) ─► chuẩn hoá thực thể ─► sinh cặp ứng viên ─► đặc trưng
  ─► 8 LF bỏ phiếu ─► label model (Dawid–Skene/EM) ─► chặn + phủ quyết ─► hiệu chỉnh isotonic ─► áp lại chốt chặn ─► p
  ─► chọn bộ ba (anchor, positive, negative khó) ─► train_triplets.jsonl
```

**Mô hình embedding chỉ đọc `tiêu đề + ". " + sapo`.** Thực thể và điểm số chỉ dùng để quyết định nhãn.

**Đầu vào:** Gold 28.746 bài join Silver theo `article_id` (khớp 100%), bỏ 21 bài không có `published_at` → **28.725 bài**.

### 7.3 Bước 1: chuẩn hoá thực thể và độ nổi bật (`entities.py`)

`EntityNormalizer.norm(text, label)`: cắt dấu câu hai đầu → bỏ rác (không có chữ cái / < 2 ký tự, **trừ `Ý`, `Á`**) → bỏ từ
chung đứng một mình (không áp cho PER) → bỏ mảnh từ viết thường chỉ khi là âm tiết tiếng Việt → DOC gộp theo loại + số hiệu
(`nghịquyết57`) → khoá tự động (NFC, thường, bỏ dấu chấm/gạch nối/khoảng trắng) → bảng alias `configs/entity_aliases.yaml` →
LOC bỏ tiền tố hành chính (cả `đặc khu`; bỏ cấp hành chính giữa tên cơ quan: "Sở Y tế tỉnh Gia Lai" = "Sở Y tế Gia Lai").
Alias **trước** bỏ tiền tố, để "Thành phố Hồ Chí Minh" không trùng tên người. 149.216 chuỗi → 131.992 thực thể chuẩn hoá. Đo
trên Gold có 9.558 nhóm cách viết, 405 nghìn lần nhắc.

- **Bỏ tên của chính tờ báo** (`SELF_NAMES`): `Tuổi Trẻ` có trong 942 bài, 97% là bài của chính Tuổi Trẻ.
- **Nối tên một chữ với tên đầy đủ trong cùng bài** ("Nguyễn Văn Tuấn … ông Tuấn"); tên một chữ là 33% số PER.
- **Độ nổi bật:** vùng tiêu đề 3,0 · sapo 2,0 · đoạn đầu (800 ký tự) 1,2 · thân 0,6.
  `salience = trọng_số_vùng_tốt_nhất × (1 + 0,5 × ln(số_lần_nhắc))`, × 0,2 nếu tên người một chữ (chưa nối được).

### 7.4 Bước 2–4: IDF, ứng viên, đặc trưng (`corpus.py`, `pairs.py`)

- `idf(e) = ln(N/df)`; = 0 nếu df = 1 hoặc df > 2%·N (~575 bài: Việt Nam, Hà Nội, Chính phủ, Mỹ, Tô Lâm). `weight = salience × idf`.
- **Bài đăng lại:** cùng tiêu đề, hoặc cùng sapo ≥ 80 ký tự → chung `dup_group`. Không xoá, nhưng **không đưa vào train** (quá dễ).
- **Ứng viên** (đều trong ±7 ngày; so mọi cặp là ~412 triệu):

| Nguồn | Cách làm | v1 | v3 |
|---|---|---|---|
| Thực thể | chỉ mục ngược; thực thể idf > 0 và nổi bật; bỏ thực thể > 400 bài; mỗi bài giữ top 20 | 273.898 | 265.831 |
| TF-IDF | 10 láng giềng gần nhất (unigram + bigram âm tiết, `sublinear_tf`, `max_df=0,3`), cos > 0,15 | 66.907 | 66.907 |
| Ngẫu nhiên | 1 cặp/bài trong ±24h | 27.999 | 27.978 |
| Ngữ nghĩa (v3) | MiniLM, cos ≥ 0,6, top 10 | — | 97.218 |
| Ép thêm cặp audit | `--force-pairs` | — | 799 |
| **Hợp** | | 327.230 | **375.347** |

- **Đặc trưng:** `ent_score` (Σ min trọng số thực thể chung), `ent_wjacc` (ent_score / Σ max trên hợp), `n_head_shared` (thực thể
  hiếm df ≤ 200 ở tiêu đề/sapo của cả hai), `cos_head` (TF-IDF tiêu đề + sapo), `cos_lead` (+ 600 ký tự đầu), `n_numbers` (con
  số kèm đơn vị trùng: "150 người", "2,5 tỷ"), `date_conflict` (hai tiêu đề ghi ngày khác nhau, trừ ngày lễ và tỉ số),
  `dt_hours`, `cross_source`, `same_category`, `same_dup`, `cos_dense` (v3), `conflict_doc/org/per/event/loc`.

### 7.5 Bước 5–6: hàm gán nhãn và label model (`lfs.py`, `label_model.py`)

Mọi phiếu dương đòi hai bài cách nhau **≤ 72 giờ** (`POS_MAX_HOURS`).

| LF | Phiếu dương | Phiếu âm | Độ phủ (v2) |
|---|---|---|---|
| `lf_repost` | cùng nhóm đăng lại | — | 0,06% |
| `lf_entity_overlap` | `ent_wjacc` ≥ 0,30 và `ent_score` ≥ 10 | `ent_wjacc` < 0,04 | 40,6% |
| `lf_head_entities` | `n_head_shared` ≥ 2 | — | 2,6% |
| `lf_lexical` (v2 gộp từ `lf_tfidf_head` + `lf_tfidf_lead`, vốn bỏ phiếu giống nhau 75%) | cos cao | cos thấp | 51,3% |
| `lf_shared_number` | `n_numbers` ≥ 1 và `ent_score` ≥ 3 | — | 0,45% |
| `lf_dense` (v3) | cos ngữ nghĩa ≥ 0,80 | < 0,30 | 38,3% (v3) |
| `lf_time_far` | — | `dt_hours` > 72 | 44,1% |
| `lf_category_mismatch` | — | khác chuyên mục và `ent_wjacc` < 0,12 | 40,1% |

Ngưỡng v1 của hai LF TF-IDF: `cos_head` ≥ 0,45 / < 0,06; `cos_lead` ≥ 0,40 / < 0,08.

**Nguyên tắc:** "cùng chuyên mục" không bao giờ là phiếu dương; mỗi LF một loại bằng chứng (thực thể, từ vựng, con số, thời
gian, chuyên mục, ngữ nghĩa).

**Label model:** Dawid–Skene nhị phân bằng EM, viết lại bằng numpy (77 dòng, không cần PyTorch); một LF im lặng cũng là thông
tin. **Prior cố định 0,10** (9,0% cặp có ≥ 1 phiếu dương); **không có phiếu dương → p ≤ 0,5**.

**Luật sau label model:**
- **Phủ quyết** (`veto_dated_series`): hai tiêu đề ghi ngày khác nhau → p = 0,02. `veto_title_doc` (v2): mỗi tiêu đề có một
  văn bản DOC mà bài kia không nhắc.
- **Cổng nhóm bằng chứng** (`gate`, v2): cặp **cùng báo** cần ≥ 2 nhóm bằng chứng (thực thể / từ vựng / con số / ngữ nghĩa),
  nếu không p bị chặn ở 0,5. Đo trên 399 cặp chỉnh: cùng báo 1 nhóm đúng 0,57, ≥ 2 nhóm 0,86; khác báo 1 nhóm đã 0,82. Bài
  đăng lại: 1 bằng chứng là đủ.
- **Ngữ nghĩa không được là bằng chứng dương duy nhất** (v3): 45 cặp chỉ có phiếu ngữ nghĩa đúng 58%; có thêm thực thể/từ vựng 47/50.
- **Hiệu chỉnh** (v2): isotonic regression, tách cùng báo / khác báo, fit trên 399 cặp v1 có nhãn Claude. Sau đó p đọc gần
  như "tỉ lệ đúng".
- **Áp lại chốt chặn sau hiệu chỉnh** (`finalize`, v3): isotonic ánh xạ 0,5 → 0,68 làm 1.796 cặp "chỉ ngữ nghĩa" lọt lại.

### 7.6 Bước 7: chia dữ liệu và chọn dữ liệu train (`build.py`)

```
──── train (< 11/9/2026) ────┤ gap 48h ├──── holdout (≥ 13/9/2026) ────
         23.391 bài              1.458 bài          3.876 bài
```

Chỉ cặp có **cả hai bài thuộc train** vào file train; cặp holdout dành cho audit; cặp vắt qua hai vùng (`mixed`) bị bỏ.

- **Positive:** p ≥ 0,8 (đã hiệu chỉnh), không phải bài đăng lại, tối đa **3 positive / anchor**.
- **Negative khó:** giống anchor nhất (theo `cos_dense`, nếu thiếu thì `cos_lead`) nhưng: p ≤ 0,10; **khác cả từ vựng (`cos_lead`
  < 0,15) lẫn thực thể (`ent_wjacc` < 0,10)**; khác nghĩa (cos ngữ nghĩa < 0,55, v3); độ giống anchor < 95% độ giống của
  positive (`neg_margin`, kiểu TopK-PercPos của NV-Retriever); không nối với anchor/positive qua bài trung gian (A~X~C).
- **`train_pairs`:** mọi cặp dương + tối đa 3 cặp âm cho mỗi cặp dương (nửa khó nhất, nửa ngẫu nhiên); `label` = 1 nếu p ≥ 0,8.

**Negative khó, đo trực tiếp ở v2** (Claude gán 3 vòng × 100 cặp):

| Vòng | Quy tắc | Negative thực ra cùng sự kiện |
|---|---|---|
| 1 | chỉ p thấp | **29/100** (gần như chỉ có phiếu âm `lf_time_far`; tin tiếp nối nhiều ngày) |
| 2 | + khác nội dung theo **một** tiêu chí (cos < 0,15 **hoặc** wjacc < 0,04) | 12/100 |
| 3 | + khác theo **cả hai** (cos < 0,15 **và** wjacc < 0,10) | **2/100** |

### 7.7 File đầu ra (`data/weak_labels/v<n>/`)

| File | v1 | v2 | v3 | Nội dung |
|---|---|---|---|---|
| `train_triplets.jsonl` | 10.005 | 4.051 | **5.381** | `anchor`, `positive`, `negative` (+ `*_id`, `p`); dùng `MultipleNegativesRankingLoss` / `GISTEmbedLoss` |
| `train_triplets_extended.jsonl` | — | — | 7.596 | p ≥ 0,6, cột `tier` = core/extended |
| `train_pairs.jsonl` | 177.499 | 18.312 | **25.836** | `a`, `b`, `label`, `score` = p; dùng `CoSENTLoss` / `AnglELoss` |
| `pairs.jsonl` | 327.230 | 319.098 | 375.347 | mọi cặp ứng viên: `p`, `p_raw`, `n_pos_families`, `vetoed`, `votes`, đặc trưng, `split` |
| `articles.jsonl` | 28.725 | 28.725 | 28.725 | `article_id`, `source`, `category`, `published_at`, `split`, `dup_group`, `text` (= tiêu đề + ". " + sapo) |
| `audit_sample.csv` + `audit_ids.csv` | 400 | 400 | 400 | mẫu audit holdout (cột `label_human` để trống) |
| `report.json` | ✓ | ✓ | ✓ | thống kê + tham số |

Số cặp dương (p ≥ 0,8) trong v2: 6.804 tổng, 80,6% khác báo; 4.578 thuộc train trong `train_pairs`. Trong v3: 9.547 tổng;
6.459 dương trong `train_pairs`.

**Đọc nhãn:** p ≥ 0,80 dương; p ≤ 0,10 âm; ở giữa không dùng; p = 0,5 kèm `votes = {}` là không có bằng chứng; p = 0,02 là bị
phủ quyết. Nếu dùng e5, tự thêm tiền tố `query: `.

### 7.8 Đánh giá nhãn yếu

| Tập | Dùng để | Kích thước |
|---|---|---|
| `v1/audit_labeled_llm_ids.csv` | **tập chỉnh**: chọn luật, hiệu chỉnh p | 399 |
| `v2/audit_labeled_llm.csv` + `audit_ids.csv` | **tập đo** (holdout), không dùng để chỉnh | 400 |
| `v2/negative_check_llm.csv` | 3 vòng kiểm negative | 300 |
| `v3/check_llm.csv`, `v3/check_extended_llm.csv` | dương mới, tầng mở rộng | — |
| `v1/human_label_100.csv` | 100 cặp chờ **người** gán để đo κ (17 cặp Claude độ tin thấp + 83 cặp lấy đều) | 100 |

Mẫu audit: phân tầng **4 khoảng p × (cùng/khác báo) × 50 cặp**, lấy từ holdout. **Gán bằng Claude:** gán mù (bỏ `p`), 8
subagent song song, mỗi cụm 50 cặp, cùng một hướng dẫn, chỉ đọc; trả `label` (1/0/?), `confidence`, `reason`. Ở v1: 113 cặp 1,
287 cặp 0; 294 độ tin cao, 89 trung bình, 17 thấp.

**Tỉ lệ thô trên mẫu phân tầng KHÔNG phải precision/recall thật** (recall thô v2 0,52, thật 0,20): luôn dùng `evaluate.py`.

Kết quả thô theo tầng (để tham khảo):

| p | v1 (audit v1) cùng báo / khác báo / tất cả | v2 (audit v2) cùng báo / khác báo / tất cả |
|---|---|---|
| 0,00–0,10 | 0,02 / 0,02 / 0,02 | 0,02 / 0,02 / 0,02 |
| 0,10–0,50 | 0,14 / 0,16 / 0,15 | 0,12 / 0,16 / 0,14 |
| 0,50–0,85 (v1) · 0,50–0,80 (v2) | 0,20 / 0,38 / 0,29 | 0,59 / 0,76 / 0,68 |
| 0,85–1,00 (v1) · 0,80–1,00 (v2) | **0,54 / 0,80 / 0,67** | **0,82 / 0,96 / 0,89** |

**Lỗi dương còn lại:** chuỗi bài một báo về các trận khác nhau cùng giải; "Lịch thi đấu 13/9" vs "Kết quả 13/9"; hai nghị quyết
không có số hiệu trong tiêu đề; ở tầng mở rộng: **các diễn biến khác nhau của một câu chuyện lớn** (câu hỏi định nghĩa). **Lỗi
bỏ sót:** cặp cùng sự kiện viết khác nhau (dự thảo quy chế tuyển sinh, vụ cháy Tây Hồ, ngập Hà Nội, chuyến thăm của Nhà vua Thái Lan).

**Giới hạn:** nhãn đối chiếu là của Claude (chưa phải người; κ ≥ 0,7 thì mới dùng nhãn LLM thay người); hiệu chỉnh dựa trên ~45
cặp dương mỗi nhóm; sự kiện nhiều ngày bị cắt bởi giới hạn 72h.

### 7.9 Lỗi lớn đã gặp và cách sửa

| Lỗi | Sửa |
|---|---|
| EM tự học prior 0,444 → 124.049 cặp p ≥ 0,85, trong đó 94.519 cặp **không có phiếu dương nào** (LF âm một chiều cùng im lặng) | Prior cố định 0,10 + "không phiếu dương → p ≤ 0,5". Kết quả không nhạy với prior (0,05–0,20) |
| "Giá Bitcoin hôm nay 8.9" ↔ "7.9": LF "khác ngày" bị label model ước chỉ đúng 0,31 vì luôn mâu thuẫn TF-IDF | Chuyển thành **luật phủ quyết** sau label model |
| Regex ngày lễ có chữ `ngày` → "Giá vàng **ngày** 16/9" lọt phủ quyết | Bỏ `ngày` khỏi `_HOLIDAY` |
| Negative chỉ dựa "cách > 72h": 29% sai | Đòi khác cả từ vựng lẫn thực thể (2%) |
| Audit v1 ghép với id bằng tiêu đề, lúc đầu sai một nửa | Thêm `audit_ids.csv`; tra cặp bằng `frozenset((a, b))` |

Đã thử và **không** đưa vào: đòi ≥ 2 nhóm cho **mọi** cặp (precision 0,89 nhưng chỉ giữ 15% dương thật); phủ quyết khi
ORG/PER/EVENT/LOC ở tiêu đề khác nhau (không đổi kết quả); nới ngưỡng thực thể/từ vựng (precision giảm còn 0,63–0,67).

### 7.10 Quyết định thiết kế quan trọng

Mô hình ngữ nghĩa dùng cho nhãn (MiniLM) **khác họ** với mô hình sẽ fine-tune (PhoBERT/e5) để tránh học vòng tròn. Chia train /
gap 48h / holdout theo thời gian. Gán bằng LLM ban đầu **chỉ dùng để đo**, không tạo dữ liệu train.

### 7.11 Chạy lại

```bash
make embed          # MiniLM ONNX int8 (~135 MB lần đầu), nhúng ~9 phút CPU → data/weak_labels/cache/*.npz
make weak-labels    # ~2,5 phút → data/weak_labels/v3/
uv run --group embed python -m eventrank.weak_labels.evaluate --system v3=data/weak_labels/v3/pairs.jsonl
uv run --group embed pytest tests/weak_labels -q    # 45+ test, mọi luật có test kèm bằng chứng
make agreement      # κ người ↔ Claude sau khi gán human_label_100.csv
```

**Tham số v3:** `--window-hours 168 --holdout-start 2026-09-13 --gap-hours 48 --prior 0.10 --pos-threshold 0.80
--ext-threshold 0.60 --neg-threshold 0.10 --max-pos-per-anchor 3 --neg-ratio 3 --neg-margin 0.95 --dense-pos 0.80
--dense-neg 0.30 --neg-max-dense 0.55 --min-families 1 --min-families-same-source 2 --calibration
data/weak_labels/v1/audit_labeled_llm_ids.csv --force-pairs data/weak_labels/v2/audit_ids.csv --seed 29`.

Đổi sang `bge-m3`: `make embed EMBED_MODEL=Xenova/bge-m3` (~590 MB), **phải chỉnh lại `--dense-pos/--dense-neg`** trên tập
chỉnh (thang cosine mỗi mô hình khác nhau). Lần tải bge-m3 bản đầy đủ (2,3 GB) từng thất bại vì mạng ~0,2 MB/s; có thể chạy
trên Kaggle/Colab rồi chỉ chép file `.npz` (~60 MB) về.

### 7.12 Cạm bẫy

1. **Không chỉnh ngưỡng trên tập đo.** Chỉnh trên tập chỉnh (v1), xác nhận trên mẫu mới.
2. Không đọc tỉ lệ thô trên mẫu phân tầng là precision/recall.
3. `pairs.jsonl`: `a`, `b` xếp theo thứ tự bài trong kho → tra cặp bằng `frozenset`.
4. `uv run` **không kèm `--group embed`** sẽ gỡ PyTorch/onnxruntime khỏi `.venv` (các lệnh `make` đã kèm sẵn).
5. Chạy lại `build` ghi đè `audit_sample.csv` / `audit_ids.csv` của thư mục `--out`.
6. `pkill -f <mẫu>` trong script bash có thể tự giết chính shell → dùng `kill <pid>`.
7. Các CSV có nhãn Claude (< 2 MB) **không tái tạo được**, chưa có trên R2 → nên đưa lên R2 (prefix mới) trước khi đổi máy.

### 7.13 Bước tiếp theo (theo Gói 1 / hướng E)

1. Ghi phiếu quyết định vào tài liệu định nghĩa; xác nhận 3 điểm còn mở (mục 4.4).
2. Hướng dẫn gán **theo cụm** (`event_id` + `story_id`); bảng tính mẫu 2–3 ngày holdout (~1.000 bài); script suy ra cặp và đo κ, B-Cubed.
3. 2 người gán chung 150 bài; Claude gán cùng 150 bài để xem có thay người được không.
4. **Nhãn yếu v4:** cửa sổ theo loại sự kiện; loại chuỗi định kỳ và bài tổng hợp; lớp negative khó mới "cùng câu chuyện, khác
   sự kiện" (chung nhân vật/sự kiện lớn **và** khác địa điểm/đối thủ/ngày/văn bản, dùng `conflict_*`, `date_conflict`).
5. Song song: **fine-tune thử trên v3**, so với TF-IDF, MiniLM zero-shot, mô hình gốc zero-shot.
6. Tuỳ chọn: bge-m3 qua Kaggle/Colab; hiệu chỉnh lại p bằng ~1.300 nhãn Claude đã có (giữ một phần làm tập kiểm tra).

Các hướng tăng recall đã bàn: nới ngưỡng có điều kiện (ví dụ p ≥ 0,5 và `cos_lead` ≥ 0,2 và khác báo); đưa vùng 0,5–0,8 vào
`train_pairs` làm nhãn mềm; bắc cầu A~B, B~C ⇒ A~C (1 bước, cạnh p ≥ 0,99); cho Claude gán trực tiếp vùng 0,5–0,8; mở rộng
sinh ứng viên; self-training sau khi có mô hình fine-tune (mô hình chỉ đề xuất ứng viên, không tự gán nhãn).

---

## 8. Fine-tune mô hình embedding

### 8.1 Mô hình và so sánh dự kiến

| | Mô hình | Ghi chú kỹ thuật |
|---|---|---|
| **A** (đang làm) | **`bkai-foundation-models/vietnamese-bi-encoder`** (mô hình câu dựa trên PhoBERT, kiến trúc RoBERTa) | Tối đa **256 token**, **bắt buộc tách từ** |
| B (kế hoạch) | `intfloat/multilingual-e5-base` | Tối đa 512 token, **bắt buộc tiền tố `query: `**, không cần tách từ |

Bảng so sánh phải đủ 5 dòng: TF-IDF + thực thể IDF + thời gian · A zero-shot · A fine-tune · B zero-shot · B fine-tune. Điều
kiện công bằng: cùng tập cặp, cùng số bước, cùng mức tìm siêu tham số, **≥ 3 seed**, có CI. Gọi đúng tên phương pháp: **học
tương phản có giám sát với cặp yếu** (không gọi là SimCSE).

### 8.2 Hiện trạng thực thi

| | |
|---|---|
| Notebook | `training/finetune_bkai_kaggle.ipynb` (Kaggle, **GPU T4 x1**, bật Internet) |
| Đóng gói dữ liệu | `training/prepare_kaggle_data.py` → `data/temp/kaggle_upload/` (~15 MB) → tải lên Kaggle Dataset (private) |
| Dữ liệu train hiện dùng | **Bản tạm** `weak_supervision_pairs.csv` từ R2 `gold/weak_supervision/`: **23.254 cặp** (11.780 dương, 11.474 âm), chỉ có id + `similarity_score` + `label`. Cặp âm quá dễ (khác chuyên mục, cách hàng chục ngày); chưa rõ mô hình nào sinh `similarity_score` |
| Dữ liệu nên dùng | `data/weak_labels/v3/train_triplets.jsonl` / `train_pairs.jsonl` (cần sửa bước chép cặp trong script đóng gói) |
| Kết quả | **Chưa có mô hình fine-tune hay `results_*.json` nào lưu về máy** |

**Gói Kaggle gồm:** `weak_supervision_pairs.csv`; `articles.jsonl` (chỉ bài cần, `text` = tiêu đề + ". " + sapo); `audit_v1.csv`
(**tập chỉnh** 399 cặp, chọn ngưỡng cosine); `audit_v2.csv` (**tập đo** 400 cặp holdout, có `cos_head` để chia tầng);
`strata_sizes.json` (số cặp mỗi tầng → trọng số Horvitz–Thompson).

**Tiền xử lý bắt buộc** (mọi nơi dùng mô hình, kể cả gom cụm/API sau này): `NFC` → tách từ **`pyvi`** →
`model.encode(..., normalize_embeddings=True)`. Đầu vào `tiêu đề + ". " + sapo` (sau tách từ p99 ≈ 92 token).

**Cấu hình:** `loss="gist"` (mặc định; `GISTEmbedLoss` với mô hình dẫn đường là bản zero-shot đóng băng, lọc negative giả trong
batch) · `"mnrl"` (mốc so sánh) · `"cosent"`; lr 2e-5; 3 epoch; batch 64; warmup 0,1; weight decay 0,01; temperature 0,05
(= scale 20); `max_seq_length` 256; `BatchSamplers.NO_DUPLICATES`; cặp dương thêm cả hai chiều; seeds `[42]` để thử,
`[42, 43, 44]` khi báo cáo. Chạy **1 GPU** vì T4 x2 dùng DataParallel sẽ chia đôi batch và mất negative trong batch.

**Chia dữ liệu:** bỏ mọi cặp có bài từ (holdout − 48h) trở đi; bỏ cặp chạm tập đo hoặc trùng tập chỉnh; dev = 10% cặp dương muộn
nhất. Dev đo bằng **truy hồi** trên mọi bài cùng khoảng thời gian (MRR, Hit@1, Recall@10); checkpoint tốt nhất chọn theo
`eval_dev_mrr`, không nhìn tập đo.

**Đánh giá:** chọn ngưỡng cosine theo F1 trên `audit_v1`; đo trên `audit_v2` precision/recall/F1/AP **có trọng số theo tầng**, CI
95% bootstrap; recall theo **tầng trùng từ vựng** (thấp/vừa/cao, chia theo `cos_head`).

**Mốc zero-shot** (cùng giao thức, đo trên máy): bkai **F1 0,610 [0,51; 0,70], AP 0,688**; TF-IDF tiêu đề F1 0,594, AP 0,587.
Bỏ tách từ thì AP của bkai tụt còn ~0,557.

**Đầu ra trên Kaggle:** `/kaggle/working/models/<tag>/` (kèm `PREPROCESS.md`) và `results_<loss>.json`. Có thể đẩy lên Hugging
Face **private** bằng `HF_TOKEN` trong Kaggle Secrets.

### 8.3 Nhận biết mô hình tốt

Đạt **đủ**: AP > 0,688 và F1 > 0,610; mức tăng lớn hơn độ lệch giữa 3 seed (tốt hơn: paired bootstrap trên hiệu số AP, CI nằm
trọn trên 0); **recall tầng trùng từ vựng thấp tăng** (giá trị thật của fine-tune); precision không sụt mạnh; dev MRR cao hơn
zero-shot và không rơi dần cuối huấn luyện; ổn định giữa các seed. Cuối cùng phải thắng zero-shot ở bước gom cụm (B-Cubed).

**Dấu hiệu lỗi:** zero-shot trong notebook khác xa 0,610/0,688 (sai tiền xử lý); AP > 0,95 (rò rỉ dữ liệu); dev MRR tăng mà AP
đứng yên (dev quá dễ).

### 8.4 Vòng lặp cập nhật dữ liệu + mô hình

Được phép, với kỷ luật: **tập đo cố định** (`audit_v2`); **mỗi lượt train lại từ mô hình gốc**; mô hình chỉ **đề xuất** ứng
viên, nhãn do tín hiệu khác quyết định (nếu dùng làm `lf_dense` thì chỉnh lại ngưỡng và hiệu chỉnh p); không tìm dữ liệu
train trong holdout; dừng khi AP lượt mới nằm trong CI lượt trước; đặt tên phiên bản (dữ liệu `v3`, `v4`…; mô hình
`bkai-gist-v3-s42`). Mỗi lượt thí nghiệm chỉ đổi một thứ (ví dụ v3 lõi → + bắc cầu → + mở rộng → + nhãn Claude vùng 0,5–0,8).

---

## 9. Gom cụm, đặt tên, xu hướng (KẾ HOẠCH)

### 9.1 Gom cụm

**Single-pass thuần có ba nhược điểm:** phụ thuộc thứ tự bài đến; không gộp lại được hai cụm của cùng sự kiện; lỗi là vĩnh
viễn. Ngoài ra app có thông báo đẩy nên **ID sự kiện phải ổn định** (đẩy "Sự kiện mới: X" rồi phát hiện trùng = hai thông báo
cho một sự kiện).

| Tầng | Nhịp | Việc |
|---|---|---|
| Gán nhanh | Mỗi bài | Single-pass: bài mới → cụm gần nhất trong cửa sổ, hoặc cụm tạm |
| Gom lại + đối chiếu | Mỗi 15 phút | Gom lại cửa sổ 48h, khớp với sự kiện cũ bằng **Jaccard trên tập bài** để giữ `event_id`; cụm ≥ 3 bài chỉ lớn thêm, không tách |
| Thông báo | Khi sự kiện **ổn định** | ≥ k nguồn hoặc ≥ m bài, **và** đã qua ít nhất một vòng đối chiếu |

Tham số chỉnh trên tập vàng: **ngưỡng cosine giảm dần theo Δt**; cửa sổ 24/48/72h; thuật toán vòng gom lại (agglomerative
average-linkage hoặc HDBSCAN). So single-pass thuần với lai là một thí nghiệm (Miranda et al., EMNLP 2018). Phát hiện sự kiện mới
để thông báo = **First Story Detection**, đo bằng tỉ lệ bỏ sót, tỉ lệ báo động giả, độ trễ. Kiểm tra chéo bằng **VLSP 2022
Abmusu** (~3 bài/cụm), không thay tập vàng tự gán.

### 9.2 Đặt tên sự kiện

| | ViT5-base | BARTpho-word |
|---|---|---|
| Kích thước | ~226M | ~420M |
| Đầu vào | Âm tiết, không cần tách từ | **Bắt buộc tách từ**; đầu ra có `_` phải ghép lại |
| Checkpoint | `VietAI/vit5-base` hoặc bản `vietnews-summarization` | `vinai/bartpho-word` |

Đầu vào cụm: tiêu đề + sapo của tối đa N bài, **ưu tiên đa dạng nguồn**, ~1024 token; tự đặt `max_length` và
`truncation=True` (tokenizer ViT5 không có giới hạn mặc định).

| Vai | Nguồn |
|---|---|
| Nhãn huấn luyện (yếu) | Tiêu đề **medoid** (gần tâm cụm nhất) đã bỏ tiền tố ("Video:", "Clip:", "Nóng:") và cắt gọn, hoặc tên do LLM sinh offline rồi kiểm toán |
| Nhãn đánh giá (vàng) | **Người viết tay**, không xem output mô hình, 2 người viết độc lập một phần |
| Baseline bắt buộc | Tiêu đề medoid nguyên văn; medoid rút gọn bằng luật; cụm thực thể IDF cao nhất |
| Trần | LLM zero-shot offline |

Chỉ số: ROUGE word-level (sửa tokenizer tiếng Việt) + bootstrap CI, BERTScore, **% đúng độ dài 5–10 từ**, **% trung thực thực
thể** (mọi thực thể và con số trong tên phải có trong cụm), người chấm so cặp mù. Chính sách sản phẩm: tên chỉ sinh lại khi cụm
tăng gấp đôi hoặc rớt kiểm tra trung thực; kiểm tra trung thực **bắt buộc trước khi đẩy thông báo** (rớt thì dùng medoid rút
gọn); giới hạn độ dài cứng (`max_new_tokens`) + hậu kiểm số từ. Tuần 1 cần đo phân bố độ dài tiêu đề thật.

### 9.3 Điểm xu hướng

```
score(e, t) = (n_nguồn_hiệu_dụng(e) ^ α) · log(1 + vận_tốc_chuẩn_hoá(e, t))
              ─────────────────────────────────────────────────────────────
                            (tuổi_giờ(e, t) + 2) ^ G

vận_tốc_chuẩn_hoá = số bài 3h gần nhất / mức nền của khung giờ đó
n_nguồn_hiệu_dụng = số báo, có hệ số giảm cho nhóm bài trùng gần nguyên văn
```

So ≥ 2 công thức (gravity kiểu Hacker News vs log kiểu Reddit) + ablation từng thành phần. Ba lỗi phải tránh: số nguồn **bão
hoà nhanh** (chỉ 5–6 báo → cần vận tốc); chưa **chuẩn hoá theo giờ trong ngày**; chuyên mục có mức nền khác nhau (bảng tổng +
bảng theo chuyên mục).

**Đánh giá khách quan:** cào hộp **"Xem nhiều" / "Đọc nhiều"** mỗi giờ làm nhãn thay thế (độ nóng = số giờ có ≥ 1 bài của sự
kiện trong hộp của bất kỳ báo nào); đo Spearman ρ, Kendall τ, **NDCG@10**, độ trễ; baseline xếp theo số bài thô, số nguồn thô.
Giới hạn: hộp "xem nhiều" thiên về giải trí, câu view.

---

## 10. Kế hoạch đánh giá và các cổng kiểm chứng

### 10.1 Bảng đánh giá

| Tác vụ | Tập đánh giá | Chỉ số chính | Baseline bắt buộc | Phân tích bắt buộc |
|---|---|---|---|---|
| Hàm gán nhãn | Cặp suy ra từ tập vàng | Precision/recall theo cặp; % cặp dương khác báo | — | Trần/sàn của tín hiệu huấn luyện |
| Embedding + gom cụm | Cửa sổ vàng liền mạch, chạy theo thời gian | **B-Cubed F1** (+ P, R), AMI, purity + inverse purity | TF-IDF + thực thể; hai bản zero-shot | F1 theo tầng trùng từ vựng; đồng thuận người–người làm trần; ≥ 3 seed + CI |
| Single-pass vs lai | Như trên | B-Cubed F1, số lần đổi ID, số cụm trùng | Single-pass thuần | Ảnh hưởng tới thông báo trùng |
| Phát hiện sự kiện mới | Cửa sổ vàng | Tỉ lệ bỏ sót, báo động giả, độ trễ | Ngưỡng số bài thô | Đánh đổi độ trễ ↔ báo động giả |
| Đặt tên | Tên người viết cho cụm vàng (mù) | ROUGE + CI, BERTScore, % đúng độ dài, % trung thực | Medoid; medoid rút gọn; cụm thực thể | So cặp mù bởi người ngoài nhóm; đánh giá trên cụm vàng và cụm dự đoán |
| Xu hướng | Nhãn thay thế từ "Xem nhiều" | Spearman, Kendall, NDCG@10, độ trễ | Số bài; số nguồn | Ablation |
| Hệ thống | — | Unit test, test API, end-to-end | — | Độ trễ bài → sự kiện → thông báo |

**Không dùng silhouette** để so hai mô hình embedding (đo hình học nội tại, không so được giữa hai không gian); **purity** đạt 1,0
khi mọi bài là một cụm; **NMI** thiên lệch khi nhiều cụm nhỏ. **Không báo cáo số nào thiếu baseline và khoảng tin cậy.**

### 10.2 Tập vàng

Hướng dẫn gán 1–2 trang có ví dụ. Lấy **một khoảng thời gian liền mạch phủ mọi nguồn** (lấy ngẫu nhiên 500–1.000 bài trên nhiều
tuần thì gần như mọi bài là một cụm riêng); ~1.000 bài ≈ nửa ngày đến một ngày với 5 báo, nên có thể giới hạn 2–3 chuyên mục lớn
để phủ 2–3 ngày. Gán **theo thứ tự thời gian** (chọn cụm có sẵn hoặc tạo mới), ~30–60 giây/bài (~12 giờ/người cho 1.000 bài).
Tránh neo nhận thức: chỉ gợi ý cụm bằng baseline TF-IDF hoặc xáo thứ tự. **Đồng thuận người–người (B-Cubed F1) là trần của mọi
mô hình.** Chống rò rỉ: cửa sổ train kết thúc trước cửa sổ vàng, loại thêm ±48h.

**Công cụ gán (HIỆN TRẠNG, 19/10/2026):** `src/eventrank/evaluation/gold_clusters.py` (+ `gold_clusters.html`, test ở
`tests/evaluation/`). Cửa sổ đề xuất **14–15/09/2026** (1.496 bài, đủ 6 báo, sau mốc holdout 13/09 của dữ liệu train;
từ 17/09 Silver mất VnExpress và VietnamNet). Dự kiến ngày 14/09 làm tập chỉnh (chọn ngưỡng), 15/09 làm tập đo.

1. `make gold-tool` → `data/gold_clusters/v1/cong_cu_gan.html`: **một file HTML tự chứa** (dữ liệu nhúng sẵn, ~1 MB), gửi cho
   người gán, mở bằng Chrome/Edge/Firefox, không cần cài gì. Gợi ý cụm bằng TF-IDF (không bằng mô hình đang được chấm).
   Phím: `1`–`9` chọn cụm, `N` sự kiện mới, `X` loại (bài tổng hợp nhiều tin), `U` không chắc, `H` hướng dẫn. Tiến độ tự lưu
   trong trình duyệt; **Xuất CSV** để sao lưu và nộp.
2. Gán thử: 2 người, đoạn 1–100, độc lập →
   `uv run python -m eventrank.evaluation.gold_clusters agree A.csv B.csv` → B-Cubed người–người + `dong_thuan_lech.csv`.
   Cổng ≥ 0,7.
3. Gán thật: mỗi người một đoạn số thứ tự liên tiếp; người gán đoạn sau bấm **Nạp nhãn người khác** (CSV của đoạn trước) để nối
   vào cụm đã có. Gộp: `uv run python -m eventrank.evaluation.gold_clusters merge A.csv B.csv …` →
   `data/gold_clusters/v1/gold_clusters.csv` (`cluster_id, article_id, …`). Một bài bị gán ở hai file → báo lỗi.

**Cách 2 — Claude đề xuất, người duyệt (đang dùng, 19/10/2026):** gán tay từng bài quá mơ hồ và phải nhớ các cụm trước.
`src/eventrank/evaluation/gold_review.py`: gom thô (trong 48h VÀ TF-IDF ≥ 0,15 hoặc MiniLM ≥ 0,60; nhóm > 120 bài chia lại)
→ 177 nhóm nhiều bài + 546 bài lẻ; giữ chung nhóm 78/80 cặp v4 mức 3 trong cửa sổ, 0/24 cặp mức 0 → 8 agent Claude chia
mỗi nhóm thành sự kiện, đặt tên, độ tin (≈ 635 nghìn token) → 1.013 cụm đề xuất (180 cụm ≥ 2 bài, 87 cụm tin thấp, 19 bài
loại) → `make gold-review` → `duyet_cum.html`: mỗi nhóm một trang, sửa bằng chọn bài + phím số / `N` / `X`, gộp cụm khác nhóm
bằng tìm kiếm; xuất CSV cùng định dạng cách 1 (thêm cột `proposal`, `changed`).
**Hạn chế phải ghi trong báo cáo:** train v4 cũng do Claude gán → đáp án nghiêng về mô hình fine-tune. Đối chứng: đoạn
**STT 601–700** do người gán MÙ bằng cách 1, làm TRƯỚC khi xem đề xuất; so người-mù ↔ Claude ↔ bản duyệt bằng `agree`.
**Cập nhật 21/10/2026:** nhóm quyết định KHÔNG gán tay đoạn này; thay bằng Claude gán lại ĐỘC LẬP (một agent, đọc tiêu đề +
sapo + tóm tắt toàn văn + 2.500 ký tự đầu, không xem đề xuất cũ) → `llm/claude_gan_lai_601_700.csv`. Đồng thuận Claude cũ ↔
Claude gán lại: B-Cubed F1 0,980 (P 0,962, R 1,000) trên 100 bài; 10/13 cụm ≥ 2 bài trùng khớp, 3 chỗ lệch đều ở ranh giới
"phản ứng/hệ quả sau sự việc có cùng sự kiện không" (bài bình luận sau trận, bảng xếp hạng sau lượt đấu, bài cùng hội nghị).
Đây là độ ỔN ĐỊNH của Claude, KHÔNG phải độ đúng so với người; F1 cao một phần do 65/100 bài là cụm 1 bài.
→ Báo cáo phải ghi: tập vàng chưa có nhãn người; độ lệch Claude ↔ người chưa đo.

**Vòng kiểm tra (21/10/2026), `src/eventrank/evaluation/gold_verify.py`:** (A) tóm tắt TOÀN VĂN cả 1.496 bài (`llm/tom_tat_*.json`,
~34 agent); (D) nhóm duyệt 6 quy tắc ranh giới R1–R6 (`docs/huong-dan-gan-4-muc.md`); (B) 6 agent kiểm 222 cụm (mọi cụm ≥ 2 bài +
cụm "không chắc") bằng tóm tắt toàn văn — giữ / tách / loại; (C) 4 agent xét 157 cặp cụm có bài gần nghĩa (bkai fine-tune
cosine ≥ 0,85, trong 48h) — gộp 19 cặp; phiên chính loại thêm 10 bài tổng hợp nhiều tin và gộp 1 cặp. Kết quả
`proposals_v2.json`: **1.003 cụm (176 cụm ≥ 2 bài), loại 32 bài**, 52 thay đổi kèm lý do ở `llm/verify/thay_doi.md`.
B-Cubed v1 ↔ v2 = 0,980. Bản Claude gán lại độc lập STT 601–700 ↔ v2: F1 1,000 trên 99 bài (khác đúng 1 bài: bảng xếp hạng
→ x theo R4) — 3 chỗ lệch trước đây đều được R1–R6 giải quyết. Vẫn là nhãn Claude: độ lệch Claude ↔ người chưa đo.

**Chấm gom cụm (21/10/2026):** `training/cluster_eval_kaggle.ipynb` (Kaggle; tự tải tập vàng + mô hình từ R2 qua Kaggle Secrets).
Mô hình: TF-IDF (baseline), bkai zero-shot, bkai fine-tune v1, e5 zero-shot (+ e5 fine-tune khi có); thuật toán single-pass và
agglomerative average-linkage (cửa sổ 48h); ngưỡng chọn trên 14/09, B-Cubed + CI bootstrap theo cụm vàng trên 15/09, so ghép
cặp, recall theo tầng trùng chữ, độ nhạy với cụm "không chắc". **Chạy thử ở máy (chỉ TF-IDF + bkai fine-tune, chưa phải số báo
cáo):** mốc "mỗi bài một cụm" F1 0,838; TF-IDF 0,928 [0,902; 0,951]; bkai fine-tune agglo **0,967 [0,955; 0,976]**, hơn TF-IDF
+0,040 [0,020; 0,064]; recall tầng trùng chữ thấp 0,879 so với 0,563 (TF-IDF). Chưa có zero-shot → chưa trả lời được cổng tuần 6.

### 10.3 Cổng kiểm chứng

| Tuần | Cổng | Tiêu chí | Nếu trượt |
|---|---|---|---|
| 1 | Dữ liệu lấy được | Có sitemap để backfill, lấy được chuyên mục, đo độ dài tiêu đề | Crawler chạy liên tục, hạ mục tiêu |
| 2 | Hướng dẫn gán | 2 người gán 100 bài, **B-Cubed người–người ≥ 0,7** | Viết lại hướng dẫn |
| 3 | Luật gán nhãn dùng được | **Precision cặp dương ≥ 0,8**; **≥ 30% cặp dương khác báo** | Sửa LF, không fine-tune trên luật hỏng (**đã đạt ở v2/v3**) |
| 4 | Baseline có mốc | TF-IDF + thực thể có B-Cubed F1 | Vạch mọi mô hình phải vượt |
| 6 | Fine-tune có tác dụng | Ít nhất một mô hình thắng zero-shot của nó **ở tầng trùng từ vựng thấp**, CI không chồng | Báo cáo kết quả âm, phân tích vì sao |
| 7 | Đặt tên thắng baseline | Thắng medoid theo so cặp mù | Dùng medoid rút gọn |
| 8 | Thông báo an toàn | Tỉ lệ báo động giả ≤ ngưỡng đặt trước | Nâng ngưỡng k nguồn |

---

## 11. Ứng dụng: cài đặt, chạy, API, triển khai

### 11.1 Cài đặt (Linux/WSL, tại gốc repo)

Công cụ: `git`, `gh`, `make`, `uv` (tự cài Python 3.12), Node.js ≥ 20 + npm.

```bash
gh auth login                                       # tài khoản phải được Trần Đức Duy thêm làm collaborator
git clone https://github.com/ducduy-tran2703/Ranking-Event-Detection.git
cd Ranking-Event-Detection                          # đúng chữ HOA/thường
make install                                        # uv sync (.venv) + npm ci (apps/web)
cp .env.example .env                                # điền R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY
make dev                                            # backend :8000 + web :5173
```

Khoá R2 xin trưởng nhóm, nên là **khoá chỉ đọc**. Độ dài đúng: Account ID và Access Key ID 32 ký tự, Secret 64 ký tự. Kiểm
tra mà không in khoá: in `${#val}`. `R2_BUCKET=vietnam-news-datalake`. Chưa có khoá: `LAKE_BACKEND=local
LAKE_LOCAL_ROOT=tests/fixtures make dev` (5 bài mẫu). Chỉ chạy lại `make install` khi `uv.lock` hoặc `package-lock.json` đổi.

### 11.2 Lệnh `make`

| Lệnh | Việc |
|---|---|
| `make` / `make help` | Danh sách lệnh |
| `make install` | Cài thư viện Python và JavaScript |
| `make check-env` | Kiểm tra có `.env` (tự chạy trước `api`/`dev`) |
| `make api` | Backend FastAPI cổng 8000 |
| `make web` | Frontend React (Vite) cổng 5173 |
| `make dev` | Cả hai trong một terminal (Ctrl+C dừng cả hai) |
| `make types` | Sinh lại `apps/web/openapi.json` và `apps/web/src/api/schema.d.ts` sau khi sửa `apps/api/schemas.py` |
| `make test` | Test Python + lint + kiểm tra kiểu frontend |
| `make build` | Đóng gói web ra `apps/web/dist/` |
| `make prod` | Một cổng (8000) phục vụ cả web React lẫn API |
| `make embed` | Embedding ngữ nghĩa cho nhãn yếu → `data/weak_labels/cache/` |
| `make weak-labels` | Sinh nhãn yếu → `data/weak_labels/v3/` |
| `make agreement` | Cohen's κ nhãn người ↔ nhãn LLM |
| `make tunnel` | Cloudflare Tunnel tạm thời |
| `make db-up` / `make db-down` | Postgres 16 bằng Docker ở `127.0.0.1:5433` (chỉ khi máy chưa có Postgres; cần `POSTGRES_PASSWORD`) |
| `make db-migrate` / `make db-status` | Áp / xem migration `infra/db/migrations/` vào `DATABASE_URL` |
| `make ingest-import` | Nạp Silver JSONL ở máy (`SILVER_GLOB`) vào Postgres, idempotent |
| `make ingest-replay` | Phát lại Silver theo đồng hồ giả lập vào DB riêng `REPLAY_DATABASE_URL` (`REPLAY_START`, `REPLAY_SPEED`, `ARGS`) |
| `make ingest-status` | Mỗi báo: lần cào cuối, bài mới 1h/24h, lỗi gần nhất; đồng hồ |
| `make db-import-run` | Nạp một lần chạy pipeline (`data/runs/<run_id>/`, mặc định run mới nhất) vào tầng sự kiện của Postgres (`ARGS="<run_dir> --replace"`) |
| `make test-db` | Chỉ test cần Postgres (`TEST_DATABASE_URL`, role có `CREATEDB`); thiếu biến → skip |

**Postgres (từ 04/11/2026, cho hệ thống chạy liên tục — chưa bắt buộc cho web demo hiện tại).** Máy có Postgres cài sẵn
(`sudo apt install postgresql`, cổng 5432): tạo một lần `sudo -u postgres psql -c "CREATE ROLE eventrank LOGIN CREATEDB
PASSWORD '<mật khẩu>'"`, `sudo -u postgres createdb -O eventrank eventrank` (và `eventrank_replay` cho replay). Không có thì
`make db-up` (Docker, cổng 5433). Đặt `DATABASE_URL`, `REPLAY_DATABASE_URL`, `TEST_DATABASE_URL`, `CRAWLER_USER_AGENT` trong
`.env` (mẫu ở `.env.example`) rồi `make db-migrate`. CLI đầy đủ: `uv run --group embed python -m eventrank.ingest --help`
(`sources sync`, `import-jsonl`, `run --source X`, `replay`, `status`, `clock`). Chi tiết: `docs/handoff/ingest.md`.

| Địa chỉ | Là gì |
|---|---|
| http://127.0.0.1:5173 | Web React (`apps/web/`); Vite chuyển tiếp `/api` sang 8000 (không cần CORS) |
| http://127.0.0.1:8000 | Trang kiểm soát dữ liệu nội bộ (`apps/api/static/`, HTML/JS thuần, chỉ đọc) |
| http://127.0.0.1:8000/docs | Tài liệu API tự sinh |

Chỉ chạy `npm run dev` thì web báo "Không tải được dữ liệu" vì không có backend ở 8000. Test dùng dữ liệu mẫu `tests/fixtures/`,
không cần khoá, không gọi mạng (`uv run pytest -q`, `uv run ruff check src apps tests`).

**Hợp đồng API:** hình dạng JSON khai báo trong `apps/api/schemas.py` (Pydantic, endpoint có `response_model=`); hai file sinh tự
động **không sửa tay**, commit cùng PR; frontend chỉ gọi qua `apps/web/src/api/` (`client.ts`, `queries.ts`); TypeScript ghim
**5.x** (`openapi-typescript` không chạy với TS 7).

### 11.3 API

| Endpoint | Việc |
|---|---|
| `GET /api/health` | Server còn sống, số bài |
| `GET /api/stats/overview` | Tổng quan theo nguồn |
| `GET /api/stats/quality` | Lỗi chất lượng theo nguồn |
| `GET /api/articles?source=&q=&issue=&sort=&date_from=&date_to=&page_size=` | Tìm bài |
| `GET /api/stats/timeline?granularity=day\|hour&source=` | Số bài theo thời gian |
| `GET /api/files` | Danh sách file trên kho |
| `POST /api/admin/reload` | Nạp lại dữ liệu từ kho (= nút "Tải lại từ kho") |
| `GET /api/runs/current` | Lần chạy pipeline sự kiện đang phục vụ: `run_id`, phiên bản, số lượng, cửa sổ ẩn tên, ghi chú hạn chế |
| `GET /api/trending/times` | Khoảng mốc giờ có bảng xu hướng (`dau`, `cuoi`, `buoc_gio`, `mac_dinh`) + số sự kiện trên bảng từng giờ |
| `GET /api/trending?t=` | Top-20 xu hướng tại giờ `t` (ISO; không múi giờ = giờ VN; làm tròn xuống) + `t_truoc`/`t_sau`; bỏ `t` → mốc cuối có ≥ 10 sự kiện |
| `GET /api/events?q=&source=&date_from=&date_to=&min_size=&sort=hot\|newest\|size&page=&page_size=` | Danh sách sự kiện (mặc định ≥ 2 bài, `hot` = tổng điểm theo giờ); `q` khớp tên đang hiển thị/tiêu đề medoid, không phân biệt dấu |
| `GET /api/events/{event_id}` | Chi tiết: bài (URL từ Silver), số bài theo báo, chuỗi số bài + điểm xu hướng theo giờ (tính lại bằng `trending.score.score_at`) |
| `GET /api/events/stats?date=` | Số đếm, không có tên: phân bố kích thước sự kiện, số báo (sự kiện ≥ 2 bài), chuyên mục chính; `date` → `ngay` (số bài, số sự kiện, số sự kiện ≥ 2 bài TRONG ngày, số báo) |
| `GET /api/events/map/dates` | Các ngày đã có bản đồ 2D (bỏ ngày thuộc cửa sổ ẩn tên) + ngày mặc định (10/09/2026) |
| `GET /api/events/map?date=` | Bản đồ t-SNE các bài một ngày (`data/runs/<run_id>/ban_do/<date>.json`, sinh bằng `python -m eventrank.evaluation.event_map --date …`: perplexity 25, cosine, init pca, random_state 0, vector đệm `data/events/cache/emb_<model_version>.npz`) + tên ĐANG HIỂN THỊ của 8 sự kiện nhiều bài nhất trong ngày. File không chứa tên. Ngày giao cửa sổ ẩn tên → **403** (cả script cũng từ chối); chưa có file → 404 |
| `POST /api/auth/register · login · logout · logout-all · verify-email · forgot-password · reset-password · change-password`, `GET /api/auth/me` | Tài khoản (cookie phiên `er_session` HttpOnly + `csrf_token`); 204 hoặc `AccountUser`; 401 sai thông tin / chưa đăng nhập, 423 đang khoá, 429 quá nhiều lần |
| `GET/POST /api/me/follows`, `PUT/DELETE /api/me/follows/{event_id}`, `GET/POST /api/me/bookmarks`, `DELETE /api/me/bookmarks/{event_id}`, `GET/POST /api/me/subscriptions`, `DELETE /api/me/subscriptions/{id}`, `GET/PUT /api/me/settings`, `GET /api/me/sessions`, `DELETE /api/me/sessions/{id}`, `GET /api/me/notifications`, `POST /api/me/notifications/read`, `DELETE /api/me` | "Của tôi" (cần đăng nhập; ghi cần header `X-CSRF-Token`) |
| `POST /api/events/{event_id}/feedback` | Báo sai, khách gửi được (≤ 20/giờ mỗi IP hoặc tài khoản) |
| `GET /api/admin/users`, `PUT /api/admin/users/{id}`, `POST /api/admin/users/{id}/unlock`, `GET /api/admin/outbox`, `GET/POST /api/admin/api-tokens`, `DELETE /api/admin/api-tokens/{id}` | Quản trị (vai trò admin) |
| `GET /api/admin/feedback`, `PUT /api/admin/feedback/{id}` | Xử lý báo sai (editor hoặc admin) |

`/api/events` có thêm `category` (chuyên mục chính — chuyên mục gặp nhiều nhất trong các bài, đã gộp cách viết giữa các báo:
"Y Tế"/"Sức Khỏe" → "Sức khỏe", "Quốc Tế" → "Thế giới"), `first_from`/`first_to` (ISO, không múi giờ = giờ VN; lọc theo bài
đầu) và `sort=first_seen`; `EventSummary`/`TrendItem` có `chuyen_muc_chinh`, `TrendItem` có `first_seen`. `IssueCounts` có
thêm `missing_sapo` (sapo null/rỗng; cũng dùng được làm `issue=`).

`issue`: `missing_author`, `missing_sapo`, `empty_content`, `short_content`, `bad_date`, `future_date`, `duplicate_url`, `duplicate_id`.
`sort`: `newest`, `oldest`, `longest`, `shortest`. Ngày `YYYY-MM-DD` theo giờ Việt Nam. Tiếng Việt trong URL phải mã hoá (dùng
`curl -G --data-urlencode`). Server nạp dữ liệu một lần lúc khởi động và giữ trong RAM.

**Web React (`apps/web/`, mọi trang tải lười theo route):** công khai — `/` Xu hướng (phát lại theo giờ, `?t=YYYY-MM-DDTHH:MM`;
`/trending?t=` cũ chuyển về đây), `/events` (`?q=&source=&category=&date_from=&date_to=&min_size=&sort=&page=`; `?tim=1` đặt
con trỏ vào ô tìm), `/events/:id`, `/chuyen-muc`, `/du-lieu/chat-luong`, `/du-lieu/mo-hinh` (nội dung tĩnh
`src/content/models.ts`, mỗi số ghi nguồn), `/du-lieu/gom-cum?ngay=`; tài khoản — `/login?next=`, `/register`,
`/forgot-password`, `/reset-password?token=`, `/verify-email?token=`, `/me`; quản trị (vai trò admin) — `/admin/thu-thap`,
`/admin/bao-sai`, `/admin/thu`, `/admin/nguoi-dung`, `/admin/khoa-api`, `/admin/kho/…` (7 trang kiểm soát dữ liệu cũ; `/time`,
`/categories`, `/quality`, `/articles`, `/sources` cũ chuyển hướng vào đây). **Tài khoản có backend** (04/11/2026, `apps/api/accounts.py` + `src/eventrank/accounts/`, bảng 003–006): web gọi máy chủ thật mặc định; `VITE_AUTH_MOCK=1` bật lại adapter **giả lập** lưu localStorage (chỉ khi làm frontend không có Postgres; tài khoản mẫu `admin@example.com` / `bientap@example.com` / `ban@example.com`, mật khẩu `matkhau-demo`, trang hiện dải "Bản xem trước").

**Sự kiện (API cho web):** đọc MỘT lần chạy pipeline ở máy (`eventrank/serving/store.py`), không đọc R2:
`EVENTS_RUN_DIR`, không đặt thì lần chạy **đầy đủ** mới nhất trong `data/runs/` (manifest không có `--start/--end`,
`finished_at` muộn nhất; không theo thời điểm sửa file); log server ghi run đã chọn. Không có run → 5 endpoint trên trả
**503** ("chạy `make pipeline`", không chứa đường dẫn tuyệt đối), các trang bài báo vẫn chạy. `event_id` sai dạng
(`^E\d{8}-[0-9a-f]{8}$`), ngày sai dạng hoặc không có trên lịch, `t` ngoài khoảng → 422; không có sự kiện → 404.
**Ẩn tên tập test:** `EVENTS_HIDE_NAMES_WINDOW` (giờ VN, gồm cả hai ngày; **không đặt hoặc rỗng = mặc định
`2026-09-14..2026-09-15`; chỉ `off` mới tắt**, kèm cảnh báo trong log). Bị ẩn: sự kiện giao cửa sổ, và sự kiện ngoài cửa sổ
có tên mô hình gần trùng một tên mô hình (kể cả tên bị loại) của sự kiện trong cửa sổ — Jaccard âm tiết ≥ 0,6
(`NEAR_DUP_JACCARD`; run v2: 1.001 + 26 sự kiện). Sự kiện bị ẩn hiển thị tiêu đề medoid, `nguon_ten = "an"`,
`ten_bi_an = true`; tên mô hình bị bỏ ngay lúc nạp, không endpoint nào trả ra (kể cả tìm kiếm). Không phục vụ
`events.json`/`ten_su_kien.csv`. `/api/runs/current` có thêm khoảng dữ liệu (`du_lieu_tu/den`, `pham_vi_tu/den`). Run v2:
nạp ~0,65 s, ~60 MB RAM, phản hồi 1–11 ms.

### 11.4 Triển khai cho cả nhóm

`make prod`: FastAPI cổng 8000 phục vụ `/` (web React), `/api/…`, `/legacy/` (trang kiểm soát cũ), `/docs`. **Bắt buộc đặt mật
khẩu trước khi mở ra Internet** (trang có toàn văn bài báo có bản quyền): `DASHBOARD_USER`, `DASHBOARD_PASSWORD` trong `.env`
(tạo bằng `python3 -c "import secrets; print(secrets.token_urlsafe(24))"`); có hai biến này thì mọi đường dẫn, kể cả `/api` và
`/docs`, đều hỏi đăng nhập. Server dùng khoá R2 chỉ đọc.

| | A: Tunnel tạm | B: Tunnel + domain (khuyến nghị) | C: VPS + domain |
|---|---|---|---|
| Dựng | 5 phút | 30 phút | 1–2 giờ |
| Domain | Không | Có (~250k/năm) | Có |
| Địa chỉ | `https://<ngẫu nhiên>.trycloudflare.com`, đổi mỗi lần | Cố định | Cố định |
| Máy chạy | Máy bạn | Máy bạn hoặc VPS | VPS (~165k/tháng) |
| Mở cổng | Không | Không | 80/443 |
| Cách làm | `make prod` + `make tunnel` | `cloudflared tunnel login/create eventrank/route dns`, `~/.cloudflared/config.yml` trỏ `http://127.0.0.1:8000`, `cloudflared service install`, systemd `eventrank.service` | Caddy `reverse_proxy 127.0.0.1:8000`, không mở cổng 8000 |

Tuỳ chọn: Cloudflare **Zero Trust Access** cho đăng nhập bằng email từng người (miễn phí tới 50 người). Kiểm tra: trang trả 401
khi chưa đăng nhập; `curl -u nhom:<mật khẩu> …/api/health` trả `{"status":"ok"}`. Cập nhật: `git pull` → `make install` (nếu
lock đổi) → `make build` → `sudo systemctl restart eventrank`.

### 11.5 Quy trình git

Nhánh `feat/<module>-<mô-tả>`; không `git add .` khi chưa xem kỹ; kiểm tra `git diff --cached --name-only` không có `.env` hay dữ
liệu; commit message bắt đầu bằng mã module (`[INGEST] cào Tuổi Trẻ theo ngày qua sitemap`); merge vào `dev` qua Pull Request
điền đủ mẫu; không `push --force` lên `dev`/`main`. Mã module: `INGEST`, `LAKE`, `NLP`, `WEAK`, `EMB`, `CLUST`, `NAME`, `TREND`,
`EVAL`, `API`, `WEB`, `MOBILE`, `INFRA`, `DOCS`. Bàn giao module → `docs/handoff/<module>.md`. Thư mục `data/` không commit.

### 11.6 Sự cố thường gặp

`Repository not found` → `gh auth switch --user <tài-khoản-có-quyền>`; `uv: command not found` → `source "$HOME/.local/bin/env"`;
thiếu `.env` / biến trống → điền đủ; `AccessDenied`/403 → khoá sai hoặc bị thu hồi; `NoSuchBucket` → `R2_BUCKET=vietnam-news-datalake`;
cổng 8000 bận → `ss -ltnp | grep ':8000'`, `pkill -f "[u]vicorn apps.api"`; cổng 5173 bận → `pkill -f "[n]ode_modules/.bin/vite"`;
`make types` lỗi `createKeywordTypeNode` → `npm install -D typescript@5`; `npm ci` báo không đồng bộ → người sửa `package.json`
phải commit `package-lock.json`; không có biểu đồ → cần Internet để tải Chart.js; số liệu cũ → "Tải lại từ kho".

---

## 12. Phân công, lịch, rủi ro

### 12.1 Phân công 4 người (KẾ HOẠCH, quỹ ~480 giờ = 4 người × 12h/tuần × 10 tuần)

| | Mảng chính (tuần 1–6) | Mảng giao diện (tuần 6–9) | ~Giờ |
|---|---|---|---|
| **A — Data** (mã INGEST, LAKE, API) | Data lake, cào + backfill, "Xem nhiều", lịch chạy, ánh xạ chuyên mục, test pipeline | API FastAPI + Web dashboard | 120 |
| **B — NER & nhãn** (NLP, WEAK) | NER, chuẩn hoá thực thể, hàm gán nhãn + kiểm toán, hướng dẫn gán + điều phối tập vàng | Mobile tối thiểu + thông báo đẩy + cổng thông báo | 120 |
| **C — Embedding & gom cụm** (EMB, CLUST) | 5 dòng embedding, MNRL vs GIST, gom cụm lai + đối chiếu ID, đánh giá | Trang chi tiết sự kiện, tối ưu độ trễ | 120 |
| **D — Tên, xu hướng, đánh giá** (NAME, TREND, EVAL) | Đặt tên 2 mô hình + baseline, công thức xu hướng, bộ máy đánh giá chung (tokenizer ROUGE, bootstrap CI) | Bảng xu hướng, badge trung thực của tên | 120 |

Ước lượng giờ: data lake 70–90 · NER + nhãn 50–60 · embedding + gom cụm 70–80 · đặt tên 50–60 · xu hướng 25–35 · tập vàng 30–40 ·
API 20–30 · web 25–35 · **mobile + push 50–80** · báo cáo, slide, test 40–50 → **tổng 430–560 giờ** (chạm hoặc vượt trần).
Mobile bản tối thiểu: feed + chi tiết + push; không đăng nhập, không cá nhân hoá; một stack đa nền tảng (Expo/React Native +
Firebase Cloud Messaging).

**Lịch 10 tuần:**

| Tuần | A | B | C | D |
|---|---|---|---|---|
| 1 | Cào, backfill, Bronze | Hướng dẫn gán, công cụ gán | Baseline TF-IDF | Đo độ dài tiêu đề, sửa tokenizer ROUGE |
| 2 | Silver, dup_group, ánh xạ chuyên mục | 🚦 Cổng đồng thuận; NER | Embedding zero-shot | Harness CI, baseline tên |
| 3 | Gold, lịch chạy | 🚦 Cổng luật gán nhãn | Gom cụm single-pass | Cào "Xem nhiều" |
| 4 | Cào ổn định, test | Sinh cặp theo thời gian | 🚦 Mốc baseline; gom lại + đối chiếu | Công thức xu hướng |
| 5 | Monitoring | Hỗ trợ gán vàng | Fine-tune A, B (MNRL, GIST) | Fine-tune ViT5 |
| 6 | API | Bắt đầu mobile | 🚦 Cổng fine-tune | Fine-tune BARTpho |
| 7 | Web | Mobile + push | Phát hiện sự kiện mới | 🚦 Cổng đặt tên; đánh giá xu hướng |
| 8 | Web | 🚦 Cổng thông báo | Tích hợp end-to-end | So cặp mù |
| 9 | Test E2E, demo offline | Hoàn thiện mobile | Tối ưu độ trễ | Tổng hợp bảng số |
| 10 | Báo cáo | Báo cáo | Báo cáo | Báo cáo |

Việc chung: gán tập vàng (tuần 2–4, **trước khi có mô hình**), chấm so cặp mù (người **ngoài nhóm**), báo cáo, slide.

### 12.2 Rủi ro

| Rủi ro | Xác suất | Tác động | Giảm thiểu |
|---|---|---|---|
| Định nghĩa sự kiện mơ hồ → tập vàng vô nghĩa | Cao | Cao | Cổng đồng thuận tuần 2 (đã chốt Gói 1) |
| Luật gán nhãn chỉ sinh cặp cùng báo | Cao | Cao | Bỏ "cùng chuyên mục"; đo % khác báo (**v3: 90% khác báo**) |
| Fine-tune không thắng TF-IDF | Trung bình | Cao | Đo trên tầng trùng từ vựng thấp; kết quả âm vẫn hợp lệ nếu phân tích tốt |
| Baseline medoid thắng mô hình đặt tên | Trung bình | Trung bình | Nhãn người viết; trình bày trung thực |
| Mobile ăn hết thời gian | Cao | Trung bình | Bản tối thiểu, bắt đầu tuần 6 |
| Thông báo trùng hoặc sai | Trung bình | Cao | ID ổn định + cổng ổn định + bảng đã gửi + kiểm tra tên |
| Dữ liệu mỏng (giới hạn 500 bài/chuyên mục) | Trung bình | Trung bình | Cào theo ngày qua sitemap; cặp tốt quan trọng hơn số bài |
| Crawler chết âm thầm | — | Cao | Cảnh báo theo từng báo (RSS không lấy lại được quá khứ) |
| Pháp lý: lưu và hiển thị nội dung có bản quyền | Thấp | Trung bình | Chỉ lưu nội bộ; bucket private; trang có mật khẩu; app chỉ hiện tên + tiêu đề + link |

---

## 13. Mâu thuẫn giữa các tài liệu gốc và cách hiểu đúng

| Chủ đề | Tài liệu cũ nói | Hiện trạng / số đúng |
|---|---|---|
| Tên bucket | `event-lake` (hướng dẫn data lake) | **`vietnam-news-datalake`** |
| Định dạng và lớp kho | Bronze `.html.gz` + Silver **Parquet** + Postgres | **Chỉ Silver JSONL** + Gold + nhãn yếu; chưa có Bronze |
| Danh sách báo | 5 báo đề xuất (Thanh Niên, Tuổi Trẻ, Dân Trí, VietnamNet, VnExpress) | **6 báo thực tế:** tuoitre, thanhnien, vietnamnet, nhandan, vnexpress, baochinhphu. **Không có Dân Trí** |
| Khoảng backfill | 01/06–31/07/2026, 45–50k bài | Thực tế 28.746 bài, 76% trong 1/8–19/9/2026 |
| Số bài trong kho | 18.124 bài, 4 nguồn (ảnh chụp 19/09) | 28.746 bài, 6 nguồn |
| Thư mục báo Nhân Dân | `silver/baodantri/silver_nhandan.jsonl` (lake-layout), `silver/baonhandan/` (data-contracts), `silver/baodantri/` (tiền xử lý) | Thư mục lệch tên với trường `source = nhandan`; **cần thống nhất** |
| `standardized_category` | Mẫu 4.000 bài: chưa chuẩn hoá (13 giá trị) | Gold hiện tại: **10 chuyên mục chuẩn** (Thể Thao, Thế Giới, Văn Hóa, Chính Trị, Du Lịch, Kinh Tế, Khoa học - Công nghệ, Pháp Luật, Giáo Dục, Sức Khỏe) |
| Taxonomy chuyên mục đề xuất | 10–12 mục (Thời sự, Thế giới, Kinh doanh, Pháp luật, Giáo dục, Y tế, Thể thao, Giải trí, Công nghệ, Đời sống, Khác) | Gold đang dùng bộ 10 mục ở dòng trên |
| Gold thiếu `published_at` | Mẫu 4.000 bài không có trường thời gian | Gold hiện tại **có** `published_at` (21 bài trống) |
| Công cụ NER | Đề xuất `underthesea` / VnCoreNLP / PhoBERT-NER | Gold do thành viên khác làm, 6 nhãn, độ chính xác ~90% |
| Bộ tách từ | Đề xuất `underthesea` | Notebook fine-tune dùng **`pyvi`**. Phải chốt một bộ dùng cho mọi nơi |
| Ngưỡng nhãn yếu | v1 và Phụ lục A cũ: dương 0,85 / âm 0,15 | **v2 trở đi: dương 0,80 / âm 0,10** (trên p đã hiệu chỉnh) |
| Precision v1 | 0,67 (README v1, tỉ lệ thô trên audit v1) | **0,81** (có trọng số, trên audit v2). Khác vì cách đo, không phải dữ liệu |
| Precision v2 | 0,89 (README v2, thô) | **0,93** (có trọng số) |
| Recall v2 | "bắt 89/172" ≈ 0,52 (thô) | **0,20** (có trọng số) |
| Định nghĩa sự kiện | Tài liệu nhãn yếu: "nhóm chưa chốt"; phiếu quyết định còn trống | **Đã chốt Gói 1 / hướng E** (theo tài liệu bàn giao) |
| Cửa sổ ứng viên | Luật ban đầu 48h | Ứng viên ±7 ngày (168h); phiếu dương ≤ 72h |
| Đánh giá gom cụm | silhouette, purity, NMI | **B-Cubed**; không dùng silhouette |
| Gom cụm | Tăng dần thuần | Kiến trúc lai có đối chiếu ID |
| Khử trùng gần trùng | Loại bỏ | **Đánh dấu `dup_group_id`, giữ lại** |
| Dữ liệu fine-tune | Tài liệu nhãn yếu: train trên `v3/train_triplets.jsonl` | Notebook hiện đọc **file tạm** `weak_supervision_pairs.csv` |
| Gán bằng LLM | Chỉ dùng để đo, không tạo dữ liệu train | Vẫn đúng; nếu dùng nhãn Claude để train thì phải sửa quy tắc và tách hẳn tập đo |

---

## 14. Thuật ngữ

**Kiến trúc kho:** *Data lake* (dữ liệu thô dạng file) · *Data warehouse* (sạch, bảng chặt) · *Lakehouse* (file trên object
storage, truy vấn bằng SQL: Parquet/JSONL trên R2 + DuckDB) · *Medallion* Bronze (thô, bất biến) → Silver (sạch, có cấu trúc) →
Gold (đặc trưng cho mô hình) · *ELT* (nạp thô trước, xử lý sau) · *Backfill* (lấy dữ liệu quá khứ) · *Snapshot* + *Manifest*
(bản đóng băng + mô tả số dòng, mã băm) · *Lineage* (truy vết nguồn gốc).

**Tính chất:** *Immutable / append-only* (dữ liệu không sửa) · *Idempotent* (thao tác chạy lại vẫn đúng) · *Atomic write* (ghi file
tạm rồi đổi tên) · *Versioning* (`parser_version`) · *Reproducible*.

**Object storage:** *Bucket*, *Object*, *Key* (dấu `/` chỉ là ký tự), *Prefix*, *S3-compatible API*, *Endpoint*
(`https://<account_id>.r2.cloudflarestorage.com`), *Egress* (phí tải ra, R2 miễn phí), *Class A* (ghi/liệt kê, đắt) / *Class B*
(đọc, rẻ), *Public access* (phải tắt).

**Định dạng:** *Parquet* (lưu theo cột) · *Partition* / *Hive partitioning* (`cot=giatri`) · *Partition pruning* · *Small file
problem* · *Compaction* · nén `gzip` (HTML) / `zstd` (Parquet) · *Schema evolution* (tăng phiên bản, không sửa file cũ).

**Bảo mật:** *API token*, *Access Key ID / Secret* (secret hiện một lần), *Account ID*, *Scope*, *Least privilege*, *Key
rotation*, *Secrets management* (`.env`, Colab/Kaggle Secrets), *2FA*, *Deploy key*.

**Thu thập:** *Crawler* · *RSS* (vài chục bài mới nhất, không lịch sử) · *Sitemap* / *sitemap index* (`<sitemapindex>`) / *urlset* ·
*`lastmod`* · *`robots.txt`* · *Crawl-delay* · *User-Agent* · *Throttle* · *ETag / If-Modified-Since* (304) · *Backoff* ·
*Frontier* (hàng đợi URL) · *Claim* · *Boilerplate removal* (`trafilatura`) · *JSON-LD / schema.org* · *Breadcrumb* · *Canonical
URL* (bỏ `utm_*`, `fbclid`, `www.`, `/` cuối) · *URL hash* (SHA-256).

**Khử trùng:** *Exact duplicate* (loại) · *Near-duplicate* (đánh dấu, giữ) · *Shingle* · *MinHash* · *SimHash* · *LSH*.

**Chất lượng:** *Quality flag* · *NFC / NFD* · *Timezone-aware / naive datetime* · *`timestamptz`* · *Ground truth / gold
standard* · *Data drift*.

**Vận hành:** *Worker*, *Scheduler*, *`flock`*, *`tmux`/`screen`*, *WAL*, *`SKIP LOCKED`*, *Heartbeat*, *Dead-man alert*,
*Healthcheck*, *Graceful shutdown*, *Restore test*.

**ML trong đề tài:** *Weak supervision* (nhiều LF bỏ phiếu) · *LF* (hàm gán nhãn) · *Label model* (Dawid–Skene/EM) · *Calibration*
(isotonic) · *Bi-encoder* · *MNRL* (negative trong batch) · *GISTEmbedLoss* (mô hình dẫn đường lọc negative giả) · *CoSENT /
AnglE* (cặp có điểm) · *Hard negative* · *Horvitz–Thompson* (trọng số N_tầng/n_tầng) · *Bootstrap CI* · *Cohen's κ* · *B-Cubed* ·
*TDT* (event vs topic) · *First Story Detection* · *Medoid*.

---

## 15. Tài liệu tham khảo

- Allan et al. (1998), *Topic Detection and Tracking Pilot Study* (event/story, First Story Detection).
- Miranda et al. (EMNLP 2018), *Multilingual Clustering of Streaming News* (https://aclanthology.org/D18-1483/, mã: github.com/Priberam/news-clustering); *Batch Clustering for Multilingual News Streaming*.
- Ratner et al. (2017), *Snorkel: Rapid Training Data Creation with Weak Supervision*.
- Gao et al. (EMNLP 2021), *SimCSE*.
- Sentence-Transformers, danh mục loss (MNRL, GISTEmbedLoss): https://sbert.net/docs/package_reference/sentence_transformer/losses.html; giảm negative sai trong MNRL: https://huggingface.co/blog/dragonkue/mitigating-false-negatives-in-retriever-training
- `intfloat/multilingual-e5-base` (tiền tố `query: `, 512 token).
- Bagga & Baldwin (1998), B-Cubed; Amigó et al. (2009), *A comparison of extrinsic clustering evaluation metrics*.
- Narayan et al. (2018), *XSum*; ViT5 (NAACL 2022 SRW); BARTpho (INTERSPEECH 2022).
- Cloudflare R2 pricing: https://developers.cloudflare.com/r2/pricing; DuckDB S3/R2: https://duckdb.org/docs/current/core_extensions/httpfs/s3api.html

---

## Phụ lục A: Đường dẫn quan trọng (trong repo `Ranking-Event-Detection/`)

| Đường dẫn | Là gì |
|---|---|
| `src/eventrank/lake/reader.py` | Đọc kho, chuẩn hoá phía người đọc |
| `src/eventrank/weak_labels/{entities,corpus,pairs,lfs,label_model,dense,build,evaluate,agreement}.py` | Nhãn yếu v3 |
| `src/eventrank/weak_labels/graded.py`, `docs/huong-dan-gan-4-muc.md` | Nhãn 4 mức v4 (xây trên `v3/pairs.jsonl`) |
| `configs/entity_aliases.yaml` | Alias thực thể |
| `apps/api/main.py`, `apps/api/schemas.py`, `apps/api/static/` | Backend, hợp đồng API, trang kiểm soát |
| `apps/web/` | Web React + Vite + TypeScript |
| `training/prepare_kaggle_data.py`, `training/finetune_{bkai,e5}_kaggle.ipynb` | Fine-tune embedding (mô hình A, B) |
| `data/lake/{gold,silver}/` | Bản tải về của kho (không commit) |
| `data/weak_labels/v1/` | Chỉ còn **tập chỉnh** `audit_labeled_llm_ids.csv` + `audit_labeled_llm.csv`, `human_label_100.csv` (dữ liệu lớn của v1 có trên R2 `weak_label_NguyenDinhHieu/`, đã xoá ở máy 19/10/2026) |
| `data/weak_labels/v2/` | Chỉ còn **tập đo** `audit_labeled_llm.csv` + `pairs.jsonl` (tổng thể để tính trọng số tầng); phần còn lại của v2 đã xoá 19/10/2026 |
| `data/weak_labels/v3/`, `data/weak_labels/v4/` | Nhãn yếu đang dùng (không commit); bản trên R2: `weak_label_NguyenDinhHieu/v3/`, `…/v4/` |
| `data/gold_clusters/v1/` | Tập vàng gom cụm (không commit); bản trên R2: `gold_clusters_NguyenDinhHieu/v1/` |
| `data/weak_labels/models/`, `data/weak_labels/cache/` | Mô hình MiniLM ONNX, file embedding `.npz` |
| `data/temp/kaggle_upload/` | Gói dữ liệu tải lên Kaggle |
| `tests/fixtures/` | Dữ liệu mẫu cho test |

## Phụ lục B: Các file nguồn đã gộp

> **19/10/2026:** tài liệu này được đưa vào repo thành `docs/tong-hop.md` và thay cho các file `docs/` cũ; mọi tham chiếu
> trong `AGENTS.md`, `README.md`, skill, mẫu PR và code đã trỏ về đây theo số mục.

> **Đã xoá ngày 10/10/2026** sau khi gộp: 6 file ở `pbl/` (không có trong git, không khôi phục được) và 9 file trong
> `Ranking-Event-Detection/docs/`. Các file trong `docs/` khôi phục được bằng `git restore docs/` (riêng
> `lam-sach-du-lieu.md` chưa từng commit nên không khôi phục được). Các README trong `data/` và `README.md` của repo vẫn giữ.

Thư mục `pbl/`: `mo-ta-du-an-event-clustering-trending.md`, `phan-tich-event-clustering-trending.md`,
`huong-dan-xay-dung-data-lake.md`, `huong-dan-data-lake-cloud.md`, `huong-dan-chi-tiet-datalake-online.md`,
`thuat-ngu-datalake.md`.

Repo `Ranking-Event-Detection/`: `README.md`, `docs/dinh-nghia-su-kien.md`, `docs/lake-layout.md`, `docs/data-contracts.md`,
`docs/lam-sach-du-lieu.md`, `docs/tien-xu-ly.md`, `docs/nhan-yeu-chi-tiet.md`, `docs/handoff/weak_labels.md`,
`docs/huong-dan-chay-du-an.md`, `docs/trien-khai.md`, `data/lake/gold/README.md`, `data/weak_labels/v1/README.md`,
`data/weak_labels/v2/README.md`, `data/weak_labels/v3/README.md`, `data/temp/kaggle_upload/README.md`.

**Không gộp** (file cấu hình cho AI agent và GitHub): `AGENTS.md`, `CLAUDE.md`, `.claude/skills/*/SKILL.md`,
`.github/pull_request_template.md`.
