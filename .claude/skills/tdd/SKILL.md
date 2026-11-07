---
name: tdd
description: >-
  Viết test theo quy trình TDD (red-green-refactor) cho dự án Ranking-Event-Detection
  (Python + pytest). Use when: thêm test, sửa parser/crawler, sửa bug cần test tái hiện,
  thêm hàm vào src/eventrank, kiểm tra một báo mới bằng HTML mẫu.
argument-hint: '[đường dẫn module hoặc mô tả hành vi cần test]'
---

# TDD cho Ranking-Event-Detection

Test viết **trước**, chạy thật, và kết quả thật được dán ra cho người dùng.

## Quy trình bắt buộc

1. **RED** — viết test mô tả hành vi mong muốn. Chạy, xác nhận nó **fail đúng lý do**
   (assertion sai, không phải lỗi import). Dán output fail.
2. **GREEN** — viết code **tối thiểu** để pass. Không thêm tính năng ngoài phạm vi test.
3. **REFACTOR** — dọn code khi đã xanh, chạy lại.

**Không bao giờ sửa test cho khớp với bug.** Sửa bug thì test phải tái hiện bug (fail) trước.

## Quy ước

- Test nằm trong `tests/`, **phản chiếu cấu trúc** `src/` và `apps/`:
  `src/eventrank/lake/reader.py` → `tests/lake/test_reader.py`, `apps/api/main.py` → `tests/api/test_api.py`.
- Tên hàm test mô tả hành vi bằng tiếng Việt không dấu hoặc tiếng Anh rõ nghĩa:
  `test_tra_ve_none_khi_khong_co_json_ld`.
- **Test không được gọi mạng.** HTML và sitemap mẫu lưu trong `tests/fixtures/`:
  ```
  tests/fixtures/html/<source>/<mô-tả>.html
  tests/fixtures/sitemaps/<source>_<mô-tả>.xml
  ```
  Mỗi báo có tối thiểu 5 bài mẫu, gồm cả ca xấu: bài video, bài quá ngắn, bài thiếu JSON-LD.
- **Test không được chạm vào R2.** Dữ liệu Silver mẫu nằm ở `tests/fixtures/silver/<source>/*.jsonl`;
  fixture `store` trong `tests/conftest.py` đã nạp sẵn. Test API dùng `TestClient(create_app(store))`.
- Dữ liệu mẫu phải chứa **đúng các lỗi đã gặp trong dữ liệu thật** (tên nguồn viết hoa, thiếu tác giả,
  thân bài rỗng, URL trùng) — nếu không, test không bảo vệ được gì.
- Ca biên đã biết từ dữ liệu thật — luôn có test:
  - sitemap có BOM ở đầu (Dân Trí)
  - trang HTML trả về thay cho sitemap XML (VnExpress chuyển hướng) → phải ném lỗi
  - `datePublished` có múi giờ `+07:00` → lưu đúng UTC
  - chuỗi tiếng Việt dạng NFD → chuẩn hoá về NFC

## Lệnh chạy

```bash
uv run pytest tests/lake/test_reader.py -q       # một file
uv run pytest tests/lake -q                      # một module
uv run pytest -q                                 # toàn bộ
uv run pytest -q -k "bom or redirect"            # lọc theo tên
```

## Checklist trước khi báo xong

- [ ] Test đã **fail trước** đúng lý do, rồi mới pass.
- [ ] Không sửa test để né bug.
- [ ] Không có lời gọi mạng, không chạm R2.
- [ ] Đã chạy đúng lệnh và **dán kết quả thật**.
