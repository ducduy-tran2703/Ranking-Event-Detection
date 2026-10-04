# Định nghĩa "sự kiện": các phương án để nhóm chọn

> **Mục đích:** chốt *một* định nghĩa "sự kiện" dùng chung cho mọi phần của đề tài: gán nhãn yếu, tập vàng, gom cụm,
> đặt tên, xếp hạng xu hướng. Chưa chốt thì mỗi phần hiểu một kiểu, và các con số đánh giá không so được với nhau.
>
> **Cách dùng:** đọc mục 2 (các phương án), mục 3 (ca biên có ví dụ thật), rồi điền **phiếu quyết định ở mục 6**.
> Mọi ví dụ đều lấy từ dữ liệu thật (tháng 8–9/2026), trong đó có nhiều cặp mà nhãn yếu đang gán sai hoặc mà Claude
> và luật bất đồng.

---

## 1. Vì sao phải chốt

| Phần của đề tài | Định nghĩa ảnh hưởng thế nào |
|---|---|
| Nhãn yếu (`weak_labels`) | quyết định cặp nào là **dương**, cặp nào là **negative khó**, cửa sổ thời gian (`POS_MAX_HOURS`), các luật phủ quyết |
| Tập vàng | người gán và Claude phải gán theo cùng một chuẩn; nếu không, κ thấp và precision/recall vô nghĩa |
| Gom cụm | cụm to hay nhỏ, gộp hay tách |
| Đặt tên (5–10 từ) | sự kiện quá rộng thì không đặt tên ngắn được ("Xung đột Nga–Ukraine" thì không phải tin) |
| Xu hướng | đếm "độ nóng" trên đơn vị nào: một vụ việc hay cả câu chuyện |

**Hiện trạng:** nhãn yếu v1–v3 và mọi lần Claude gán mù đang ngầm dùng **phương án B** (mục 2.2). Đổi sang phương án khác
thì phải sửa pipeline và gán lại audit (mục 5).

---

## 2. Các phương án

Bốn mức từ mịn đến thô. Trong tài liệu Topic Detection and Tracking (TDT, chuẩn đánh giá kinh điển của bài toán
này), **event** = *"một việc xảy ra tại một thời điểm và địa điểm cụ thể"* (gần phương án A), còn **topic** = *"một
sự kiện gốc cùng các sự kiện liên quan trực tiếp"* (gần phương án C).

### 2.1 Phương án A: Hành động đơn lẻ

> **Một sự kiện = một việc cụ thể, xảy ra tại một thời điểm và địa điểm.**

- "U23 Việt Nam thắng U23 Kuwait" và "U23 Việt Nam gặp U23 Philippines" → **2 sự kiện**.
- Lễ đón Tổng Bí thư tại Australia (11/8) và tuyên bố chung Việt Nam–Australia (12/8) → **2 sự kiện**.
- Bài nhận định trước trận và bài kết quả **cùng một trận** → **2 sự kiện** (một sắp xảy ra, một đã xảy ra).

| Ưu | Nhược |
|---|---|
| Rõ ràng, ít tranh cãi; người gán đồng thuận cao | Rất nhiều cụm nhỏ (1–3 bài), nhiều tin chỉ một báo đưa → khó thấy "nhiều báo cùng đưa" |
| Đặt tên ngắn dễ | Bảng xu hướng vụn: 5 mục khác nhau cho một chuyến thăm |
| Nhãn yếu đạt precision cao (luật hiện tại hợp nhất với kiểu này) | Ít cặp dương khác báo → ít dữ liệu train |

### 2.2 Phương án B: Sự kiện tin tức (đang dùng)

> **Một sự kiện = một việc cụ thể CÙNG các tin tiếp nối trực tiếp của chính việc đó trong vài ngày** (phản ứng,
> cập nhật, diễn biến ngay sau).

- "X bị bắt" và "X bị khởi tố" trong vài ngày → **1 sự kiện**.
- Nhận định trước trận và kết quả **cùng một trận** → **1 sự kiện**.
- Lễ đón, hội đàm, tuyên bố chung **cùng một chuyến thăm** → **1 sự kiện**.
- Hai trận khác nhau của cùng một giải → **2 sự kiện**.
- Giá vàng ngày 16/9 và ngày 14/9 → **2 sự kiện**.

| Ưu | Nhược |
|---|---|
| Khớp với cách người đọc nghĩ về "một tin" | Ranh giới "vài ngày" và "tiếp nối trực tiếp" cần ví dụ rõ |
| Cụm vừa phải; nhiều báo cùng đưa → tín hiệu xu hướng tốt | Chuyến thăm/hội nghị kéo dài 4–7 ngày vượt cửa sổ 72h hiện tại |
| Đặt tên 5–10 từ được ("Tổng Bí thư thăm cấp Nhà nước Australia") | Còn vùng xám: bài phân tích chung với bài tin cụ thể |

### 2.3 Phương án C: Câu chuyện (story)

> **Một sự kiện = toàn bộ diễn biến của một câu chuyện đang tiếp diễn**, không giới hạn số ngày.

- Mọi bài về ASIAD 2026 (khai mạc, từng trận, huy chương) → **1 sự kiện**.
- Toàn bộ vụ án Mường Thanh, từ khởi tố tới xét xử cách nhau vài tuần → **1 sự kiện**.
- Điện đàm Trump–Putin, đặc phái viên Mỹ tới Kyiv, lệnh ngừng bắn 3 ngày → **1 sự kiện**.

| Ưu | Nhược |
|---|---|
| Cụm lớn, nhiều báo; xu hướng ổn định | Không còn là "tin": tên kiểu "ASIAD 2026" hay "Xung đột Nga–Ukraine" thì vô ích với người đọc |
| Recall nhãn yếu tăng mạnh (nhiều cặp hiện bị coi là "không chắc" sẽ thành dương) | Gần "chủ đề" → mô hình học phân biệt chủ đề, việc TF-IDF đã làm tốt → giá trị fine-tune giảm |
| | Cụm không bao giờ "đóng" → khó gom cụm trực tuyến theo cửa sổ thời gian |

### 2.4 Phương án D: Chủ đề (loại trừ, chỉ để tham chiếu)

> Mọi bài cùng chủ đề ("giá vàng", "điểm chuẩn đại học 2026", "AI trong giáo dục").

Đây **không phải** sự kiện; ghi ra để thấy ranh giới dưới. Mô hình ngữ nghĩa zero-shot (MiniLM) nghiêng về mức này. Đó
là lý do tín hiệu ngữ nghĩa không được đứng một mình (58% đúng khi đứng một mình).

### 2.5 Phương án E: Hai tầng (B làm đơn vị, C làm nhóm cha)

> **Đơn vị gom cụm và đặt tên = sự kiện tin tức (B).** Các sự kiện B thuộc cùng một câu chuyện được **nhóm thêm**
> thành "câu chuyện" (C), dùng cho trang chi tiết hoặc bảng xu hướng theo chủ đề.

- Nhãn yếu và tập vàng gán theo B. Thêm một cột "câu chuyện" (tuỳ chọn) để gom các sự kiện B.
- Bảng xu hướng hiển thị sự kiện B; có thể gộp thành câu chuyện khi nhiều sự kiện B cùng nóng.
- Tốn thêm công gán (một cột nữa), nhưng không làm hỏng định nghĩa B.

---

## 3. Ca biên: mỗi phương án gán thế nào

Ký hiệu: **1** = cùng sự kiện, **0** = khác. Các cặp đều có trong dữ liệu.

| # | Cặp bài (rút gọn) | A | **B** | C | Ghi chú |
|---|---|---|---|---|---|
| 1 | "Khẩn trương xử lý vụ nghi ngộ độc bánh mì ở Gia Lai" (Nhân Dân) ↔ "Cục ATTP yêu cầu điều tra vụ ngộ độc bánh mì ở Gia Lai" (Tuổi Trẻ), cách 1 giờ | 1 | **1** | 1 | rõ ràng ở mọi mức |
| 2 | "U23 Việt Nam: Kuwait mới là nơi bắt đầu giấc mơ Asiad" ↔ "U23 Việt Nam tập trung cho trận gặp Philippines" | 0 | **0** | 1 | hai trận khác nhau |
| 3 | Nhận định "MU vs Ipswich" ↔ "Man Utd đại thắng nhờ hat-trick của Fernandes" (cùng trận) | 0 | **1** | 1 | trước và sau cùng một trận |
| 4 | "Lễ đón Tổng Bí thư thăm cấp Nhà nước Australia" (11/8) ↔ "Tuyên bố chung Việt Nam–Australia" (12/8) | 0 | **1** | 1 | cùng chuyến thăm |
| 5 | "Tổng Bí thư sắp thăm cấp Nhà nước tới Australia" ↔ "Australia hỗ trợ Việt Nam thành trung tâm khoa học" (cách 129 giờ) | 0 | **1?** | 1 | cùng chuyến thăm nhưng cách hơn 5 ngày, **vượt cửa sổ 72h** |
| 6 | "Truy tố Chủ tịch Mường Thanh vụ 519 căn hộ" ↔ "Truy tố ông Lê Thanh Thản tội lừa dối khách hàng" | 1 | **1** | 1 | cùng một quyết định truy tố |
| 7 | "Hôm nay xét xử tài xế xe tải gây tai nạn khiến nữ sinh tử vong" ↔ "Mối quan hệ cựu phó thủ trưởng điều tra với tài xế" (cách 7 ngày) | 0 | **?** | 1 | cùng vụ việc, khía cạnh khác, cách 7 ngày |
| 8 | "Giá vàng ngày 16/9: vàng miếng bật tăng" ↔ "Giá vàng ngày 14/9: ít biến động" | 0 | **0** | 0 | chuỗi bài theo ngày → luôn khác |
| 9 | "Lịch thi đấu bóng đá hôm nay 13/9" ↔ "Kết quả bóng đá hôm nay 13/9" | 0 | **0** | 0 | bài tổng hợp nhiều trận |
| 10 | "Điểm chuẩn ĐH Thủy lợi 2026" ↔ "ĐH Điện lực công bố điểm chuẩn 2026" | 0 | **0** | 0 | cùng khuôn tin, khác đối tượng (mức D) |
| 11 | Điện đàm Trump–Putin (8/9) ↔ đặc phái viên Mỹ lần đầu tới Kyiv | 0 | **0** | 1 | cùng câu chuyện, hai diễn biến khác |
| 12 | "Sắp xếp trường phường Xuân Hòa" ↔ "Phường Bảy Hiền sắp xếp 17 trường còn 8" | 0 | **0** | 0? | cùng chính sách, hai địa phương |
| 13 | "Bộ GD-ĐT dự kiến bỏ điểm cộng IELTS" ↔ "Vì sao Bộ GD-ĐT muốn bỏ quy định cho trường tự ra đề" | 1? | **1** | 1 | cùng một dự thảo quy chế tuyển sinh |
| 14 | "Bóng chuyền nữ ASIAD: Việt Nam 3-0 Hồng Kông" ↔ "Việt Nam 3-0 Qatar" | 0 | **0** | 1 | hai trận khác nhau |
| 15 | Bài phân tích "Nguy cơ Iran leo thang trả đũa" ↔ tin "Tổng thống Iran 'thách đấu' quân sự với Mỹ" | 0 | **0?** | 1 | bài phân tích chung với một phát ngôn cụ thể |
| 16 | "Tin tức thế giới 1-9: ông Trump nhận phán quyết có lợi; Ukraine…" (bài tổng hợp) ↔ tin riêng về một mục trong đó | 0 | **?** | ? | **bài tổng hợp nhiều tin**, xem mục 4.3 |
| 17 | "Vụ cháy nhà 5 người chết ở Tây Hồ" ↔ "Bí thư Hà Nội vào viện thăm nạn nhân vụ cháy" | 0? | **1** | 1 | phản ứng trực tiếp của cùng vụ việc |

Các ô **?** là chỗ định nghĩa B **chưa đủ rõ**. Phiếu quyết định (mục 6) hỏi đúng các chỗ này.

---

## 4. Các quy tắc phụ cần chốt, dù chọn phương án nào

### 4.1 Cửa sổ thời gian

| Lựa chọn | Hệ quả |
|---|---|
| ≤ 72 giờ (hiện tại) | Cặp 5 và 7 bị coi là khác sự kiện; precision cao, recall thấp với sự kiện nhiều ngày |
| ≤ 7 ngày | Bắt được chuyến thăm, hội nghị, phiên toà nhiều ngày; nguy cơ gộp nhầm các diễn biến khác nhau tăng |
| Theo loại sự kiện (ví dụ thể thao 48h, chuyến thăm/hội nghị theo lịch trình, vụ án 7 ngày) | Chính xác nhất nhưng phải phân loại sự kiện trước, phức tạp |

### 4.2 Chuỗi bài định kỳ

"Giá vàng hôm nay", "Lịch thi đấu hôm nay", "Chứng khoán ngày…", "Thời sự 24h…": mỗi ngày là **một sự kiện riêng**,
hay **loại khỏi** gom cụm vì không phải tin về một việc cụ thể?

### 4.3 Bài tổng hợp nhiều tin

"Tin tức thế giới 1-9", "Điểm tin sáng", "Kết quả bóng đá hôm nay": một bài nói về nhiều sự kiện.
- (a) Loại khỏi nhãn yếu và tập vàng.
- (b) Gán vào sự kiện chính (mục đầu tiên).
- (c) Cho phép một bài thuộc nhiều cụm (phức tạp cho gom cụm).

### 4.4 Bài phân tích, bình luận, bối cảnh

Ví dụ "Nguy cơ Iran leo thang", "Loạt diễn biến lạ trên thị trường vàng từ đầu năm". Thuộc sự kiện tin đang nóng, hay
không thuộc sự kiện nào?

### 4.5 Bài "sắp diễn ra" so với "đã diễn ra"

Thông báo trước ("sắp thăm", "chốt ngày tái đấu") và tin sau khi xảy ra: cùng sự kiện?

---

## 5. Hệ quả cho pipeline nếu chọn từng phương án

| Phương án | Sửa nhãn yếu | Gán lại audit | Ước lượng dữ liệu train |
|---|---|---|---|
| **A** | giảm `POS_MAX_HOURS` (khoảng 24–48h); thêm phủ quyết "thời điểm diễn ra khác nhau" | **có** (khoảng 15–20% cặp dương hiện tại thành âm) | giảm; precision tăng |
| **B (giữ)** | chỉ chốt các ô "?" ở mục 3 và quy tắc mục 4 | gán lại các cặp rơi vào ô "?" | như v3 |
| **B + cửa sổ 7 ngày** | tăng `POS_MAX_HOURS` lên 168h cho loại "chuyến thăm/hội nghị/vụ án"; phải đo lại precision | một phần | tăng nhẹ |
| **C** | bỏ phủ quyết khác trận/khác ngày; tăng cửa sổ; gom theo câu chuyện | **có**, nhiều | tăng mạnh; precision theo định nghĩa mới tăng, nhưng mô hình học "chủ đề" |
| **E (B + C)** | như B; thêm cột "câu chuyện" khi gán vàng | không (chỉ thêm cột) | như B |

---

## 6. Phiếu quyết định (nhóm điền)

**Ngày họp:** ____ · **Người tham dự:** ____

**Q1. Đơn vị "sự kiện" là gì?**
- [ ] A: hành động đơn lẻ
- [ ] B: sự kiện tin tức (hành động + tin tiếp nối trực tiếp)
- [ ] C: câu chuyện
- [ ] E: B làm đơn vị, C làm nhóm cha

**Q2. Cửa sổ thời gian cho "tin tiếp nối"?**
- [ ] ≤ 72 giờ
- [ ] ≤ 7 ngày
- [ ] theo loại sự kiện: ____

**Q3. Các ca biên ở mục 3** (ghi 1 hoặc 0):
- cặp 3 (trước/sau cùng trận) ___
- cặp 5 (chuyến thăm, cách 5 ngày) ___
- cặp 7 (vụ án, khía cạnh khác, 7 ngày) ___
- cặp 13 (cùng dự thảo) ___
- cặp 15 (phân tích ↔ tin) ___
- cặp 16 (bài tổng hợp) ___
- cặp 17 (phản ứng sau vụ việc) ___

**Q4. Chuỗi bài định kỳ** (mục 4.2):
- [ ] mỗi ngày một sự kiện
- [ ] loại khỏi gom cụm

**Q5. Bài tổng hợp nhiều tin** (mục 4.3):
- [ ] (a) loại
- [ ] (b) gán vào sự kiện chính
- [ ] (c) nhiều cụm

**Q6. Bài phân tích/bình luận** (mục 4.4):
- [ ] thuộc sự kiện tin đang nóng
- [ ] không thuộc sự kiện nào

**Q7. "Sắp diễn ra" và "đã diễn ra"** (mục 4.5):
- [ ] cùng sự kiện
- [ ] khác sự kiện

**Q8. 15–20 ví dụ chuẩn** (người phụ trách: ____): chọn từ mục 3 và từ các cặp lệch nhau khi chạy `make agreement`.
Đưa vào hướng dẫn gán nhãn cho người và cho Claude.

---

## 7. Gợi ý (không bắt buộc)

**Phương án E**, với các lựa chọn:
- B làm đơn vị;
- cửa sổ **theo loại**: mặc định 72h, chuyến thăm/hội nghị/phiên toà theo lịch trình của chính sự kiện;
- loại chuỗi bài định kỳ và bài tổng hợp khỏi gom cụm;
- bài phân tích **không** thuộc sự kiện;
- "sắp diễn ra" và "đã diễn ra" của cùng một việc là **cùng sự kiện**.

Lý do:
1. B là mức người đọc hiểu là "một tin", đặt tên 5–10 từ được, và là mức mà mọi phép đo hiện tại đang dùng: không mất
   công đã làm.
2. Lớp C đi kèm giải quyết đúng nhóm lỗi "cùng câu chuyện, khác diễn biến" (cặp 11) mà không làm cụm B phình ra.
3. Loại chuỗi định kỳ và bài tổng hợp xoá gọn một nhóm lỗi lớn của nhãn yếu (cặp 8, 9, 16), thay vì phải viết thêm
   luật phủ quyết.
4. Mô hình được train để phân biệt **sự kiện** chứ không phải **chủ đề**: đó là phần mà fine-tune có thể thắng TF-IDF.

Sau khi chốt, cần:
1. cập nhật hướng dẫn gán cho người (`human_label_100.csv`) và cho Claude;
2. chỉnh `POS_MAX_HOURS` và các luật trong `src/eventrank/weak_labels/lfs.py`;
3. gán lại các cặp rơi vào ô thay đổi;
4. đo lại bằng `evaluate.py`.

---

## 8. Phân tích chi tiết và xếp hạng

### 8.1 Tiêu chí đánh giá

| # | Tiêu chí | Vì sao quan trọng |
|---|---|---|
| T1 | **Dễ gán nhất quán** | Người với người, người với Claude phải đồng thuận (κ ≥ 0,7); nếu không, mọi số đo đều mất giá trị |
| T2 | **Nhãn yếu đạt precision ≥ 0,8** | Mốc của dự án; nhãn sai thì dạy mô hình sai |
| T3 | **Đủ dữ liệu train** (recall, số cặp dương khác báo) | Ít cặp dương thì fine-tune yếu |
| T4 | **Giá trị của fine-tune** | Mô hình phải học được thứ TF-IDF / mô hình zero-shot chưa làm được, nếu không thì phần ML không có lý do tồn tại |
| T5 | **Gom cụm khả thi** (trực tuyến, theo cửa sổ thời gian) | Cụm phải "đóng" được sau một thời gian |
| T6 | **Đặt tên 5–10 từ** | Yêu cầu đề tài |
| T7 | **Giá trị cho người dùng** (bảng xu hướng, thông báo) | Sản phẩm cuối |
| T8 | **Bảo vệ được trước hội đồng** | Có căn cứ trong tài liệu (TDT), dễ giải thích |
| T9 | **Chi phí chuyển đổi** từ hiện trạng | Thời gian còn lại của đồ án |

Thang điểm 1 (kém) đến 5 (tốt). Điểm dựa trên số đo thật nếu có, nếu không thì là ước lượng (ghi *ước*).

### 8.2 Phân tích từng phương án

#### A: Hành động đơn lẻ

| Tiêu chí | Điểm | Phân tích |
|---|---|---|
| T1 Dễ gán | **5** | Câu hỏi gần như có/không: "có phải cùng một việc, cùng một lúc không?". Ít vùng xám |
| T2 Precision | **5** | Luật hiện tại vốn đã thiên về mức này. Cặp cùng báo khác trận (lỗi chính của v1) tự động thành âm |
| T3 Dữ liệu | **2** | Mất các cặp "trước–sau", "đưa tin–phản ứng", "lễ đón–hội đàm". *Ước* giảm 15–25% số cặp dương; recall vốn đã thấp (0,28) |
| T4 Giá trị fine-tune | **3** | Mô hình học được ranh giới rất mịn (khác trận, khác buổi) — có giá trị — nhưng các cặp dương còn lại thường giống nhau về chữ, nên lợi thế so với TF-IDF giảm |
| T5 Gom cụm | **4** | Cụm nhỏ, đóng nhanh (≤ 48h) — dễ cho gom cụm trực tuyến |
| T6 Đặt tên | **5** | Một việc cụ thể → tên cụ thể ("U23 Việt Nam thắng Kuwait 2-1") |
| T7 Người dùng | **2** | Bảng xu hướng vụn: một chuyến thăm thành 4–5 mục; khó thấy "câu chuyện lớn đang nóng" |
| T8 Bảo vệ | **4** | Khớp định nghĩa *event* của TDT |
| T9 Chi phí | **3** | Phải gán lại audit, giảm cửa sổ, thêm luật "khác thời điểm" |
| **Tổng** | **33/45** | |

**Khi nào nên chọn:** nhóm ưu tiên độ chính xác và sự đơn giản khi gán; chấp nhận bảng xu hướng chi tiết, vụn.

#### B: Sự kiện tin tức (hiện trạng)

| Tiêu chí | Điểm | Phân tích |
|---|---|---|
| T1 Dễ gán | **3** | Rõ ở phần lõi, nhưng còn ô "?" (mục 3: cặp 5, 7, 15, 16). Chưa có số đo κ người–Claude |
| T2 Precision | **5** | Đo thật: v3 lõi 0,93; v2 0,93 (khác báo 0,96) |
| T3 Dữ liệu | **3** | Đo thật: recall 0,28 (lõi) / 0,43 (mở rộng); 5.381 bộ ba, 90% khác báo |
| T4 Giá trị fine-tune | **4** | Cặp dương có cả "cùng việc, khác cách viết" (phản ứng, cập nhật) → mô hình phải học nghĩa, không chỉ chữ |
| T5 Gom cụm | **4** | Cụm đóng sau vài ngày; cửa sổ 72h hoạt động tốt, trừ sự kiện kéo dài |
| T6 Đặt tên | **4** | Đặt tên được ("Tổng Bí thư thăm cấp Nhà nước Australia"); hơi khó khi cụm gồm nhiều diễn biến |
| T7 Người dùng | **4** | Đúng mức "một tin" người đọc quan tâm; nhiều báo cùng đưa → tín hiệu xu hướng rõ |
| T8 Bảo vệ | **4** | Gần với cách các hệ thống tin tức (Google News "full coverage") gom bài; giải thích được |
| T9 Chi phí | **5** | Không phải làm lại gì, chỉ chốt các ô "?" |
| **Tổng** | **36/45** | |

**Điểm yếu cần vá:** sự kiện kéo dài hơn 72h (chuyến thăm 5–7 ngày, phiên toà nhiều ngày) và các ô "?". Cả hai giải quyết bằng quy tắc phụ ở mục 4, không cần đổi phương án.

#### C: Câu chuyện

| Tiêu chí | Điểm | Phân tích |
|---|---|---|
| T1 Dễ gán | **2** | "Cùng câu chuyện" rất chủ quan: Trump–Putin và Iran có cùng câu chuyện "căng thẳng Mỹ–Nga–Trung Đông" không? Ranh giới trôi |
| T2 Precision | **3** | Theo định nghĩa mới thì nhiều cặp đang bị coi là sai sẽ thành đúng, nhưng luật thực thể sẽ gộp quá tay (mọi bài có "Việt Nam" + "ASIAD") |
| T3 Dữ liệu | **5** | Recall tăng mạnh; rất nhiều cặp dương |
| T4 Giá trị fine-tune | **1** | Học "cùng câu chuyện" ≈ học "cùng chủ đề", việc TF-IDF và mô hình zero-shot đã làm khá tốt (MiniLM chỉ đứng một mình đã thiên về mức này) → khó chứng minh fine-tune có tác dụng |
| T5 Gom cụm | **2** | Cụm không bao giờ đóng (ASIAD kéo dài 2 tuần, vụ án nhiều tháng) → mâu thuẫn với gom cụm theo cửa sổ thời gian |
| T6 Đặt tên | **2** | Tên chung chung ("ASIAD 2026", "Xung đột Nga–Ukraine") — không phải tin |
| T7 Người dùng | **3** | Tốt cho trang "chủ đề nóng", kém cho "tin nóng" và thông báo đẩy |
| T8 Bảo vệ | **3** | Khớp *topic* của TDT, nhưng đề tài viết là "nhận diện **sự kiện**" |
| T9 Chi phí | **1** | Bỏ nhiều luật đã kiểm chứng; gán lại toàn bộ audit; đo lại từ đầu |
| **Tổng** | **22/45** | |

**Không khuyến nghị** làm đơn vị chính. Giá trị của C nằm ở việc làm **lớp nhóm cha** (phương án E).

#### E: Hai tầng (B làm đơn vị + C làm nhóm cha)

| Tiêu chí | Điểm | Phân tích |
|---|---|---|
| T1 Dễ gán | **3** | Như B cho đơn vị; cột "câu chuyện" là thêm, có thể gán thưa (chỉ cho cụm lớn) |
| T2 Precision | **5** | Nhãn yếu theo B, không đổi |
| T3 Dữ liệu | **3** | Như B. Có thể dùng thêm cặp "cùng câu chuyện, khác sự kiện" làm **negative khó hạng hai** — đúng loại negative đang thiếu (xem rủi ro "negative dễ hơn về nghĩa") |
| T4 Giá trị fine-tune | **5** | Mô hình học được hai ranh giới: khác câu chuyện (dễ) và **cùng câu chuyện nhưng khác sự kiện** (khó, đúng chỗ fine-tune có thể thắng zero-shot) |
| T5 Gom cụm | **4** | Gom cụm trực tuyến theo B; nhóm câu chuyện làm sau, theo lô, không ảnh hưởng độ trễ |
| T6 Đặt tên | **4** | Tên cho sự kiện B; câu chuyện có thể dùng tên ngắn hơn |
| T7 Người dùng | **5** | Bảng xu hướng hiện sự kiện; trang chi tiết gom các sự kiện cùng câu chuyện ("Diễn biến liên quan") |
| T8 Bảo vệ | **5** | Dùng đủ hai khái niệm *event* và *topic* của TDT; kiến trúc phân tầng dễ trình bày |
| T9 Chi phí | **4** | Không phải làm lại nhãn hiện có; thêm một cột khi dựng tập vàng; nhóm câu chuyện có thể làm sau |
| **Tổng** | **38/45** | |

### 8.3 Bảng tổng hợp

| Tiêu chí | A | B | C | **E** |
|---|---|---|---|---|
| T1 Dễ gán | 5 | 3 | 2 | 3 |
| T2 Precision nhãn yếu | 5 | 5 | 3 | 5 |
| T3 Đủ dữ liệu | 2 | 3 | 5 | 3 |
| T4 Giá trị fine-tune | 3 | 4 | 1 | **5** |
| T5 Gom cụm | 4 | 4 | 2 | 4 |
| T6 Đặt tên | 5 | 4 | 2 | 4 |
| T7 Người dùng | 2 | 4 | 3 | **5** |
| T8 Bảo vệ | 4 | 4 | 3 | **5** |
| T9 Chi phí chuyển | 3 | 5 | 1 | 4 |
| **Tổng** | 33 | 36 | 22 | **38** |

Trọng số bằng nhau. Nếu nhóm coi T4 (giá trị fine-tune) và T8 (bảo vệ) nặng gấp đôi — hợp lý với một đồ án ML — thì
E càng dẫn xa (E 48, B 44, A 40, C 26).

### 8.4 Các gói quyết định, xếp theo thứ tự khuyến nghị

Mỗi gói = một phương án + bộ quy tắc phụ (mục 4).

#### 🥇 Gói 1: E, cửa sổ theo loại sự kiện (khuyến nghị)

| Quyết định | Chọn |
|---|---|
| Đơn vị | B: sự kiện tin tức |
| Nhóm cha | C: câu chuyện, gán thưa cho cụm lớn |
| Cửa sổ | Mặc định 72h; chuyến thăm/hội nghị/phiên toà: theo lịch trình của chính sự kiện (tối đa 7 ngày) |
| Chuỗi định kỳ, bài tổng hợp | Loại khỏi gom cụm |
| Bài phân tích | Không thuộc sự kiện |
| "Sắp diễn ra" ↔ "đã diễn ra" cùng việc | Cùng sự kiện |

- **Ưu:** tốt nhất ở T4, T7, T8; giữ toàn bộ nhãn đã kiểm chứng; có nguồn negative khó mới (cùng câu chuyện, khác sự kiện).
- **Nhược:** cần nhận diện loại sự kiện (chuyến thăm/hội nghị/phiên toà) để áp cửa sổ dài — làm bằng từ khoá trong tiêu đề
  ("thăm cấp Nhà nước", "hội nghị", "xét xử") rồi đo lại precision; thêm một cột khi gán vàng.
- **Việc phải làm:** luật cửa sổ theo loại; luật nhận diện chuỗi định kỳ/bài tổng hợp; cột "câu chuyện" trong tập vàng.

#### 🥈 Gói 2: B, cửa sổ 72h + loại chuỗi định kỳ / bài tổng hợp

- **Ưu:** đơn giản nhất, gần như không phải sửa gì; mọi số đo hiện tại giữ nguyên giá trị; loại chuỗi định kỳ và bài tổng hợp
  xoá một nhóm lỗi lớn của nhãn yếu.
- **Nhược:** sự kiện dài hơn 3 ngày bị cắt thành nhiều cụm; không có lớp "câu chuyện" cho sản phẩm; thiếu nguồn negative khó
  "cùng câu chuyện, khác sự kiện".
- **Khi nào chọn:** thời gian còn lại ít, muốn bắt đầu fine-tune ngay. Nâng lên Gói 1 sau được, không mất gì.

#### 🥉 Gói 3: B, cửa sổ cố định 7 ngày

- **Ưu:** bắt được chuyến thăm, phiên toà nhiều ngày mà không cần phân loại sự kiện.
- **Nhược:** gộp nhầm các diễn biến khác nhau tăng (các trận cùng giải, các phát ngôn khác nhau của cùng một lãnh đạo);
  precision nhãn yếu *ước* giảm — phải đo lại; cụm đóng chậm hơn.
- **Khi nào chọn:** dữ liệu thiên về sự kiện kéo dài (chính trị, tư pháp) và nhóm chấp nhận đo lại kỹ.

#### Gói 4: A, hành động đơn lẻ, cửa sổ 48h

- **Ưu:** gán dễ nhất, precision cao nhất, tên sự kiện cụ thể nhất.
- **Nhược:** ít dữ liệu train nhất; bảng xu hướng vụn; mất các cặp "phản ứng/cập nhật" — đúng loại cặp giúp mô hình học nghĩa.
- **Khi nào chọn:** đồng thuận khi gán (κ) quá thấp với B và không cải thiện được bằng ví dụ chuẩn.

#### Không khuyến nghị: C làm đơn vị

Phá vỡ gom cụm theo cửa sổ, tên sự kiện vô nghĩa, và khó chứng minh fine-tune có tác dụng (T4 = 1).

### 8.5 Cách ra quyết định nhanh

```
Còn nhiều thời gian và muốn kết quả tốt nhất?      ──► Gói 1 (E)
Thời gian gấp, cần train ngay?                      ──► Gói 2 (B + loại định kỳ/tổng hợp), nâng lên Gói 1 sau
Gán thử 50 cặp mà người với người bất đồng nhiều?   ──► Gói 4 (A), hoặc bổ sung ví dụ chuẩn rồi thử lại B
```

Dù chọn gói nào, bước tiếp theo vẫn là: **2–3 người cùng gán 50 cặp theo định nghĩa đã chọn → đo κ**. Nếu κ < 0,6 thì
định nghĩa còn mơ hồ — bổ sung ví dụ chuẩn trước khi gán quy mô lớn.
