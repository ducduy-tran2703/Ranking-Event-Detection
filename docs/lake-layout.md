# Cấu trúc kho dữ liệu (lake layout)

> **Hợp đồng** giữa người ghi dữ liệu (crawler) và người đọc (trang kiểm soát, pipeline ML).
> Đổi cấu trúc key hay định dạng file → sửa file này **trong cùng Pull Request**.
> Schema từng trường của một bài báo: xem [data-contracts.md](data-contracts.md).

## Hiện trạng (ảnh chụp lúc 16:30 ngày 19/09/2026)

> Số liệu dưới đây **thay đổi mỗi khi có người đẩy dữ liệu mới**. Muốn biết số hiện tại, mở trang kiểm soát:
> tab **Tổng quan** và tab **File nguồn**.

| | |
|---|---|
| Nhà cung cấp | Cloudflare R2 |
| Bucket | `vietnam-news-datalake` |
| Lớp đang có | **Chỉ có Silver** |
| Định dạng | JSONL — mỗi dòng một bài báo, mã hoá UTF-8 |
| Tổng | 4 nguồn · 18.972 bài · 97,5 MB |

```
vietnam-news-datalake/
└── silver/
    ├── baochinhphu/
    │   └── silver_baochinhphu.jsonl     4.395 bài · 29,1 MB · 12/01/2023 → 16/09/2026
    ├── tuoitre/
    │   └── articles_silver.jsonl        5.447 bài · 25,7 MB · 16/05/2026 → 19/09/2026
    ├── vietnamnet/
    │   └── articles_silver.jsonl        4.645 bài · 22,2 MB · 22/04/2026 → 16/09/2026
    └── vnexpress/
        └── articles_silver.jsonl        4.485 bài · 20,5 MB · 20/05/2026 → 16/09/2026
```

Có thêm một object rỗng tên `silver/baochinhphu/` — là "thư mục ảo" do công cụ upload tạo ra, không chứa dữ liệu, có thể bỏ qua.

### Quy ước đang áp dụng

- Mỗi báo một thư mục `silver/<source>/`, tên thư mục viết **thường, không dấu**.
- Người đọc lấy toàn bộ bằng một mẫu: `silver/*/*.jsonl` (biến `LAKE_SILVER_GLOB`).
- **Mỗi người chỉ ghi vào thư mục của báo mình phụ trách.**

### Điểm chưa thống nhất

| Vấn đề | Đề xuất |
|---|---|
| Tên file khác nhau: `silver_baochinhphu.jsonl` so với `articles_silver.jsonl` | Thống nhất thành `articles_silver.jsonl` |
| Mỗi báo **một file duy nhất**, cào thêm là ghi đè cả file | Rủi ro mất dữ liệu nếu lần ghi sau lỗi giữa chừng — xem "Hướng tới" |
| **Không có Bronze** (HTML gốc) | Phát hiện lỗi tách bài thì phải cào lại từ đầu |

## Hướng tới (chưa làm)

Khi đưa crawler vào repo, chuyển dần sang cấu trúc này. **Người đọc không phải sửa code**, chỉ đổi `LAKE_SILVER_GLOB`.

```
bronze/articles/source=<báo>/dt=<ngày CÀO>/<article_id>__<YYYYMMDDTHHMMSS>.html.gz
silver/articles/source=<báo>/dt=<ngày ĐĂNG>/part-<uuid>.jsonl
snapshots/<tên>_v<n>/…  + MANIFEST.json
models/<tên>/<phiên bản>/…
```

| Thay đổi | Lý do |
|---|---|
| Thêm **Bronze** — HTML gốc, không bao giờ sửa hay xoá | Sửa parser xong chạy lại được mà không cần cào lại |
| Chia Silver theo **ngày đăng**, nhiều file nhỏ | Thêm dữ liệu mới là **thêm file**, không ghi đè file cũ |
| Tên file có **uuid** | Hai lần ghi không bao giờ trùng tên rồi đè lên nhau |
| `snapshots/` đóng băng | Nhóm ML thí nghiệm trên dữ liệu không đổi, kết quả tái lập được |

Có thể giữ **JSONL** hoặc chuyển sang Parquet. Với khoảng 100 MB hiện nay, JSONL vẫn đủ nhanh (nạp toàn bộ mất vài giây). Chỉ cân nhắc Parquet khi dữ liệu vượt vài trăm MB.

## Quy tắc an toàn

- R2 **không có versioning**: xoá hay ghi đè là mất vĩnh viễn. Không chạy lệnh xoá khi chưa được cả nhóm đồng ý.
- Trang kiểm soát và người chỉ đọc dùng **khoá Object Read only**. Chỉ máy chạy crawler giữ khoá có quyền ghi.
