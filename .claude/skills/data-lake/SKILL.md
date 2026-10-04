---
name: data-lake
description: >-
  Quy ước đọc/ghi data lake trên Cloudflare R2 (bucket vietnam-news-datalake). Use when: đọc
  hoặc ghi dữ liệu Silver, đổi cấu trúc thư mục hay schema, truy vấn bằng DuckDB, khử trùng lặp,
  xuất snapshot, dọn dữ liệu, xử lý file .env hoặc khoá R2.
---

# Data lake — quy ước bắt buộc

**Nguồn sự thật:** `docs/lake-layout.md` (cấu trúc) và `docs/data-contracts.md` (schema từng trường).
Skill này chỉ tóm tắt. Hai file đó mâu thuẫn với skill → tin hai file đó, và sửa skill.

## Hiện trạng

```
vietnam-news-datalake/silver/<source>/<tên>.jsonl     # JSONL, UTF-8, mỗi dòng một bài
```

- 6 nguồn: `baochinhphu`, `baonhandan`, `thanhnien`, `tuoitre`, `vietnamnet`, `vnexpress` (xem `docs/lake-layout.md`). Có **Silver** + **Gold** (`gold/gold_data.jsonl`: NER, không chứa văn bản) + nhãn yếu v1 (`weak_label_NguyenDinhHieu/`). Chưa có Bronze.
- Người đọc lấy toàn bộ bằng mẫu `silver/*/*.jsonl` (biến `LAKE_SILVER_GLOB`).
- **Mỗi báo một file.** Ghi lại file đó là **thay thế toàn bộ** dữ liệu của báo.

## Đọc

Cách chuẩn trong code: dùng `eventrank.lake.reader.SilverStore` — đã xử lý múi giờ, chuẩn hoá `source`, đếm số từ.

Truy vấn nhanh bằng DuckDB:

```python
import os, duckdb
con = duckdb.connect()
con.execute("INSTALL httpfs; LOAD httpfs; SET GLOBAL TimeZone = 'Asia/Ho_Chi_Minh';")
con.execute(f"""CREATE OR REPLACE SECRET lake (TYPE r2,
    KEY_ID '{os.environ["R2_ACCESS_KEY_ID"]}', SECRET '{os.environ["R2_SECRET_ACCESS_KEY"]}',
    ACCOUNT_ID '{os.environ["R2_ACCOUNT_ID"]}');""")
con.sql("""
    SELECT lower(source) AS source, count(*)
    FROM read_json('r2://vietnam-news-datalake/silver/*/*.jsonl', format = 'newline_delimited')
    GROUP BY 1
""").show()
```

- Bí mật loại `r2` **chỉ dùng được với đường dẫn `r2://`**.
- Đặt múi giờ bằng `SET GLOBAL`: mỗi `cursor()` là một phiên mới, thiết lập mức phiên **không được kế thừa** → cursor quay về UTC và bài đăng 0h–7h sáng bị xếp sang ngày hôm trước.
- `source` của baochinhphu đang viết hoa → luôn `lower(source)` khi nhóm theo nguồn.

## Ghi

- Mặc định ghi vào máy (`LAKE_BACKEND=local`). **Chỉ ghi lên R2 khi người dùng yêu cầu rõ.**
- Mỗi bản ghi phải đúng `docs/data-contracts.md`; đặc biệt `article_id = sha256(url)`, `source` viết thường, `published_at` có múi giờ.
- Mỗi người chỉ ghi vào `silver/<source>/` của **báo mình phụ trách**.
- Ghi file mới ra tên tạm rồi mới thay thế, để lần ghi lỗi giữa chừng không làm hỏng file đang có.

## Khử trùng lặp

Khoá của bài là `article_id` (= `sha256(url)`):

```sql
SELECT * FROM (
  SELECT *, row_number() OVER (PARTITION BY article_id ORDER BY published_at DESC) AS rn
  FROM read_json('r2://vietnam-news-datalake/silver/*/*.jsonl', format = 'newline_delimited')
) WHERE rn = 1;
```

Bài **gần trùng** giữa các báo (cùng tin, khác URL) **không phải lỗi** — đó là tín hiệu chính để gom sự kiện. Không xoá.

## An toàn

- R2 **không có versioning**: xoá hay ghi đè là mất vĩnh viễn. Không chạy lệnh xoá hay ghi đè khi người dùng chưa xác nhận.
- Khi có lớp Bronze: **không sửa, không xoá, không ghi đè**.
- Không đọc, in, `cat` file `.env`. Kiểm tra biến → chỉ in độ dài.
- Không để khoá trong notebook; dùng Colab Secrets / Kaggle Secrets.
