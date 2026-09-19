# Kế hoạch tiền xử lý dữ liệu

> Biến lớp **Silver** (bài báo đã tách trường) thành lớp **Gold** (dữ liệu sẵn sàng cho gom cụm sự kiện).
> Các con số thời gian trong tài liệu là **đo thật** trên máy, ngày 19/09/2026.

## 0. Đầu vào, đầu ra

```
silver/<source>/*.jsonl          →   tiền xử lý   →   gold/
18.124 bài, 4 nguồn                                  ├── articles/     bài đã chuẩn hoá + gắn cờ + đánh dấu trùng
                                                      ├── entities/     thực thể đã chuẩn hoá
                                                      └── segmented/    văn bản đã tách từ (cho PhoBERT, TF-IDF)
```

**Ba nguyên tắc:**

1. **Không sửa Silver.** Tiền xử lý chỉ đọc Silver và ghi ra Gold. Sai thì chạy lại, không mất gì.
2. **Chạy lại cho cùng kết quả.** Mỗi lần chạy ghi kèm `pipeline_version`; đổi logic thì tăng phiên bản và ghi sang thư mục mới.
3. **Đánh dấu, không xoá.** Bài lỗi, bài trùng, bài quá ngắn đều được **gắn cờ**; bước sau tự quyết định có dùng hay không.

---

## 1. Tám bước, theo đúng thứ tự

### Bước 1 — Chuẩn hoá văn bản

| | |
|---|---|
| Làm gì | Unicode về **NFC**; gộp khoảng trắng; bỏ ký tự điều khiển; đổi dấu nháy cong `"" ''` về nháy thẳng; giải mã HTML entity còn sót (`&amp;`, `&nbsp;`) |
| Vì sao | "ế" có thể là **một** ký tự hoặc **hai** ký tự ghép. Không chuẩn hoá thì hai chuỗi trông giống hệt nhau lại không khớp khi so trùng, băm, hay tách từ |
| Thư viện | `unicodedata` có sẵn trong Python |
| Kiểm tra | Đếm số bài đổi sau chuẩn hoá; xem tay 10 bài |

### Bước 2 — Chuẩn hoá trường

| Trường | Quy tắc |
|---|---|
| `source` | Viết thường, **phải trùng tên thư mục**. ⚠️ Hiện `silver/baodantri/` chứa `source: "nhandan"` — phải chốt một tên |
| `category` | Giữ nguyên bản gốc, **thêm** cột `category_std` theo bảng ánh xạ 10–12 chuyên mục chuẩn dùng chung cho mọi báo |
| `published_at` | Về dạng có múi giờ; thêm `published_date_vn` (ngày theo giờ Việt Nam) và `published_hour_vn` |
| `author` | Rỗng → `null` |

Bảng ánh xạ chuyên mục để trong `configs/section_mapping.yaml`, **có phiên bản**, vì mỗi báo đặt tên khác nhau ("Thời sự" / "Xã hội" / "Chính trị").

### Bước 3 — Gắn cờ chất lượng

Thêm cột `flags` (danh sách), dùng lại đúng các định nghĩa trang trực quan hoá đang dùng:

`missing_author`, `empty_content`, `short_content` (<80 từ), `bad_date`, `future_date`, và thêm mới:

- `likely_video` — URL hoặc tiêu đề có "video", "clip", thân bài rất ngắn
- `likely_pr` — tiêu đề chứa tên thương hiệu + từ khoá tuyển dụng / khuyến mãi (ví dụ đã thấy: "Vietjet tổ chức chuỗi Ngày hội tuyển dụng")
- `out_of_window` — ngoài khoảng thời gian có đủ 4 báo (trước 20/05/2026)

### Bước 4 — Khử trùng lặp

| Loại | Cách phát hiện | Xử lý |
|---|---|---|
| Trùng tuyệt đối | `article_id` (= `sha256(url)`) | Giữ một bản |
| **Gần trùng** | **MinHash + LSH** trên 5-gram của `title + sapo`, ngưỡng Jaccard ~0,8 | **Đánh dấu** `dup_group_id`, **giữ nguyên** |

⚠️ Bài gần trùng giữa các báo **là tín hiệu chính** của đề tài (nhiều báo cùng đưa một tin), tuyệt đối không xoá. Đã thấy sẵn các tiêu đề giống hệt nhau ở 2 báo.

Thư viện: `datasketch` (kéo theo numpy, scipy). Kiểm tra: xem tay 20 nhóm ngẫu nhiên xem có đúng là cùng một tin không.

### Bước 5 — Tách câu và tách từ

| | |
|---|---|
| Thư viện | **`underthesea`** — chạy tốt, không kéo theo PyTorch |
| Kết quả đo | `sent_tokenize` gần như tức thì; `word_tokenize` **15 ms/bài** → cả kho ~**4,4 phút** |
| Ghi ra | `title_seg`, `sapo_seg`, `body_seg` (dạng `Tổng_Bí_thư`, `phu_nhân`) |
| Vì sao cần | PhoBERT **bắt buộc** văn bản đã tách từ; TF-IDF và tìm kiếm cũng chính xác hơn |

⚠️ **Chốt đúng MỘT bộ tách từ cho cả dự án.** Train bằng `underthesea` rồi chạy bằng VnCoreNLP (hay ngược lại) sẽ làm tụt điểm mô hình mà không ai hiểu vì sao.

### Bước 6 — Trích thực thể

**Chỉ chạy trên `title + sapo + 3 câu đầu thân bài`, không chạy toàn bài.**

| Phạm vi | Thời gian mỗi bài | Cả kho 18.124 bài |
|---|---|---|
| Toàn bài | 909 ms | **4,6 giờ** |
| Tiêu đề + sapo | **8 ms** | **2,3 phút** |

Nhanh hơn **121 lần**, và tin tức viết theo hình tháp ngược nên thực thể quan trọng gần như luôn ở đầu bài.

⚠️ **Phải đo chất lượng NER trước khi tin vào nó.** Thử nghiệm trên một câu thật cho kết quả sai rõ ràng:

```
"Chủ tịch nước Tô Lâm"     → gán nhãn ĐỊA DANH (đúng ra là TÊN NGƯỜI)
"Điện Invalides , Paris"   → gộp làm một thực thể, kể cả dấu phẩy
```

Việc cần làm **trước khi dùng thực thể để sinh nhãn yếu**: gán tay 100 câu tin thật, đo precision/recall theo từng loại (PER/LOC/ORG). Nếu quá thấp thì đổi sang mô hình NER khác trên Hugging Face, hoặc chỉ dùng những loại thực thể mà nó làm đúng.

**Chuẩn hoá thực thể** (quan trọng không kém việc trích): `TP.HCM` / `TP. Hồ Chí Minh` / `Thành phố Hồ Chí Minh` phải về một tên. Dùng bảng alias + so khớp mờ (`rapidfuzz`). Kèm danh sách thực thể quá phổ biến ("Việt Nam", "Hà Nội", "Chính phủ") để bước sinh nhãn yếu **không** coi chúng là bằng chứng cùng sự kiện.

### Bước 7 — Chuẩn hoá ngày trong văn bản

Tin Việt hay viết ngày tương đối hoặc rút gọn: *"Chiều 10.9"*, *"sáng qua"*, *"tối 14/9"*. Chuyển về ngày tuyệt đối dựa trên `published_at`.

Hai báo viết khác nhau: Thanh Niên dùng **dấu chấm** (`10.9`), các báo khác dùng **gạch chéo** (`10/9`) — regex phải nhận cả hai.

Ngày sự kiện sau chuẩn hoá là **tín hiệu rất mạnh** để gom cụm: hai bài đăng khác ngày nhưng cùng nói về biến cố ngày 10/9 thì vẫn nhận ra nhau.

### Bước 8 — Đặc trưng cho các bước sau

| Đặc trưng | Dùng cho |
|---|---|
| `lead_text` = `title + sapo + 3 câu đầu` | Đầu vào cho embedding (vừa giới hạn 256 token của PhoBERT) |
| `n_words`, `title_words` | Lọc chất lượng |
| Danh sách **số và đơn vị** trong bài (số người, số tiền) | Kiểm tra tính trung thực khi đặt tên sự kiện; là tín hiệu phụ để gom cụm |
| `entity_idf` | Bỏ qua thực thể quá phổ biến khi so hai bài |

---

## 2. Thời gian chạy toàn bộ

| Bước | Thời gian (1 tiến trình) |
|---|---|
| 1–4: chuẩn hoá, gắn cờ, khử trùng | ~2–4 phút |
| 5: tách câu + tách từ | **4,4 phút** |
| 6: trích thực thể (chỉ đầu bài) | **2,3 phút** |
| 7–8: ngày tháng, đặc trưng | ~2 phút |
| **Tổng** | **~12–15 phút cho cả kho** |

Chạy lại toàn bộ chỉ mất một lượt cà phê, nên **không cần tối ưu sớm**. Sau này chỉ xử lý bài mới thì còn nhanh hơn nữa.

---

## 3. Đầu ra: schema lớp Gold

`gold/articles/v=<pipeline_version>/source=<báo>/dt=<ngày đăng>/part-*.jsonl`

| Cột | Từ đâu |
|---|---|
| `article_id`, `url`, `source`, `published_at` | Silver |
| `title`, `sapo`, `content_text` | Silver, sau chuẩn hoá văn bản (bước 1) |
| `category`, `category_std` | Bước 2 |
| `published_date_vn`, `published_hour_vn` | Bước 2 |
| `flags` | Bước 3 |
| `dup_group_id` | Bước 4 |
| `title_seg`, `sapo_seg`, `lead_seg` | Bước 5 |
| `entities` (text, type, text_norm) | Bước 6 |
| `event_date` | Bước 7 |
| `lead_text`, `n_words`, `numbers` | Bước 8 |

Ghi kèm `pipeline_version` trong **mọi** bản ghi.

---

## 4. Cấu trúc code

```
src/eventrank/preprocess/
├── text.py        # bước 1: NFC, khoảng trắng, HTML entity
├── fields.py      # bước 2: source, category_std, thời gian
├── flags.py       # bước 3: gắn cờ chất lượng
├── dedup.py       # bước 4: MinHash + LSH
├── segment.py     # bước 5: tách câu, tách từ
├── entities.py    # bước 6: NER + chuẩn hoá alias
├── dates.py       # bước 7: ngày trong văn bản
└── pipeline.py    # ghép 8 bước, ghi Gold, ghi pipeline_version

jobs/build_gold.py            # điểm chạy: đọc Silver → ghi Gold
configs/section_mapping.yaml  # bảng ánh xạ chuyên mục
configs/entity_aliases.yaml   # bảng gộp tên thực thể
tests/preprocess/             # mỗi bước một file test
```

Thêm lệnh vào `Makefile`:

```makefile
gold:  ## Chạy tiền xử lý Silver → Gold
	uv run python -m jobs.build_gold
```

Mỗi hàm nhận **một bản ghi** và trả về bản ghi đã xử lý, không đụng mạng — nhờ vậy test được bằng dữ liệu mẫu, không cần R2.

---

## 5. Kiểm tra sau mỗi bước

| Bước | Cách kiểm tra |
|---|---|
| 1 | Số bài thay đổi sau chuẩn hoá; 10 bài xem tay |
| 2 | Không còn `source` viết hoa; ≥95% bài có `category_std` khác "Khác" |
| 3 | Tỉ lệ từng cờ theo nguồn — so với tab **Chất lượng** của trang trực quan hoá |
| 4 | 20 nhóm gần trùng xem tay; tỉ lệ bài thuộc nhóm trùng theo cặp báo |
| 5 | 20 câu xem tay; đếm tỉ lệ token dính `_` bất thường |
| 6 | **Gán tay 100 câu**, đo precision/recall theo loại thực thể |
| 7 | 30 bài có ngày trong tiêu đề, so ngày suy ra với thực tế |
| 8 | Phân bố `n_words`, số bài không có thực thể nào |

Quy tắc: **bước nào chưa đạt thì không chạy bước sau**, vì lỗi sẽ lan xuống toàn bộ.

---

## 6. Sáu quyết định cần chốt trước khi viết code

| # | Quyết định | Gợi ý |
|---|---|---|
| 1 | Tên nguồn cho báo thứ tư: `baodantri` hay `nhandan`? | Chốt theo tên báo thật, sửa cả thư mục, tên file và trường `source` |
| 2 | Bộ tách từ | `underthesea` (đã đo: nhanh, không cần JVM, không cần PyTorch) |
| 3 | Taxonomy chuyên mục chuẩn | 10–12 mục: Thời sự, Thế giới, Kinh doanh, Pháp luật, Giáo dục, Y tế, Thể thao, Giải trí, Công nghệ, Đời sống, Khác |
| 4 | Ngưỡng gần trùng | Bắt đầu 0,8; xem tay 20 nhóm rồi chỉnh |
| 5 | Nguồn NER | Bắt đầu `underthesea`; **đo trước**; kém thì đổi mô hình |
| 6 | Xử lý bài ngoài cửa sổ chung (trước 20/05/2026) | Gắn cờ, **giữ lại**; bước gom cụm tự lọc |

---

## 7. Phân công và lịch (1 tuần)

| Người | Việc |
|---|---|
| A | Bước 1–3 + khung `pipeline.py` + `jobs/build_gold.py` + ghi Gold lên R2 |
| B | Bước 6 (NER, alias) + **gán tay 100 câu để đo chất lượng** |
| C | Bước 4 (khử trùng) + bước 5 (tách từ) |
| D | Bước 7–8 + bộ kiểm tra chất lượng sau mỗi bước, hiển thị lên trang trực quan hoá |

| Ngày | Mốc |
|---|---|
| 1 | Chốt 6 quyết định ở mục 6; dựng khung code và test |
| 2–3 | Bước 1–5 chạy được trên toàn kho, có số liệu kiểm tra |
| 4 | Bước 6–7, gán tay 100 câu đo NER |
| 5 | Bước 8, ghi Gold, thêm tab hiển thị lên trang |
| 6–7 | Xem tay mẫu, chỉnh ngưỡng, viết lại tài liệu hợp đồng cho lớp Gold |

---

## 8. Điều tiền xử lý KHÔNG giải quyết được

Dữ liệu hiện tại bị **giới hạn khoảng 500 bài mỗi chuyên mục**, nên phần lớn các ngày mỗi báo chỉ có vài bài. Không phép chuẩn hoá nào tạo ra được bài mà crawler chưa lấy.

Vì vậy nên làm **song song**: một người sửa crawler sang **cào theo ngày** (qua sitemap), trong khi ba người còn lại xây pipeline tiền xử lý trên dữ liệu hiện có. Khi dữ liệu dày hơn, chỉ cần chạy lại pipeline — mất khoảng 15 phút.
