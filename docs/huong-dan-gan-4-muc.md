# Hướng dẫn gán mức độ liên quan giữa hai bài báo (4 mức)

> Dùng cho nhãn yếu v4 (`src/eventrank/weak_labels/graded.py`), cho Claude gán mù và cho người gán kiểm tra.
> Theo định nghĩa đã chốt (Gói 1 / phương án E, `docs/tong-hop.md` mục 4): **đơn vị = sự kiện tin tức**,
> **nhóm cha = câu chuyện**. Mỗi cặp chỉ có tiêu đề + sapo, báo, ngày đăng. Không đoán thêm ngoài văn bản.

## Bốn mức

| Mức | Điểm | Nghĩa | Hỏi |
|---|---|---|---|
| **3** | 1,0 | **Cùng sự kiện** | Hai bài kể về **cùng một việc cụ thể** (hoặc tin tiếp nối trực tiếp của chính việc đó)? |
| **2** | 0,6 | **Cùng câu chuyện, khác sự kiện** | Không cùng một việc, nhưng là **hai diễn biến của cùng một câu chuyện** đang tiếp diễn? |
| **1** | 0,3 | **Cùng chủ đề / cùng khuôn tin** | Không chung câu chuyện, chỉ **cùng loại tin** hoặc cùng lĩnh vực? |
| **0** | 0,0 | **Không liên quan** | Khác lĩnh vực, không có gì chung đáng kể |
| **x** | — | **Không gán** | Một trong hai bài là **bài tổng hợp nhiều tin**, hoặc văn bản không đủ để hiểu |

Đi từ trên xuống: kiểm tra mức 3 trước, không đạt thì xét mức 2, rồi 1, rồi 0.
**Phân vân giữa hai mức → chọn mức THẤP hơn**, ghi độ tin `thấp`.

## Mức 3: cùng sự kiện

Gán 3 khi hai bài nói về **cùng một việc cụ thể**, kể cả khi:
- khác báo, khác cách viết, khác khía cạnh của **chính việc đó** (con số, nhân chứng, phát biểu tại cùng buổi);
- một bài **trước**, một bài **sau** cùng việc: "sẽ hội đàm" ↔ "đã hội đàm", nhận định trước trận ↔ kết quả **cùng
  trận**, bài báo trước chương trình (dàn nghệ sĩ, "sẽ bắn pháo hoa", "diễn ra tối 23/8") ↔ **chính đêm diễn**. Bài báo
  trước **cả một chuyến thăm / cả một đợt** nhiều hoạt động ↔ **một** hoạt động trong đó → 2;
- tin **mở đầu** ↔ tin **kết quả** của cùng một việc đang diễn ra: khai mạc ↔ bế mạc cùng phiên họp, **mở phiên tòa ↔
  tuyên án của cùng phiên tòa** (kể cả cách vài ngày);
- **phản ứng trực tiếp** của việc đó trong vài ngày: "vụ cháy 5 người chết" ↔ "lãnh đạo thăm nạn nhân vụ cháy";
- nhiều bài về **cùng một hoạt động** trong một chuyến thăm / hội nghị / phiên toà: cùng một cuộc hội đàm, cùng một buổi
  lễ đón, cùng một phiên họp (khác báo, khác giờ đăng). Hai **hoạt động khác nhau** của cùng chuyến → mức 2 (xem dưới);
- "X bị bắt" ↔ "X bị khởi tố" trong vài ngày.

## Mức 2: cùng câu chuyện, khác sự kiện

Gán 2 khi **không cùng một việc** nhưng **cùng một câu chuyện** (một chuỗi diễn biến có chung nhân vật/vụ việc/giải
đấu chính):
- hai **trận khác nhau** của cùng một đội trong cùng giải: "U23 VN thắng Kuwait" ↔ "U23 VN gặp Philippines";
  "U20 VN gặp Iran 6/9" ↔ "U20 VN gặp Palestine 3/9"; "Cantho Catfish 88–85 (18/7)" ↔ "… 95–75 (16/7)";
- hai **hoạt động khác nhau** của cùng một đoàn trong cùng một chuyến đi / hội nghị: "Thủ tướng gặp Thủ tướng Ethiopia"
  ↔ "Thủ tướng gặp Putin" bên lề BRICS; "Tổng Bí thư dự Đại hội Liên hiệp hữu nghị (14/9)" ↔ "… làm việc với Ban Chấp
  hành (15/9)"; lễ đón ↔ hội đàm ↔ thăm địa phương của cùng chuyến thăm (quyết định ngày 29/10/2026);
- hai **diễn biến khác** của cùng một xung đột/đàm phán: "điện đàm Trump–Putin" ↔ "đặc phái viên Mỹ tới Kyiv";
- các **giai đoạn khác nhau** của cùng một vụ án cách nhau lâu (khởi tố ↔ xét xử sau vài tuần);
- **bài phân tích / bình luận** ↔ tin cụ thể của câu chuyện đó ("Nguy cơ Iran leo thang" ↔ "Tổng thống Iran thách thức
  Mỹ"): bài phân tích không thuộc sự kiện nào;
- hai việc khác nhau trong cùng một kỳ đại hội thể thao / sự kiện lớn **khi có chung đội, nhân vật**: "bóng chuyền nữ VN
  thắng Hồng Kông" ↔ "bóng chuyền nữ VN thắng Qatar" (ASIAD).

## Mức 1: cùng chủ đề / cùng khuôn tin

Gán 1 khi chỉ **cùng loại tin** hoặc cùng lĩnh vực hẹp, không chung câu chuyện:
- **chuỗi bài định kỳ** khác ngày: "Giá vàng hôm nay 15/9" ↔ "Giá vàng hôm nay 10/9", thời tiết, chứng khoán,
  giá bạc, giá Bitcoin theo ngày;
- **cùng khuôn tin, khác đối tượng**: "Điểm chuẩn ĐH Thủy lợi" ↔ "Điểm chuẩn ĐH Điện lực"; cùng chính sách ở **hai
  địa phương** khác nhau ("sắp xếp trường ở phường A" ↔ "… phường B");
- cùng lĩnh vực hẹp, khác việc: hai bài tư vấn sức khoẻ cùng bệnh, hai bài về hai mẫu điện thoại khác nhau, hai vụ tai
  nạn giao thông khác nhau;
- hai việc khác nhau trong cùng một kỳ đại hội thể thao nhưng **khác môn, khác đội**.

## Mức 0: không liên quan

Khác lĩnh vực hoặc chỉ trùng những thứ rất chung (cùng "Việt Nam", cùng "TP.HCM", cùng chuyên mục rộng "Thời sự").

## x: không gán

- Bài **tổng hợp nhiều tin**: "Tin tức thế giới 13-9: …; …", "Tin tức sáng …", "Thời sự 24h …", "Kết quả bóng đá hôm
  nay …" (Gói 1: loại khỏi gom cụm).
- Văn bản quá ngắn hoặc lỗi, không hiểu được bài nói gì.

## Ca hay nhầm

| Cặp | Mức | Vì sao |
|---|---|---|
| "Giá vàng 4/9: rơi thẳng đứng gần 100 USD" ↔ "Giá vàng thế giới xuống thấp nhất hai tuần" (cùng ngày, cùng phiên) | 3 | cùng một biến động giá |
| "Giá vàng 14/9" ↔ "Giá vàng 15/9" | 1 | chuỗi định kỳ, mỗi ngày một tin |
| "HLV U20: các cầu thủ hoảng loạn" ↔ "Hãy kiên nhẫn với U20 sau thất bại 0-3" (cùng trận) | 3 | phản ứng sau cùng trận |
| "U20 VN thua Hàn Quốc" ↔ "U20 VN gặp Triều Tiên" | 2 | hai trận cùng giải, cùng đội |
| "Thủ tướng dự BRICS" ↔ "Ông Tập tới Ấn Độ dự BRICS" | 2 | cùng hội nghị nhưng hai đoàn, hai việc khác nhau; nếu cùng phiên họp / cùng tuyên bố → 3 |
| "iPhone 18 Pro chốt giá" ↔ "Apple tìm cách giảm mức tăng giá iPhone 18 Pro" | 3 | cùng một việc (giá bán iPhone 18 Pro) |
| "iPhone 18 khan hàng" ↔ "AirPods 5 ra mắt" | 1 | cùng hãng, khác sản phẩm, khác việc |
| "Chủ tịch QH thăm Hàn Quốc" ↔ "Chủ tịch QH thăm Mông Cổ" (cùng chuyến công du) | 2 | hai chặng, hai nước khác nhau |
| "Vụ taxi bị hành hung ở Quảng Ninh" ↔ "Vụ nhóm khách nữ túm tóc tài xế taxi" | 3 | cùng vụ |
| Bài phân tích "FED tăng lãi suất tác động ra sao" ↔ "Giá vàng 14/9" | 1 | cùng lĩnh vực, không cùng việc |

### Bổ sung sau lần người duyệt đầu tiên (13/10/2026, 100 cặp tập test)

| Cặp | Mức | Quy tắc rút ra |
|---|---|---|
| Thủ tướng gặp Thủ tướng Ethiopia ↔ Thủ tướng nói về Việt Nam–Ấn Độ (cùng chuyến dự BRICS) | ~~3~~ **2** | ~~cùng đoàn, cùng chuyến → cùng sự kiện~~. **Thay bằng quyết định 29/10/2026:** mỗi cuộc gặp / hoạt động là một sự kiện; cùng chuyến đi là cùng câu chuyện |
| Vietjet ↔ LPBank được vinh danh tại cùng lễ VNTAX 2026 | 2 | **cùng một buổi lễ / hội nghị nhưng chủ thể khác nhau**: cùng câu chuyện, không phải cùng sự kiện |
| Phỏng vấn ca sĩ A ↔ ca sĩ B cùng tham gia chương trình "Nghĩa tình Phương Nam" | 2 | bài quảng bá của nhiều người cho cùng một chương trình: cùng câu chuyện |
| Tân binh Việt kiều ↔ Williams Minh Hoàng đá cặp với ai (cùng đợt tập trung đội tuyển, cách 6h) | 3 | cùng đợt tập trung, cùng chủ đề nhân sự: cùng sự kiện |
| Họp Ban Chỉ đạo 35 (14/9) ↔ họp Ban Chỉ đạo TW về phòng, chống tham nhũng (17/9) | 1 | **hai ban chỉ đạo khác nhau**: chỉ cùng loại tin. Kiểm tra tên cơ quan trước khi coi là cùng cuộc họp |
| Tin cuộc họp bắt đầu ↔ thông báo kết quả **cùng** cuộc họp | 3 | tin trước và tin sau của cùng một việc là cùng sự kiện, không phải 2 |
| Dự án metro số 2: đền bù ↔ kéo dài tuyến tới Thủ Dầu Một | 2 | cùng dự án, hai diễn biến |

Nhận xét: 5/6 lần người sửa là **nâng mức** (Claude chọn thấp hơn người), chủ yếu ở ranh giới 3 ↔ 2 trong cùng một chuyến
đi hoặc đợt tập trung. Quy tắc "phân vân thì chọn mức thấp hơn" có thể làm thiếu mức 3; lần gán lại tới nên áp các
quy tắc ở bảng trên trước khi dùng quy tắc đó.

### Sửa sau khi rà lỗi dữ liệu train (29/10/2026)

Một lượt rà tay tìm thấy nhãn sai ở cả luật lẫn Claude; người dùng quyết định:

| Cặp | Mức cũ → mới | Quy tắc |
|---|---|---|
| Tô Lâm nhận giải Lev Tolstoy ở Moskva ↔ khánh thành phòng xét nghiệm Việt–Nga ở Hà Nội | 3 → 1 | khác việc, khác nơi; chỉ chung quan hệ Việt–Nga |
| Trần Thanh Mẫn gặp kiều bào ở Hàn Quốc ↔ Tô Lâm gặp kiều bào ở Nga | 3 → 1 | khác người, khác nơi, khác ngày: cùng khuôn tin |
| U20 VN gặp Iran (6/9) ↔ gặp Palestine (3/9) | 3 → 2 | hai trận cùng đội, cùng giải (R4) |
| Cantho Catfish thắng 88–85 (18/7) ↔ 95–75 (16/7) | 3 → 2 | hai trận cùng đội, cùng giải (R4) |
| Thủ tướng gặp Thủ tướng Ethiopia ↔ gặp Putin bên lề BRICS | 3 → 2 | hai hoạt động của cùng chuyến (thay quy tắc 13/10) |
| Đại hội Liên hiệp hữu nghị (14/9) ↔ làm việc với Ban Chấp hành (15/9) | 3 → 2 | hai hoạt động riêng biệt |
| Màn diễu binh ↔ màn pháo hoa trong concert "Tổ quốc trong tim" (23/8) | 0 → 3 | cùng một đêm diễn, khác góc đưa tin |

Bổ sung cùng ngày (người dùng duyệt 2 đề xuất sau khi đo mâu thuẫn bắc cầu: 431 tam giác "A–B = 3, A–X = 3 nhưng B–X =
2" trong train sau lần gán lại thứ nhất):

| Cặp | Mức | Quy tắc |
|---|---|---|
| "Concert … có Tùng Dương, Soobin… không bán vé" (17/8) ↔ "40.000 khán giả đội mưa xem concert" (24/8) | 3 | **bài báo trước sự kiện ↔ chính sự kiện** = cùng sự kiện (như nhận định trước trận, R4) |
| "Hàng nghìn người trẻ xếp hàng nhận vé" / "Buổi tổng duyệt" / "Trung tướng kiểm tra lực lượng diễu binh" ↔ đêm diễn | 2 | **hoạt động riêng** trước/sau sự kiện (có việc mới xảy ra: phát vé, tổng duyệt, kiểm tra) |
| "Dẫn giải cựu Thứ trưởng Nguyễn Bá Hoan hầu tòa" (18/8) ↔ "… lãnh 12 năm tù" (24/8) | 3 | **mở phiên tòa ↔ tuyên án của cùng phiên tòa** = cùng sự kiện. Khởi tố ↔ xét xử sau vài tuần vẫn là 2 |
| "Chủ tịch Quốc hội Bờ Biển Ngà sắp thăm Việt Nam" ↔ "… thăm khu khảo cổ dưới tòa nhà Quốc hội" | 2 | bài trước **cả chuyến thăm** ↔ **một** hoạt động của chuyến |

**Bắc cầu:** A–B = 3 và A–X = 3 thì B–X phải là 3. Khi gán một nhóm bài, nếu thấy mâu thuẫn thì sửa cạnh sai (thường là
một bài tổng quan / kết thúc chuyến thăm bị gán 3 với nhiều hoạt động khác nhau → các cạnh đó là 2).

## Quy tắc ranh giới (ĐÃ DUYỆT 21/10/2026)

Rút ra từ 87 cụm Claude ghi "không chắc" khi gom cụm tập vàng 14–15/09. Câu hỏi chung: **có một VIỆC MỚI xảy ra không**
(một quyết định, hành động, trận đấu, cuộc họp mới)? Có → sự kiện mới. Chỉ là đưa tin thêm, phản ứng, giải thích, bình luận
về chính việc cũ → cùng sự kiện.

| # | Dạng | Quy tắc đề xuất | Ví dụ thật (14–15/09) |
|---|---|---|---|
| R1 | Chuỗi định kỳ (giá vàng, tỷ giá, chứng khoán, thời tiết) | Mỗi **phiên / ngày được mô tả** là một sự kiện; các bài cùng phiên gộp chung. Bài đăng sáng 15/9 tả phiên tối 14/9 → thuộc phiên 14/9. Tin kèm quyết định mới (NHNN nâng tỷ giá trung tâm) → sự kiện riêng | "Giá vàng 14/9" (5 bài) ≠ "Giá vàng 15/9" (5 bài); "Giá USD 15/9" ≠ "NHNN nâng tỷ giá kỷ lục" |
| R2 | Diễn biến nối tiếp | Phản ứng, hoan nghênh, bác bỏ, bình luận về **chính tuyên bố/việc đó** trong ≤ 3 ngày → cùng sự kiện. Một **thoả thuận, quyết định, hành động mới** → sự kiện mới, kể cả khi nối tiếp | Trump kêu gọi Ukraine ngừng đánh dầu (13/9) + Kremlin hoan nghênh = 1 sự kiện; Trump tuyên bố hai bên nhất trí ngừng tấn công năng lượng (14/9) = sự kiện mới |
| R3 | Một chương trình / hội nghị / đợt, nhiều chủ thể | Bài về **chính chương trình** (khai mạc, diễn biến, kết quả chung) → cùng sự kiện. Bài về **một chủ thể riêng** (phỏng vấn từng nghệ sĩ, từng doanh nghiệp được vinh danh, từng đoàn kiểm tra ở từng địa phương) → sự kiện riêng | Đoàn kiểm tra 221 – Quân ủy ≠ Đoàn 238 – An Giang; phỏng vấn ca sĩ A ≠ ca sĩ B cùng "Nghĩa tình Phương Nam" |
| R4 | Thể thao | **Một trận = một sự kiện**: nhận định, lịch phát sóng, diễn biến, kết quả, phản ứng, trọng tài/VAR, phân tích chính trận đó. Bài chuẩn bị trận kế tiếp (dù nhắc trận trước) → thuộc trận kế tiếp. Họp báo/danh sách **trước cả giải** → sự kiện riêng. Bảng xếp hạng / tổng kết nhiều trận → **x** (tổng hợp) | Tuyển nữ VN thua Đài Loan ≠ tuyển nữ VN chuẩn bị gặp Nhật Bản; HLV U23 họp báo trước ASIAD ≠ trận U23–Kuwait; BXH bóng đá nữ sau lượt đầu → x |
| R5 | Cùng chủ thể, cùng ngày, không rõ một hay hai lần công bố | Đọc nội dung/tóm tắt. Không có dấu hiệu là hai việc khác nhau → **gộp** (người duyệt từng sửa Claude vì gán thiếu "cùng sự kiện", 5/6 lần là nâng mức) | EVN công bố kết quả 8 tháng (3 bài); video giải cứu F-15E + lời kể phi công (cùng đợt công bố) |
| R6 | Bài phân tích / bình luận | Phân tích **đúng một việc cụ thể vừa xảy ra** (≤ 3 ngày) → cùng sự kiện với việc đó. Bình luận chung về xu hướng, dự báo, giới thiệu, quảng bá → sự kiện riêng (thường 1 bài) | "Trận thua Man City phơi bày hạn chế của Man Utd" → cùng trận; "Lo ngại phong độ tuyển VN trước FIFA ASEAN Cup" → riêng |

## Gán tay (cho người)

Mục đích: đo xem Claude gán có khớp với người không (Cohen's κ). Nếu khớp (κ ≥ 0,6–0,7), nhãn Claude dùng được làm
đáp án; nếu không, mọi con số đánh giá hiện tại đều phải xem lại.

**File:** `data/weak_labels/v4/human_label_100.csv`. Mở trên Windows:
`\\wsl.localhost\Ubuntu\home\hieu\personal\semeter7\pbl\Ranking-Event-Detection\data\weak_labels\v4\human_label_100.csv`.
File gồm 100 cặp đã trộn ngẫu nhiên, khoảng 25 cặp mỗi mức. Bạn không biết cặp nào thuộc mức nào, và nên như vậy.

**Quy tắc gán mù:**
- **Không mở** `human_label_100_ids.csv`, `test_labeled.csv` hay các file trong `parts/`: chúng chứa nhãn của Claude.
- Không tra Google, không mở bài gốc. Chỉ dùng tiêu đề, sapo, báo và ngày đăng, giống hệt những gì Claude được xem.
- Gán theo thứ tự `pair_no`, không quay lại sửa các cặp trước (trừ khi gõ nhầm).
- Đọc lại mục "Bốn mức" và "Ca hay nhầm" ở trên **trước khi** bắt đầu.

**Các bước:**
1. Mở file bằng Excel (*Data → From Text/CSV*, chọn mã hoá **UTF-8**) hoặc Google Sheets (*File → Import*). Bật *Wrap
   text* cho các cột sapo để đọc dễ.
2. Với mỗi dòng, đọc bài A (`title_a`, `sapo_a`) rồi bài B. Xem `gap_hours`: hai bài cách nhau bao nhiêu giờ.
3. Tự hỏi theo thứ tự rồi điền `level_human`:
   - Hai bài nói về **cùng một việc cụ thể** (hoặc tin tiếp nối trực tiếp của nó)? → **3**
   - Không, nhưng **cùng một câu chuyện** (cùng vụ án, cùng giải đấu và cùng đội, cùng cuộc xung đột…)? → **2**
   - Không, chỉ **cùng loại tin / cùng lĩnh vực hẹp** (giá vàng hai ngày, điểm chuẩn hai trường)? → **1**
   - Không có gì chung đáng kể → **0**
   - Một bài là bài tổng hợp nhiều tin, hoặc không hiểu được → **x**
4. Phân vân giữa hai mức: chọn mức **thấp hơn**, và ghi ngắn vào `ghi_chu` (ví dụ "phân vân 3/2: cùng chuyến thăm
   nhưng khác nước"). Các ghi chú này rất có giá trị khi bàn lại định nghĩa.
5. Khoảng 30–40 giây mỗi cặp, tổng khoảng 1 giờ. Nên nghỉ sau 50 cặp: mệt thì gán lệch.
6. Lưu lại **đúng tên file, định dạng CSV UTF-8**:
   - Excel: *Save As → CSV UTF-8 (Comma delimited)*. Đừng chọn "CSV" thường vì sẽ làm hỏng dấu tiếng Việt.
   - Google Sheets: *File → Download → CSV*, rồi chép đè lên file cũ.
7. Chạy `make agreement-v4`. Kết quả gồm:
   - κ 4 mức;
   - κ 4 mức trọng số bậc hai (lệch 3↔2 bị phạt nhẹ hơn lệch 3↔0);
   - κ 2 mức (cùng sự kiện hay không);
   - bảng nhầm lẫn, và file `human_disagreements.csv` liệt kê các cặp bạn và Claude lệch nhau, kèm lý do của Claude.

**Đọc kết quả:**
- **κ 2 mức** quan trọng nhất cho gom cụm. **κ trọng số bậc hai** cho biết thứ tự 4 mức có khớp không.
- κ ≥ 0,7: dùng nhãn Claude được. 0,4–0,7: xem `human_disagreements.csv`, bổ sung ví dụ vào mục "Ca hay nhầm", rồi
  cho Claude gán lại. < 0,4: định nghĩa còn mơ hồ, cần họp nhóm.
- Tốt nhất có **người thứ hai** gán độc lập cùng 100 cặp (chép file ra bản riêng). Đồng thuận người–người là **trần**:
  không thể đòi Claude hay mô hình khớp hơn mức đó.

## Định dạng trả lời (cho Claude)

Mỗi cặp một dòng CSV: `pair_no,level,confidence,reason`
- `level`: `3`, `2`, `1`, `0` hoặc `x`
- `confidence`: `cao`, `vừa`, `thấp`
- `reason`: tiếng Việt, ≤ 15 từ, nêu **việc** của mỗi bài ("Trận VN–Kuwait vs trận VN–Philippines")
