---
name: data-lake
description: >-
  Quy ước đọc/ghi data lake trên Cloudflare R2 (bucket event-lake). Use when: ghi hoặc đọc
  Bronze/Silver/Gold/snapshots, đặt tên key, đổi schema, xuất snapshot, dọn dữ liệu,
  truy vấn bằng DuckDB, xử lý file .env hoặc khoá R2.
---

# Data lake — quy ước bắt buộc

## Cấu trúc key

```
bronze/articles/source=<báo>/dt=<ngày CÀO>/<url_hash>__<YYYYMMDDTHHMMSS>.html.gz
bronze/{sitemaps,rss,most_read}/source=<báo>/dt=<ngày cào>/...
silver/articles/v=<parser_version>/source=<báo>/dt=<ngày ĐĂNG>/part-<uuid>.parquet
gold/<loại>/model=<model_version>/...
snapshots/<tên>_v<n>/*.parquet + MANIFEST.json
models/<tên>/<phiên bản>/...
_tmp/                      # tự xoá sau 7 ngày
```

- Chỉ dùng chữ thường, số, `-`, `_`, `=`, `/`. **Không dấu cách, không dấu tiếng Việt.**
- `dt` ở Bronze là **ngày cào**, ở Silver là **ngày đăng**.
- Tên file Silver phải **duy nhất** (uuid). Đặt theo số thứ tự hoặc số dòng sẽ trùng tên và **đè mất dữ liệu**.
- Một file Parquet cho mỗi báo mỗi ngày. Không ghi mỗi bài một file.

## Bất biến và phiên bản

- **Bronze không sửa, không xoá, không ghi đè.** Cào lại → file mới có timestamp khác.
- Đổi logic tách bài → **tăng `v=`**, ghi sang thư mục mới, giữ bản cũ.
- R2 **không có versioning**: xoá là mất vĩnh viễn. Không chạy lệnh xoá khi người dùng chưa xác nhận.

## Ghi đồng thời

- R2 đảm bảo mỗi object ghi nguyên vẹn (last writer wins), nhưng **không có khoá giữa nhiều object**.
- Mỗi người chỉ ghi vào vùng `source=` của báo mình. Khi đọc, khử trùng theo `url_hash`:
  ```sql
  SELECT * FROM (
    SELECT *, row_number() OVER (PARTITION BY url_hash ORDER BY parser_version DESC) AS rn
    FROM read_parquet('r2://event-lake/silver/articles/**/*.parquet')
  ) WHERE rn = 1;
  ```

## Đọc bằng DuckDB

```python
con.execute("INSTALL httpfs; LOAD httpfs;")
con.execute(f"""CREATE OR REPLACE SECRET lake (TYPE r2,
    KEY_ID '{os.environ["R2_ACCESS_KEY_ID"]}', SECRET '{os.environ["R2_SECRET_ACCESS_KEY"]}',
    ACCOUNT_ID '{os.environ["R2_ACCOUNT_ID"]}');""")
```
Bí mật loại `r2` chỉ dùng được với đường dẫn `r2://`. Nhóm ML đọc `snapshots/`, không đọc `silver/` đang được ghi.

## Bí mật

- Không đọc, in, `cat` file `.env`. Kiểm tra biến → chỉ in độ dài.
- Không để khoá trong notebook; dùng Colab Secrets / Kaggle Secrets.
