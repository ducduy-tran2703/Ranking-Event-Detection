# Hợp đồng dữ liệu

> Mô tả **chính xác** từng trường mà crawler phải ghi và người đọc được phép tin vào.
> Crawler thay đổi trường nào → sửa file này **trong cùng Pull Request**.
> Cột "Đang có" là ảnh chụp dữ liệu thật lúc 16:30 ngày 19/09/2026 (4 nguồn, 18.972 bài).
> Số hiện tại: xem tab **Chất lượng** của trang kiểm soát.

## Bản ghi bài báo — lớp Silver

Mỗi dòng trong file `silver/<source>/*.jsonl` là một đối tượng JSON:

| Trường | Kiểu | Bắt buộc | Quy tắc | Đang có |
|---|---|---|---|---|
| `article_id` | chuỗi 64 ký tự hex | ✅ | **`sha256(url)`**. Là khoá duy nhất của bài | 100% · tuoitre khớp `sha256(url)` 5.447/5.447 bài; 3 nguồn còn lại khớp 60/60 bài mẫu |
| `url` | chuỗi | ✅ | URL đầy đủ, bắt đầu bằng `https://` | 100% · không trùng |
| `source` | chuỗi | ✅ | Tên báo, **viết thường, không dấu**: `tuoitre`, `vnexpress`, `vietnamnet`, `baochinhphu` | 100% · ⚠️ baochinhphu đang ghi `BAOCHINHPHU` |
| `category` | chuỗi | ✅ | Tên chuyên mục **nguyên văn trên trang báo** | 100% · mỗi báo 9–10 chuyên mục, 13 tên chuyên mục khác nhau trên toàn bộ dữ liệu |
| `title` | chuỗi | ✅ | Tiêu đề, đã bỏ khoảng trắng thừa | 100% |
| `sapo` | chuỗi | ✅ | Đoạn tóm tắt đầu bài | 100% |
| `author` | chuỗi \| `null` | — | Không có thì ghi `null`, **không ghi chuỗi rỗng** | tuoitre, vietnamnet 100% · vnexpress 93,4% · baochinhphu 72,6% |
| `published_at` | chuỗi ISO 8601 | ✅ | **Bắt buộc có múi giờ**: `2026-09-16T07:07:00+07:00` | 100% · đều có `+07:00` |
| `content_text` | chuỗi | ✅ | Thân bài dạng văn bản thuần, không HTML | tuoitre, vietnamnet, vnexpress 100% · baochinhphu 99,5% |

Trường không có trong bảng này được **bỏ qua** khi đọc.

## Người đọc tự chuẩn hoá những gì

Trang kiểm soát (`src/eventrank/lake/reader.py`) xử lý thêm khi nạp, để dữ liệu hơi lệch chuẩn vẫn dùng được:

| Xử lý | Vì sao |
|---|---|
| `source` → viết thường | baochinhphu đang ghi hoa |
| `author` rỗng → `null` | Để đếm "thiếu tác giả" cho đúng |
| `published_at` → thời điểm có múi giờ, nhóm theo **giờ Việt Nam** | Bài đăng 0h–7h sáng không bị xếp sang ngày hôm trước |
| Tính thêm `n_words`, `title_words` | Phát hiện thân bài rỗng hoặc quá ngắn |

Việc chuẩn hoá phía người đọc chỉ là lưới an toàn. **Crawler vẫn phải ghi đúng hợp đồng.**

## Ngưỡng chất lượng

Trang kiểm soát dùng các ngưỡng sau (tab **Chất lượng**):

| Lỗi | Định nghĩa |
|---|---|
| Thiếu tác giả | `author` là `null` |
| Thân bài rỗng | `content_text` rỗng |
| Thân bài quá ngắn | 1–79 từ |
| Ngày đăng hỏng | `published_at` không đọc được thành thời điểm |
| Ngày ở tương lai | Muộn hơn hiện tại quá 1 giờ |
| URL trùng / `article_id` trùng | Xuất hiện nhiều hơn một lần |

## Vấn đề đã biết của dữ liệu hiện tại

| Vấn đề | Ảnh hưởng | Cần sửa ở |
|---|---|---|
| **Mỗi chuyên mục bị giới hạn khoảng 500 bài** (lớn nhất: tuoitre 587, vietnamnet 500, baochinhphu 499, vnexpress 462) | Trung vị chỉ 2–18 bài/báo/ngày, trong khi báo thật đăng 200–300 bài/ngày. Không đủ dày để gom sự kiện đa nguồn | Crawler: cào **theo ngày** qua sitemap thay vì theo chuyên mục |
| Khoảng thời gian lệch nhau giữa các báo (baochinhphu từ 2023, vnexpress từ 20/05/2026) | Chỉ từ 20/05/2026 trở đi mới có đủ 4 báo | Crawler: backfill cùng một khoảng thời gian cho mọi báo |
| `source` của baochinhphu viết hoa | Đã được người đọc chuẩn hoá | Crawler baochinhphu |
| baochinhphu thiếu tác giả 27,4% | Chấp nhận được nếu trang báo thật không ghi tác giả | Kiểm tra lại parser baochinhphu |

## Nguồn mẫu

**tuoitre** đạt hợp đồng 100% (đủ mọi trường, `source` viết thường, `published_at` có múi giờ, `article_id = sha256(url)`). Khi viết crawler cho báo mới, lấy crawler Tuổi Trẻ làm mẫu.
