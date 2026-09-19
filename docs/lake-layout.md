# Cấu trúc kho dữ liệu (lake layout)

> **Hợp đồng** giữa người ghi dữ liệu (crawler) và người đọc (trang kiểm soát, pipeline ML).
> Đổi cấu trúc key hay định dạng file → sửa file này **trong cùng Pull Request**.
> Schema từng trường của một bài báo: xem [data-contracts.md](data-contracts.md).

## Hiện trạng (ảnh chụp 17:30 ngày 19/09/2026)

> Danh sách nguồn và số bài **thay đổi thường xuyên**. Số hiện tại: xem tab **Tổng quan** và **Nguồn dữ liệu**
> của trang trực quan hoá (`make dev` → http://127.0.0.1:5173).

| | |
|---|---|
| Nhà cung cấp | Cloudflare R2 |
| Bucket | `vietnam-news-datalake` |
| Lớp đang có | **Chỉ có Silver** |
| Định dạng | JSONL — mỗi dòng một bài báo, mã hoá UTF-8 |
| Lúc chụp | 4 nguồn · 18.124 bài · 96,6 MB |

```
vietnam-news-datalake/
└── silver/
    ├── baochinhphu/article_silver.jsonl     4.477 bài · 29,6 MB
    ├── baodantri/silver_nhandan.jsonl       4.517 bài · 24,2 MB   ⚠ tên thư mục, tên file và
    │                                                                  trường source không khớp nhau
    ├── vietnamnet/articles_silver.jsonl     4.645 bài · 22,2 MB
    └── vnexpress/articles_silver.jsonl      4.485 bài · 20,5 MB
```

⚠️ **Xoá hay ghi đè file trên R2 là mất vĩnh viễn** (R2 không có versioning). Đây là thao tác bình thường khi
nhóm chủ động thay dữ liệu, nhưng hãy chắc **bản gốc còn trên máy người cào** trước khi xoá trên kho.

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
