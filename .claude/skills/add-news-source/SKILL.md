---
name: add-news-source
description: >-
  Thêm một báo mới vào crawler hoặc backfill thêm một khoảng thời gian cho một báo.
  Use when: thêm nguồn tin, khảo sát robots.txt/sitemap/RSS, chạy lát cắt thử,
  backfill, báo bị chặn hoặc sitemap thay đổi.
argument-hint: '[tên báo hoặc domain]'
---

# Thêm một nguồn tin

Làm **đúng thứ tự**. Chưa qua bước kiểm tra chất lượng thì **không được backfill**.

## 1. Khảo sát (không tải bài nào)

- Đọc `robots.txt`: có `Disallow` cho User-Agent của mình không, có `Crawl-delay` không.
- Tìm sitemap (dòng `Sitemap:` trong robots.txt), xác định cách chia file: theo ngày, 5 ngày, tháng, hay theo phần.
- Tải thử **một** file sitemap con. Nhận về HTML thay vì XML → **dừng, báo người dùng**. Không đổi User-Agent giả làm trình duyệt để vượt chặn.
- Ghi kết quả vào `configs/sources.yaml`.

## 2. Lát cắt 12 bài với backend local

`LAKE_BACKEND=local`, một file sitemap, `limit=12`, `delay ≥ 2` giây.

## 3. Kiểm tra chất lượng — cổng chặn

```sql
SELECT count(*),
       count(*) FILTER (WHERE title IS NULL)        AS thieu_title,
       count(*) FILTER (WHERE published_at IS NULL) AS thieu_ngay,
       count(*) FILTER (WHERE section_raw IS NULL)  AS thieu_chuyen_muc,
       median(n_words)
FROM read_parquet('data/lake/silver/**/*.parquet')
WHERE source_id = '<source>';
```

Đạt khi: không thiếu tiêu đề và ngày đăng, **và** đã mở 3 bài ngẫu nhiên so với trang thật
(thân bài không lẫn quảng cáo, mục "Tin liên quan").

## 4. Lưu HTML mẫu làm test

5 bài vào `tests/fixtures/html/<source>/`, gồm ít nhất 1 ca xấu. Viết test theo skill `tdd`.

## 5. Backfill

Chỉ khi người dùng đồng ý. Chạy trong `tmux`, ước lượng thời gian trước (`số bài × delay`) và báo cho người dùng.
Mỗi người chỉ backfill **báo mình phụ trách**.

## Bẫy đã biết (khảo sát 15/09/2026)

| Báo | Bẫy |
|---|---|
| Thanh Niên | Không có — có JSON-LD đầy đủ, sitemap 5 ngày |
| Tuổi Trẻ | `lastmod` ghi 2011-01-01 — lọc theo **tên file**, không theo `lastmod` |
| Dân Trí | Sitemap có **BOM**; chỉ mục dừng ở **tháng 7/2026**; `Crawl-delay: 1` |
| VietnamNet | Mỗi phần tối đa **1.000 URL** — duyệt hết các phần của tháng |
| VnExpress | Sitemap **302 về trang chủ**; robots chặn đích danh `Scrapy` — chỉ dùng RSS |
