# Gán nhãn yếu "cặp cùng sự kiện": quy trình chi tiết

> Tài liệu này giải thích **từng bước** đã làm để tạo dữ liệu huấn luyện cho mô hình embedding: làm gì, vì
> sao làm vậy, ra con số nào, và đã sửa những lỗi gì trên đường đi.
> Tổng quan hiện tại + cách chạy + cạm bẫy: [handoff/weak_labels.md](handoff/weak_labels.md). Mã: `src/eventrank/weak_labels/`. Lệnh: `make embed`, `make weak-labels`.
> Mọi con số là **kết quả chạy thật** ngày 01/10/2026.
>
> ⚠️ **Mục 0–11 mô tả bản v1.** v2 (02/10/2026, [mục 12](#12-v2-những-gì-đã-sửa-và-kết-quả)) sửa precision và
> negative khó. **Bản hiện tại là v3** (04/10/2026, [mục 13](#13-v3-tín-hiệu-ngữ-nghĩa-để-tăng-recall)): thêm tín hiệu
> ngữ nghĩa để tăng recall.

---

## 0. Bài toán

Mô hình embedding cần học sao cho **hai bài cùng một sự kiện có vector gần nhau**. Muốn vậy phải có rất
nhiều ví dụ dạng *(bài A, bài B, có/không cùng sự kiện)*. Không ai gán tay được hàng chục nghìn cặp.

**Gán nhãn yếu (weak supervision)** giải quyết việc này: thay vì gán từng cặp, ta viết vài **quy tắc**
(hàm gán nhãn, viết tắt LF). Mỗi quy tắc đúng phần lớn thời gian nhưng không hoàn hảo. Sau đó một mô hình thống kê **gộp phiếu** của các quy tắc thành một xác suất cho mỗi cặp.

```
 Gold (NER)  ┐                                                                        ┌─► bộ ba train
             ├─► 1. chuẩn hoá ─► 2. join ─► 3. ứng viên ─► 4. đặc trưng ─► 5. LF ─► 6. gộp ─► 7. chọn ─┤
 Silver (văn bản) ┘    thực thể      + IDF       cặp           cặp          phiếu    phiếu    + chia    └─► cặp audit
                                                                                                           │
                                                          8. kiểm tra chất lượng bằng gán tay / LLM ◄────┘
```

**Định nghĩa "cùng sự kiện"** dùng xuyên suốt:
- Là **1**: hai bài nói về cùng một việc cụ thể đã xảy ra, như cùng vụ án, cùng trận đấu, cùng chuyến thăm, cùng quyết định, cùng vụ tai nạn. Bài cập nhật diễn biến của chính việc đó trong vài ngày cũng tính là 1.
- Là **0**: chỉ cùng chủ đề hoặc cùng nhân vật nhưng khác việc. Ví dụ hai trận khác nhau của cùng một đội, giá vàng của hai ngày khác nhau, điểm chuẩn của hai trường khác nhau.

> Nhóm chưa chốt chính thức định nghĩa này (xem phan-tich-event-clustering-trending.md §3.2). Đổi định
> nghĩa thì phải chỉnh lại ngưỡng của các LF.

---

## 1. Dữ liệu đầu vào

| Nguồn | File | Có gì |
|---|---|---|
| Gold (R2 `gold/`) | `data/lake/gold/gold_data.jsonl` | 28.746 bài: `article_id`, `source`, `standardized_category`, `published_at`, `title`, **`entities`** (940.474 lần nhắc, 6 nhãn PER/ORG/LOC/EVENT/DOC/PRODUCT) |
| Silver (R2 `silver/`) | `data/lake/silver/*/*.jsonl` | Cùng 28.746 bài: `title`, **`sapo`**, **`content_text`** |

Gold **không có sapo và nội dung**, nên phải join với Silver theo `article_id`. Join khớp 28.746/28.746 bài, tiêu đề và `published_at` khớp 100%. Có 21 bài không có `published_at` nên bị bỏ, còn **28.725 bài**.

**Điểm mấu chốt:** NER chạy trên **cả bài**, còn mô hình embedding chỉ đọc **tiêu đề + sapo** (giới hạn 256–512 token). Nếu coi mọi lần nhắc tên trong bài là như nhau, hai bài sẽ bị nối với nhau chỉ vì cùng nhắc lướt "Bộ Y tế" ở đoạn cuối. Bước 1 xử lý đúng vấn đề này.

Offset của thực thể tính trên văn bản ghép theo khuôn sau (xem [lam-sach-du-lieu.md](lam-sach-du-lieu.md)):

```
Tiêu đề: {title}\n\nSapo: {sapo}\n\nNội dung:\n{content_text}
```

Khuôn này khớp **99,26%** thực thể. Phần lệch 1–6 ký tự nằm ở 247 bài, chủ yếu của BAOCHINHPHU và NHANDAN. Độ lệch này không ảnh hưởng, vì ta chỉ cần biết thực thể nằm ở vùng nào.

---

## 2. Bước 1: Chuẩn hoá thực thể và tính độ nổi bật

Mã: `entities.py`

### 2.1 Gộp các cách viết của cùng một tên

NER giữ nguyên cách báo viết, nên cùng một thực thể có nhiều dạng. Đo trên Gold có 9.558 nhóm như vậy, chiếm 405 nghìn lần nhắc. Ví dụ: `TP.HCM` 5.455 lần, `TPHCM` 1.639, `TP HCM` 1.346, `Thành phố Hồ Chí Minh` 1.445.
Nếu không gộp, hai bài cùng nói về TP.HCM nhưng viết khác nhau sẽ bị coi là không chung thực thể nào.

Hàm `EntityNormalizer.norm(text, label)` xử lý theo thứ tự:

| # | Việc | Ví dụ |
|---|---|---|
| 1 | Cắt dấu câu ở hai đầu | `Việt Nam -` → `Việt Nam`; `Cục Dự trữ Liên bang Mỹ (` → `…Mỹ` |
| 2 | Bỏ rác: không có chữ cái, hoặc dài dưới 2 ký tự | `"`, `-`, `2026` |
| 3 | Bỏ từ chung đứng một mình | `Công an`, `Bộ`, `Luật`, `bệnh viện` |
| 4 | Bỏ mảnh từ viết thường (ORG/LOC) | `ủy`, `ương`, `tỉnh` |
| 5 | DOC: gộp theo loại + số hiệu | `Nghị quyết 57`, `Nghị quyết số 57-NQ/TW` → `nghịquyết57` |
| 6 | Khoá tự động: NFC, chữ thường, bỏ dấu chấm, gạch nối, khoảng trắng | `TP. HCM`, `TPHCM` → `tphcm`; `Kim Sang-sik` → `kimsangsik` |
| 7 | Tra bảng alias viết tay `configs/entity_aliases.yaml` | `Thành phố Hồ Chí Minh` → `tphcm`; `Trump` → `donaldtrump` |
| 8 | LOC: bỏ tiền tố hành chính | `tỉnh An Giang` → `angiang` |

Bước 7 làm **trước** bước 8 vì một lý do cụ thể: nếu bỏ tiền tố trước, `Thành phố Hồ Chí Minh` sẽ thành `hồchíminh` và trùng với **tên người** Hồ Chí Minh.

Kết quả: 149.216 chuỗi gốc còn 131.992 thực thể chuẩn hoá.

### 2.2 Bỏ tên của chính tờ báo

"Như Tuổi Trẻ đưa tin…" khiến `Tuổi Trẻ` xuất hiện trong 942 bài, và **97% số đó là bài của chính Tuổi Trẻ**. Nếu giữ lại, mọi bài Tuổi Trẻ sẽ được nối với nhau. Vì vậy mỗi bài bỏ tên của chính báo đăng nó (`SELF_NAMES`). Khi báo khác nhắc "Tuổi Trẻ" thì vẫn giữ.

### 2.3 Gán vùng và tính độ nổi bật (salience)

Từ `start_char`, hàm `zone_bounds()` xác định mỗi lần nhắc nằm ở vùng nào, mỗi vùng có một trọng số:

| Vùng | Trọng số | Lý do |
|---|---|---|
| tiêu đề | 3,0 | tên ở tiêu đề gần như chắc chắn là chủ thể của bài |
| sapo | 2,0 | sapo tóm tắt sự kiện |
| đoạn đầu (800 ký tự đầu nội dung) | 1,2 | thường là các bên chính |
| thân bài | 0,6 | hay là bối cảnh hoặc nhắc lướt |

Với mỗi thực thể trong một bài, lấy vùng **tốt nhất** mà nó xuất hiện và đếm số lần nhắc:

```
salience = trọng_số_vùng_tốt_nhất × (1 + 0,5 × ln(số_lần_nhắc))
         × 0,2   nếu là tên người chỉ một chữ ("Tuấn", "Phương": ở các bài khác nhau thường là người khác nhau)
```

### 2.4 Ví dụ thật

Bài của Nhân Dân "*Khẩn trương xử lý vụ nghi ngộ độc thực phẩm sau ăn bánh mì ở Gia Lai*" có 33 lần nhắc tên. Sau bước 1, các thực thể nổi bật nhất là:

| Thực thể | Nhãn | Vùng tốt nhất | Số lần nhắc | Salience |
|---|---|---|---|---|
| Gia Lai | LOC | tiêu đề | 5 | 5,41 |
| Trung tâm Y tế An Khê | ORG | sapo | 4 | 3,39 |
| phường An Khê | LOC | sapo | 3 | 3,10 |
| Sở Y tế tỉnh Gia Lai | ORG | đoạn đầu | 6 | 2,28 |
| Cục An toàn thực phẩm | ORG | đoạn đầu | 5 | 2,17 |
| Chu Quốc Thịnh | PER | đoạn đầu | 1 | 1,20 |

Tên chỉ nhắc một lần ở cuối bài có salience 0,6 hoặc thấp hơn, gần như không đóng góp.

> Còn sót: `Sở Y tế tỉnh Gia Lai` và `Sở Y tế Gia Lai` chưa được gộp, vì bước 8 chỉ bỏ tiền tố hành chính ở
> **đầu** tên LOC. Đây là việc cần bổ sung vào bảng alias hoặc quy tắc.

---

## 3. Bước 2: Join, IDF, đánh dấu bài đăng lại

Mã: `corpus.py → load_corpus()`

**IDF.** Một thực thể có mặt ở nhiều bài thì ít giá trị phân biệt sự kiện:

```
idf(e) = ln(N / df(e))            N = 28.725 bài, df = số bài chứa e
idf(e) = 0  nếu df = 1            (chỉ một bài: không nối được với bài nào)
idf(e) = 0  nếu df > 2% · N       (~575 bài: "Việt Nam", "Hà Nội", "Chính phủ", "Mỹ", "Tô Lâm"…)
```

Trọng số cuối cùng của thực thể e trong bài a: **`weight(a, e) = salience(a, e) × idf(e)`**.

**Bài đăng lại.** Hai bài có cùng tiêu đề, hoặc cùng sapo dài ≥ 80 ký tự, được gán chung một `dup_group`. Bài không bị xoá (theo quy tắc trong AGENTS.md). Các cặp này chắc chắn cùng sự kiện nhưng **quá dễ** để học, nên sau này không đưa vào tập train.

**Văn bản đưa vào embedding.** `head_text() = tiêu đề + ". " + sapo`.

---

## 4. Bước 3: Sinh cặp ứng viên

Mã: `pairs.py`

So mọi cặp nghĩa là 28.725² / 2 ≈ 412 triệu cặp. Việc này không cần thiết, vì hai bài cùng sự kiện gần như luôn đăng cách nhau vài ngày. Ứng viên lấy từ **ba nguồn**, đều trong cửa sổ **±7 ngày**:

| Nguồn | Cách làm | Số cặp | Vì sao cần |
|---|---|---|---|
| Thực thể (`entity_candidates`) | Chỉ mục ngược thực thể → danh sách bài. Chỉ dùng thực thể có idf > 0 **và nổi bật** (ở tiêu đề/sapo, hoặc nhắc ≥ 2 lần, hoặc ở đoạn đầu). Bỏ thực thể có hơn 400 bài. Mỗi bài giữ 20 cặp có tổng trọng số chung cao nhất | 273.898 | nguồn chính |
| TF-IDF (`tfidf_candidates`) | Mỗi bài lấy 10 láng giềng gần nhất theo cosine TF-IDF của (tiêu đề + sapo + đoạn đầu), cosine > 0,15 | 66.907 | bắt cặp cùng sự kiện mà NER không khớp |
| Ngẫu nhiên (`random_candidates`) | Mỗi bài 1 cặp ngẫu nhiên trong ±24h | 27.999 | cho label model thấy đủ cặp âm thông thường |
| **Hợp** | | **327.230** | |

TF-IDF dùng cụm 1–2 âm tiết (bigram âm tiết) nên không cần tách từ tiếng Việt. Thêm hai tuỳ chọn `sublinear_tf` và `max_df = 0,3` để bỏ các từ quá phổ biến.

---

## 5. Bước 4: Đặc trưng của từng cặp

Mã: `pairs.py → pair_features()`

| Đặc trưng | Công thức / ý nghĩa |
|---|---|
| `ent_score` | Σ min(weight_a, weight_b) trên các thực thể **chung** |
| `ent_wjacc` | `ent_score` / Σ max(weight_a, weight_b) trên **hợp** các thực thể. Bài dài nhiều thực thể không tự động được lợi |
| `n_head_shared` | số thực thể hiếm (df ≤ 200) nằm ở tiêu đề/sapo của **cả hai** bài |
| `cos_head` | cosine TF-IDF của tiêu đề + sapo |
| `cos_lead` | cosine TF-IDF của tiêu đề + sapo + 600 ký tự đầu nội dung |
| `n_numbers` | số con số kèm đơn vị trùng nhau ở tiêu đề/sapo: "150 người", "2,5 tỷ", "20 tấn" |
| `date_conflict` | hai tiêu đề đều ghi ngày nhưng không có ngày nào chung. Ngày lễ ("Quốc khánh 2/9") và tỉ số ("thắng 2-1") không tính |
| `dt_hours` | hai bài cách nhau bao nhiêu giờ |
| `cross_source`, `same_category`, `same_dup` | khác báo, cùng chuyên mục, cùng nhóm đăng lại |

**Tiếp ví dụ ở mục 2.4.** Cặp Nhân Dân ↔ Tuổi Trẻ ("*Cục An toàn thực phẩm yêu cầu khẩn trương điều tra nguyên nhân vụ ngộ độc bánh mì ở Gia Lai*"):

```
dt_hours = 0,97   cross_source = 1   same_category = 1
ent_score = 69,95  ent_wjacc = 0,40   n_head_shared = 0   ← "Gia Lai" có df > 200 nên không tính là "hiếm"
cos_head = 0,31    cos_lead = 0,34    n_numbers = 0       date_conflict = 0
```

---

## 6. Bước 5: Các hàm gán nhãn (LF)

Mã: `lfs.py`

Mỗi LF dựa trên **một loại bằng chứng** và trả về 1 (cùng sự kiện), 0 (khác) hoặc −1 (bỏ qua, không đủ cơ sở). Mọi phiếu dương đều đòi hai bài cách nhau **≤ 72 giờ** (`POS_MAX_HOURS`).

| LF | Phiếu dương | Phiếu âm | Độ phủ | Độ chính xác do label model ước lượng |
|---|---|---|---|---|
| `lf_repost` | cùng nhóm đăng lại | – | 0,06% | 0,98 |
| `lf_entity_overlap` | `ent_wjacc` ≥ 0,30 **và** `ent_score` ≥ 10 | `ent_wjacc` < 0,04 | 41,9% | 0,98 |
| `lf_head_entities` | `n_head_shared` ≥ 2 | – | 2,6% | 0,88 |
| `lf_tfidf_head` | `cos_head` ≥ 0,45 | `cos_head` < 0,06 | 57,8% | 1,00 |
| `lf_tfidf_lead` | `cos_lead` ≥ 0,40 | `cos_lead` < 0,08 | 60,4% | 1,00 |
| `lf_shared_number` | `n_numbers` ≥ 1 **và** `ent_score` ≥ 3 | – | 0,4% | 0,91 |
| `lf_time_far` | – | `dt_hours` > 72 | 44,4% | 0,93 |
| `lf_category_mismatch` | – | khác chuyên mục **và** `ent_wjacc` < 0,12 | 41,3% | 1,00 |

Ba nguyên tắc khi thiết kế:
1. **"Cùng chuyên mục" không bao giờ là phiếu dương.** Cùng một sự kiện thường nằm ở chuyên mục khác nhau giữa các báo, ví dụ "Kinh doanh" ở báo này và "Pháp luật" ở báo kia. Dùng nó làm phiếu dương sẽ chặn đúng các cặp khác báo, là thứ đề tài muốn học (phan-tich §3.1).
2. **Mỗi LF dùng một loại bằng chứng khác nhau**: thực thể, từ vựng, con số, thời gian, chuyên mục. Nhờ vậy khi chúng đồng thuận, label model mới có thông tin để ước lượng độ tin của từng LF.
3. **Ngưỡng ban đầu chọn theo phân bố đặc trưng và đọc mẫu**, chưa tối ưu. Ngưỡng được chỉnh lại sau khi đo trên tập audit (mục 9).

Ví dụ ở trên: chỉ `lf_entity_overlap` bỏ phiếu **dương** (wjacc 0,40 ≥ 0,30, score 69,95 ≥ 10). Các LF khác đều bỏ qua: cosine 0,31 nằm giữa hai ngưỡng, hai bài cách nhau 1 giờ, cùng chuyên mục.

**Luật phủ quyết** `veto_dated_series`: nếu `date_conflict = 1` thì p bị ép về 0,02, **bất kể** các LF nói gì. Mục 8.2 giải thích vì sao đây là luật phủ quyết chứ không phải một phiếu.

---

## 7. Bước 6: Gộp phiếu bằng label model

Mã: `label_model.py`

### 7.1 Ý tưởng

Ta có ma trận phiếu L kích thước 327.230 × 8, nhưng **không có nhãn thật**. Mô hình Dawid–Skene giả định có một nhãn ẩn y ∈ {0, 1}. Mỗi LF j có một ma trận nhầm lẫn P(phiếu_j | y) trên ba giá trị {0, 1, bỏ qua}, và các LF độc lập với nhau khi đã biết y.

Thuật toán EM học các tham số này **chỉ từ việc các LF đồng thuận hay mâu thuẫn với nhau**:

```
khởi tạo:  q_i = P(y_i = 1) theo đa số phiếu
lặp:
  M-step:  P(phiếu_j = v | y) ∝ Σ_i [trọng số lớp y của cặp i] · [phiếu_j của cặp i = v] + 1 (làm trơn)
  E-step:  q_i = P(y=1) · Π_j P(phiếu_ij | y=1)  /  Σ_y P(y) · Π_j P(phiếu_ij | y)
đến khi hội tụ
```

Một LF bỏ qua cũng là thông tin. Ví dụ `lf_head_entities` chỉ bỏ phiếu dương; nếu nó im lặng thì đó là bằng chứng yếu cho lớp âm. Cách xử lý này giống `LabelModel` của Snorkel. Mình viết lại bằng numpy (77 dòng) để khỏi phải cài PyTorch.

### 7.2 Hai chốt chặn (thêm vào sau khi gặp lỗi, xem mục 8.1)

- **Prior cố định = 0,10.** Đây là tỉ lệ cặp cùng sự kiện trong tập ứng viên, tương đương tham số `class_balance` của Snorkel. EM không được tự học giá trị này. Con số 0,10 dựa trên quan sát: 9,0% số cặp có ít nhất một phiếu dương.
- **Không có phiếu dương nào thì p ≤ 0,5.** Không có bằng chứng dương thì không thể là cặp dương.

Ví dụ ở trên: một phiếu dương từ `lf_entity_overlap` (độ chính xác ước lượng 0,98) cộng các LF âm đều im lặng cho ra **p = 0,9966**.

### 7.3 Kết quả

| | |
|---|---|
| Cặp có p ≥ 0,85 | 20.139, trong đó **67% khác báo** |
| Cặp mà các LF mâu thuẫn nhau | 0,57% |
| Cặp không LF nào bỏ phiếu | 10,7% (p bị chặn ở 0,5, không dùng) |
| Cặp bị phủ quyết vì khác ngày | 1.460, trong đó 353 cặp label model đã cho p ≥ 0,85 |

---

## 8. Hai lỗi gặp trên đường đi và cách sửa

### 8.1 EM suy biến: 124 nghìn cặp "dương" không có bằng chứng

**Lần chạy đầu**, prior do EM tự học, ra kết quả:

```
label_model_prior = 0,444      cặp p ≥ 0,85 = 124.049
→ trong đó chỉ 29.530 cặp có ≥ 1 phiếu dương; 94.519 cặp KHÔNG có phiếu dương nào
```

**Nguyên nhân:** các LF âm như `lf_time_far` và `lf_category_mismatch` là một chiều, chỉ bỏ phiếu âm. EM tìm ra một nghiệm "dễ" nhưng sai: lớp 1 = "những cặp mà các LF âm cùng im lặng". Một cặp cùng chuyên mục, cách nhau 2 ngày, không trùng gì đặc biệt cũng bị đẩy lên p ≈ 1.

**Sửa:** cố định prior và thêm chốt "không có phiếu dương thì p ≤ 0,5" (mục 7.2). Có test chặn hồi quy là `test_cap_khong_co_phieu_duong_nao_khong_duoc_coi_la_duong`.

So sánh các giá trị prior (chạy trên cùng ma trận phiếu):

| prior | cặp p ≥ 0,85 | % khác báo |
|---|---|---|
| EM tự học (0,444) | 29.530 (sau khi chặn) | 61% |
| 0,05 | 26.649 | 61% |
| **0,10 (đã chọn)** | ~27.000 | 61% |
| 0,20 | 28.417 | 61% |

Kết quả không nhạy với giá trị prior, nên chọn 0,10 là an toàn. Sau khi thêm luật 72h và luật phủ quyết, số cặp dương còn 20.139.

### 8.2 Chuỗi bài theo ngày: label model tin nhầm TF-IDF

Đọc mẫu cặp dương thấy những cặp như:

```
"Giá Bitcoin hôm nay 8.9.2026: …"   ↔   "Giá Bitcoin hôm nay 7.9.2026: …"
"Lịch thi đấu bóng đá hôm nay 31/8" ↔   "Lịch thi đấu bóng đá hôm nay 29/8"
```

Tiêu đề gần như y hệt nhau nên hai LF TF-IDF bỏ phiếu dương rất mạnh. Ban đầu "khác ngày" được viết thành **một LF âm**. Label model ước lượng LF này chỉ đúng **0,31**, vì nó thường mâu thuẫn với TF-IDF, rồi gần như bỏ qua nó. Thực ra ở đúng loại cặp này, ngày tháng mới đúng còn TF-IDF sai.

**Sửa:** chuyển thành **luật phủ quyết** áp dụng sau label model, ép p = 0,02. Đây cũng là một bài học khi thiết kế: một LF chuyên bắt lỗi của các LF khác không nên bỏ phiếu chung với chúng, vì label model sẽ đánh giá nó thấp.

Thêm vào đó, mọi phiếu dương đều đòi **≤ 72h**. Trước khi có luật này, các cặp như "Alcaraz vòng 1" với "Alcaraz vòng 3" cách nhau 4–5 ngày vẫn được gán dương.

---

## 9. Bước 7: Chia dữ liệu và chọn dữ liệu train

Mã: `build.py → assign_split()`, `select_training()`

### 9.1 Chia theo thời gian (tránh rò rỉ)

```
──────── train (< 11/9) ────────┤ gap 48h ├──── holdout (≥ 13/9) ────
         23.391 bài               1.458 bài      3.876 bài
```

Cặp yếu được sinh từ toàn bộ kho. Nếu cửa sổ dùng để đánh giá nằm lẫn trong dữ liệu train, mô hình đã "thấy" chính các cặp đánh giá (phan-tich §3.8). Vì vậy chỉ cặp có **cả hai bài thuộc train** mới vào tập huấn luyện. Cặp thuộc holdout dùng cho audit. Cặp vắt qua hai vùng bị bỏ.

### 9.2 Chọn bộ ba (anchor, positive, negative)

Duyệt các cặp theo p giảm dần:
- **Positive:** p ≥ 0,85, không phải bài đăng lại, tối đa 3 positive cho mỗi anchor để vài sự kiện lớn không chiếm hết dữ liệu.
- **Negative khó:** trong các ứng viên của anchor, chọn bài **giống anchor nhất về từ vựng** (`cos_lead` cao nhất) mà vẫn có:
  - p(anchor, c) ≤ 0,15 (chắc chắn khác sự kiện), và
  - p(positive, c) ≤ 0,5. Nếu c lại cùng sự kiện với positive thì nó không phải negative.

Một ví dụ bộ ba thật:

```
A: Ngân hàng Trung ương Trung Quốc mua hơn 20 tấn vàng trong tháng 8, nâng dự trữ lên 2.387 tấn…
P: Trung Quốc mua hơn 20 tấn vàng dự trữ. Ngân hàng Trung ương Trung Quốc (PBOC) tiếp tục mua vàng…
N: Hà Lan rút 86 tấn vàng khỏi Mỹ và Canada vì lo ngại bất ổn chính trị. Ngày 2-9, Hà Lan thông báo…
```

Negative "khó" buộc mô hình học **ranh giới sự kiện** chứ không chỉ ranh giới chủ đề. Nếu chỉ có negative ngẫu nhiên kiểu "vàng" với "bóng đá" thì TF-IDF cũng đã phân biệt được.

### 9.3 Đầu ra

| File | Số dòng | Dùng cho |
|---|---|---|
| `train_triplets.jsonl` | 10.005 (9.947 có negative), 64% khác báo, 5.958 bài làm anchor | `MultipleNegativesRankingLoss`, `GISTEmbedLoss` |
| `train_pairs.jsonl` | 177.499 cặp có p ≥ 0,85 hoặc ≤ 0,15 | `CoSENTLoss`, `AnglELoss` với `score` = p |
| `pairs.jsonl` | 327.230 | phân tích lỗi: phiếu từng LF và đặc trưng |
| `articles.jsonl` | 28.725 | văn bản + `split` + `dup_group` |
| `audit_sample.csv` | 400 | gán tay hoặc gán bằng LLM để đo chất lượng |
| `report.json` | – | thống kê và tham số của lần chạy |

---

## 10. Bước 8: Đo chất lượng nhãn yếu

### 10.1 Lấy mẫu audit

400 cặp lấy từ **cửa sổ holdout** (không dính vào dữ liệu train), phân tầng theo bảng 4 khoảng p × (cùng báo / khác báo), mỗi ô 50 cặp, thứ tự xáo trộn. Lấy phân tầng để đo được **cả** precision (khoảng p cao) **lẫn** tỉ lệ bỏ sót (khoảng p thấp). Nếu lấy ngẫu nhiên, gần như toàn bộ mẫu sẽ rơi vào khoảng p < 0,1.

### 10.2 Gán bằng Claude (LLM làm giám khảo)

Cách làm:
1. Bỏ cột `p` và `p_bin` (**gán mù**), chỉ giữ tên báo, tiêu đề, sapo và khoảng cách giờ.
2. Chia 400 cặp thành **8 cụm × 50 cặp**, mỗi cụm khoảng 12k token, để không cụm nào làm tràn context.
3. Chạy 8 subagent Claude song song. Cả 8 dùng **cùng một hướng dẫn** với định nghĩa sự kiện ở mục 0 và các ví dụ biên cho nhãn 1 và 0. Mỗi subagent chỉ được đọc, không được chạy code tính độ tương đồng.
4. Mỗi cặp trả về `label` (1 / 0 / ?), `confidence` và `reason` (≤ 20 từ).
5. Gộp kết quả vào `data/weak_labels/v1/audit_labeled_llm.csv` (cột `label_llm`). Cột `label_human` vẫn để trống.

Claude gán 113 cặp là 1 và 287 cặp là 0, không có "?". Có 294 cặp độ tin cao, 89 trung bình, 17 thấp.

### 10.3 Kết quả (CI 95% bằng bootstrap, 2.000 lần lấy mẫu)

| p của nhãn yếu | Cùng báo | Khác báo | Tất cả |
|---|---|---|---|
| 0,00–0,10 | 0,02 | 0,02 | **0,02** [0,00; 0,05] |
| 0,10–0,50 | 0,14 | 0,16 | 0,15 [0,09; 0,22] |
| 0,50–0,85 | 0,20 | 0,38 | 0,29 [0,20; 0,38] |
| 0,85–1,00 | **0,54** | **0,80** | **0,67** [0,58; 0,76] |

- Tỉ lệ cùng sự kiện tăng đều qua các khoảng p, tức label model **xếp thứ tự đúng**.
- **Cặp âm rất sạch**: chỉ 2% cặp p < 0,1 thực ra là cùng sự kiện.
- **Cặp dương khác báo đạt mốc 0,8**. **Cặp dương cùng báo chỉ 0,54**, kéo con số chung xuống 0,67, **chưa đạt** mốc precision ≥ 0,8 của dự án.

### 10.4 Phân tích lỗi

**33 cặp dương sai** chia thành ba nhóm:

| Nhóm | Số cặp (ước) | Ví dụ | Vì sao luật bị lừa |
|---|---|---|---|
| Một báo viết nhiều bài nối tiếp về cùng một giải hoặc cùng một nhân vật | ~15 | U23 VN gặp Kuwait ↔ gặp Philippines; Ronaldo thua Al Ain ↔ Ronaldo mua Al Nassr; Mourinho sau trận Elche ↔ sau trận Rayo | Chung đội, chung giải, chung cầu thủ nên trùng thực thể nhiều, cách nhau < 72h |
| **Lỗi code**: phủ quyết ngày tháng bỏ sót "ngày 16/9" | ~4 | "Giá vàng **ngày** 16/9" ↔ "… **ngày** 14/9"; "Chứng khoán **ngày** 17/9" ↔ "… 15/9" | Regex loại ngày lễ có chữ `ngày`, nên mọi ngày đứng sau chữ "ngày" đều bị coi là ngày lễ |
| Cùng khuôn tiêu đề, khác đối tượng | ~8 | "Kế hoạch thi hành **Luật Hòa giải**" ↔ "… **Luật Phát triển đô thị**"; kiểm tra Đảng ủy Quốc hội ↔ Đảng ủy Công an; "Bài 2" ↔ "Bài 3" của cùng loạt | TF-IDF cao vì khuôn chữ giống nhau, trong khi thực thể chính khác nhau |

**17 cặp bị bỏ sót** (cùng sự kiện nhưng p < 0,5), phần lớn ở p ≈ 0,36:
- dự thảo quy chế tuyển sinh đại học (6 cặp);
- vụ cháy 5 người chết ở Tây Hồ;
- đợt ngập ở Hà Nội;
- lễ vinh danh doanh nghiệp nộp ngân sách;
- chuyến thăm của Nhà vua Thái Lan.

Đây là những cặp **cùng sự kiện nhưng viết khác nhau**, tức đúng loại dương khó mà fine-tune cần học. Lần sửa LF tiếp theo nên dùng chúng làm ví dụ.

### 10.5 Giới hạn của việc gán bằng LLM

- Nhãn của Claude **không phải nhãn người**, nên chưa dùng làm tập vàng trong báo cáo cuối được.
- Cần một người gán độc lập khoảng 80–100 cặp, ưu tiên 17 cặp Claude tự đánh dấu độ tin thấp và khoảng p 0,5–0,85, rồi đo độ đồng thuận người–LLM bằng **Cohen's κ**. Nếu κ ≥ 0,7 thì có thể dùng nhãn LLM cho phần còn lại.
  File để gán đã có sẵn: `data/weak_labels/v1/human_label_100.csv`. File này gán mù, gồm 17 cặp độ tin thấp và 83 cặp lấy đều theo khoảng p × nhãn LLM. Gán xong thì chạy `make agreement` để ra κ và danh sách cặp lệch nhau.
- Cả 8 subagent dùng một định nghĩa sự kiện. Đổi định nghĩa, ví dụ coi cả ASIAD là một sự kiện, thì số liệu ở 10.3 sẽ thay đổi.

---

## 11. Việc tiếp theo

| # | Việc | Nhắm vào |
|---|---|---|
| 1 | Bỏ `ngày` khỏi regex ngày lễ (`pairs.py`, `_HOLIDAY`) và thêm test "Giá vàng ngày 16/9" | lỗi code ở 10.4 |
| 2 | Phủ quyết khi tiêu đề hai bài có **thực thể chính cùng loại nhưng khác nhau**: hai đối thủ khác nhau, hai luật khác nhau, hai cơ quan khác nhau | nhóm lỗi 1 và 3 |
| 3 | Cặp **cùng báo** phải có bằng chứng mạnh hơn: ngưỡng cao hơn, hoặc phải có thêm phiếu thực thể ở tiêu đề | precision cùng báo 0,54 |
| 4 | Bổ sung alias: `Sở Y tế tỉnh X` ↔ `Sở Y tế X`, và các dạng tương tự | gộp thực thể |
| 5 | Chạy lại và đo trên **chính 400 cặp này**, ghép theo `article_id`, để so trước và sau một cách công bằng | |
| 6 | Người gán khoảng 100 cặp và đo κ người–LLM | độ tin của phép đo |
| 7 | Khi precision ≥ 0,8 thì fine-tune hai mô hình embedding (PhoBERT bi-encoder, multilingual-e5) và so với bản zero-shot cùng baseline TF-IDF + thực thể | mục tiêu chính |

---

---

## 12. v2: những gì đã sửa và kết quả

Đầu ra: `data/weak_labels/v2/`. v1 được giữ nguyên ở `data/weak_labels/v1/` và trên R2 (`weak_label_NguyenDinhHieu/`).

### 12.1 Cách làm: chỉnh trên một mẫu, đo trên mẫu khác

| Tập | Dùng để | Kích thước |
|---|---|---|
| 399 cặp audit v1 có nhãn Claude (`v1/audit_labeled_llm_ids.csv`) | **chỉnh**: chọn phương án chặn, hiệu chỉnh p | 399 |
| Mẫu audit v2 mới, **không trùng** tập trên (`v2/audit_labeled_llm.csv`) | **đo** precision cuối cùng | 400 |
| 3 vòng × 100 cặp (anchor, negative) (`v2/negative_check_llm.csv`) | đo chất lượng negative khó; vòng 3 chưa từng được dùng để chỉnh | 300 |

Mọi nhãn đều do Claude gán mù (không thấy p), theo cùng một hướng dẫn với v1.

### 12.2 Danh sách thay đổi

| # | Thay đổi | Vì sao (bằng chứng) | Mã |
|---|---|---|---|
| 1 | Bỏ chữ `ngày` khỏi regex ngày lễ | "Giá vàng **ngày** 16/9" bị coi là ngày lễ nên chuỗi bài theo ngày lọt qua phủ quyết | `pairs.py` `_HOLIDAY` |
| 2 | Giữ `Ý`/`Á` (địa danh 1 chữ cái: nước Ý, châu Á) | luật "< 2 ký tự" bỏ mất 339 lần nhắc (Ý 327, Á 12) | `entities.py` |
| 3 | Danh sách từ chung không áp cho PER | bỏ nhầm tên người "Trường", "Đạo" | `entities.py` |
| 4 | Mảnh từ viết thường chỉ bỏ khi là **âm tiết tiếng Việt** | bỏ nhầm thương hiệu "adidas", "vivo" | `_is_vi_syllable()` |
| 5 | Thêm tiền tố `đặc khu`; bỏ cấp hành chính **giữa** tên cơ quan | "Sở Y tế **tỉnh** Gia Lai" ≠ "Sở Y tế Gia Lai" | `_ADMIN_PREFIX`, `_INNER_ADMIN` |
| 6 | **Nối tên một chữ với tên đầy đủ trong cùng bài** ("Nguyễn Văn Tuấn … ông Tuấn"); hai tên đầy đủ cùng đuôi thì không nối | tên một chữ là 33% số PER, trước đây bị hạ trọng số dù xác định được là ai | `article_entities()` |
| 7 | Bỏ 2 alias không bao giờ dùng | đo: 0 lần khớp | `configs/entity_aliases.yaml` |
| 8 | Gộp `lf_tfidf_head` + `lf_tfidf_lead` → `lf_lexical` | hai LF bỏ phiếu giống nhau 75% số lần, label model đếm một tín hiệu hai lần | `lfs.py` |
| 9 | Thêm nhóm bằng chứng; **cặp cùng báo cần ≥ 2 nhóm** (thực thể / từ vựng / con số / ngữ nghĩa) | trên 399 cặp chỉnh: cặp cùng báo có 1 nhóm đúng 0,57, có ≥ 2 nhóm đúng 0,86; cặp khác báo 1 nhóm đã 0,82 | `FAMILY`, `gate()` |
| 10 | Phủ quyết khi mỗi tiêu đề có một văn bản (DOC) mà bài kia không hề nhắc | "Luật Hòa giải" ↔ "Luật Phát triển đô thị" | `veto_title_doc` |
| 11 | **Hiệu chỉnh p** bằng isotonic regression, tách cùng báo / khác báo | v1: p trung bình 1,00 nhưng chỉ đúng 0,67 | `Calibrator` |
| 12 | Ngưỡng dương 0,85 → **0,80 trên p đã hiệu chỉnh**; ngưỡng âm 0,15 → 0,10 | p đã có nghĩa "tỉ lệ đúng" | `build.py` |
| 13 | Negative khó phải có độ giống anchor < 95% độ giống của positive | bài giống anchor hơn cả positive thường là dương bị bỏ sót | `neg_margin` |
| 14 | **Negative phải khác cả từ vựng (cos_lead < 0,15) lẫn thực thể (wjacc < 0,10)** | xem 12.3 | `content_negative()` |
| 15 | Negative không được nối với anchor/positive qua một bài trung gian | A ~ X ~ C thì C không phải negative của A | `safe_negative()` |
| 16 | `train_pairs` cân bằng 1 dương : 3 âm (một nửa âm khó, một nửa ngẫu nhiên), thêm cột `label` | v1: 92% là cặp âm | `select_training()` |
| 17 | Thêm `audit_ids.csv` | v1 phải ghép audit với id bằng tiêu đề, và lúc đầu ghép sai một nửa vì tra ngược thứ tự cặp | `build.py` |
| 18 | Code cho tín hiệu ngữ nghĩa (bge-m3): sinh ứng viên + `lf_dense` | bắt cặp viết khác nhau; **chưa chạy được**, xem 12.5 | `dense.py`, `make embed` |

Đã thử và **không** đưa vào:
- Đòi ≥ 2 nhóm cho **mọi** cặp: precision 0,89 nhưng chỉ giữ 15% cặp dương thật, số cặp dương train giảm từ 13,7k xuống 4,3k.
- Phủ quyết khi tổ chức/người/sự kiện/địa danh ở tiêu đề khác nhau: không đổi kết quả trên mẫu chỉnh, nên không có căn cứ.
- Nới ngưỡng thực thể/từ vựng để tăng recall: các cặp dương bị bỏ sót nằm đúng vùng chồng lấn với cặp âm (wjacc trung vị 0,12, cos 0,22). Nới ra thì precision giảm còn 0,63–0,67.

### 12.3 Negative khó: lỗi lớn chỉ lộ ra khi đo trực tiếp

v1 chưa từng đo negative. Khi đo ở v2:

| Vòng | Quy tắc chọn negative | Negative thực ra cùng sự kiện |
|---|---|---|
| 1 | bài giống anchor nhất mà p thấp | **29 / 100** |
| 2 | + khác nội dung theo **một** tiêu chí (cos < 0,15 **hoặc** wjacc < 0,04) | 12 / 100 |
| 3 | + khác nội dung theo **cả hai** tiêu chí (cos < 0,15 **và** wjacc < 0,10) | **2 / 100** |

**Nguyên nhân của vòng 1:** gần như mọi negative chỉ có phiếu âm từ `lf_time_far` (cách nhau > 72h). Nhưng một vụ việc thường được đưa tin trong nhiều ngày (vụ án có diễn biến mới, bảng xếp hạng được nhắc lại), nên "cách xa" không chứng minh là khác sự kiện.

Lỗi còn lại ở vòng 2 là các khía cạnh của **một sự kiện lớn nhiều ngày**: lễ đón và tuyên bố chung của cùng một chuyến thăm cấp Nhà nước, hay các bị cáo khác nhau của cùng một phiên toà. Quy tắc vòng 3 được chọn trên mẫu vòng 2 rồi **kiểm trên mẫu vòng 3 chưa từng xem**.

v1 chọn negative còn "giống anchor" hơn vòng 1, nên **negative của v1 nhiều khả năng sai từ 29% trở lên**.

### 12.4 Kết quả trên mẫu audit mới (400 cặp, độc lập)

| p (đã hiệu chỉnh) | Cùng báo | Khác báo | Tất cả (CI 95%) | p trung bình |
|---|---|---|---|---|
| 0,00–0,10 | 0,02 | 0,02 | 0,02 [0,00; 0,05] | 0,01 |
| 0,10–0,50 | 0,12 | 0,16 | 0,14 [0,08; 0,21] | 0,24 |
| 0,50–0,80 | 0,59 | 0,76 | 0,68 [0,59; 0,77] | 0,62 |
| **0,80–1,00** | **0,82** | **0,96** | **0,89 [0,83; 0,95]** | 0,96 |

- **Đạt mốc precision ≥ 0,8 của dự án**, kể cả với cặp cùng báo.
- Hiệu chỉnh khá sát: p trung bình gần với tỉ lệ thật. Ở khoảng trên cùng p vẫn hơi tự tin (0,96 so với 0,89), vì isotonic chỉ dựa trên khoảng 45 cặp dương mỗi nhóm.
- **So với v1 trên cùng các cặp** (377 cặp mà v1 cũng có): v1 gọi dương 191 cặp với precision 0,81; v2 gọi dương 100 cặp với precision 0,89. **Recall**: trong 172 cặp cùng sự kiện thật, v1 bắt 155, v2 bắt 89.

11 cặp dương còn sai, chủ yếu thuộc ba kiểu:
- chuỗi bài của một báo về các trận khác nhau trong cùng một giải (bóng chuyền nữ ASIAD: Việt Nam gặp Hồng Kông, Việt Nam gặp Qatar);
- "Lịch thi đấu hôm nay 13/9" với "Kết quả hôm nay 13/9";
- hai nghị quyết khác nhau không có số hiệu trong tiêu đề.

### 12.5 Dữ liệu train v2

| | v1 | v2 |
|---|---|---|
| Bộ ba | 10.005 | 4.051 (4.004 có negative) |
| Bài làm anchor | 5.958 | 2.846 |
| Bộ ba khác báo | 64% | 79% |
| Cặp có điểm | 177.499 (13.651 dương) | 18.312 (4.578 dương, tỉ lệ 1:3) |

Ít hơn khoảng 2,5 lần nhưng sạch hơn rõ rệt. Điều này đúng với nhận định trong kế hoạch của dự án: "vài nghìn cặp chất lượng có giá trị hơn nhiều cặp nhiễu".

### 12.6 Giới hạn còn lại

1. **Recall thấp.** Khoảng một nửa số cặp cùng sự kiện không được gán dương: đó là các cặp viết khác nhau, nằm trong vùng chồng lấn của tín hiệu thực thể và từ vựng. Cách sửa là **tín hiệu ngữ nghĩa**: code đã có (`dense.py`, `lf_dense`, `dense_candidates`). Nhưng mạng tới Hugging Face lúc làm chỉ đạt khoảng 0,2 MB/s và hai lần tải `bge-m3` (2,3 GB) đều đứt. Cách chạy trên Kaggle/Colab:
   ```bash
   uv sync --group embed && uv run --group embed python -m eventrank.weak_labels.dense
   # chép data/weak_labels/cache/BAAI__bge-m3.npz về máy rồi chạy lại: make weak-labels
   ```
   Khi có embedding, nên chỉnh lại `DENSE_POS` / `DENSE_NEG` trên tập chỉnh rồi đo lại trên một mẫu mới.
2. **Nhãn đối chiếu là của Claude**, chưa phải của người. Cần gán `v1/human_label_100.csv` rồi chạy `make agreement` để đo κ.
3. **Hiệu chỉnh dựa trên ít mẫu** (khoảng 45 cặp dương mỗi nhóm). Có thêm nhãn thì nên gộp mẫu audit v2 vào tập hiệu chỉnh, rồi đo lại trên một mẫu thứ ba.
4. Một số cặp **cùng sự kiện lớn nhiều ngày** vẫn bị coi là khác sự kiện (giới hạn 72h). Đây là câu hỏi về định nghĩa "sự kiện" mà nhóm cần chốt.

## 13. v3: tín hiệu ngữ nghĩa để tăng recall

Đầu ra: `data/weak_labels/v3/` (mặc định của `make weak-labels`). v1 và v2 giữ nguyên để so sánh.

### 13.1 Recall thật thấp hơn con số thô

Mẫu audit lấy đều 50 cặp mỗi tầng, trong khi các tầng có kích thước rất khác nhau. Ví dụ tầng 0,10–0,50 có rất nhiều cặp, khoảng 14% trong đó là dương thật. Vì vậy tỉ lệ thô trên mẫu **không phải** precision/recall thật. `evaluate.py` nhân mỗi cặp với N_tầng / n_tầng (ước lượng Horvitz–Thompson) và lấy khoảng tin cậy bằng bootstrap trong từng tầng.

| (p ≥ 0,8) | Recall thô trên mẫu | **Recall có trọng số** |
|---|---|---|
| v1 | 0,90 | 0,57 |
| v2 | 0,52 | **0,20** |

v2 sạch nhưng chỉ bắt được khoảng 1/5 số cặp cùng sự kiện trong tập ứng viên. Recall ở đây là **recall trong tập ứng viên của v2**: cặp cùng sự kiện không bao giờ trở thành ứng viên thì không đo được.

### 13.2 Thay đổi

| # | Thay đổi | Bằng chứng | Mã |
|---|---|---|---|
| 1 | Embedding zero-shot `paraphrase-multilingual-MiniLM-L12-v2` (ONNX int8, khoảng 135 MB). Mô hình khác họ với PhoBERT/e5. `bge-m3` (2,3 GB) không tải được vì mạng khoảng 0,2 MB/s và hai lần đều đứt | – | `dense.py` |
| 2 | Tải mô hình tự nối lại khi đứt mạng (HTTP Range), kiểm SHA-256 | test giả lập đứt mạng | `download_model()` |
| 3 | Sinh thêm ứng viên theo láng giềng ngữ nghĩa (cos ≥ 0,6, top 10, ±7 ngày) | +97 nghìn cặp | `dense_candidates()` |
| 4 | `lf_dense`: cos ≥ 0,80 là phiếu dương; < 0,30 là phiếu âm | trên tập chỉnh: ≥ 0,80 có precision 0,80; < 0,30 có 0/76 cặp là dương | `lfs.py` |
| 5 | **Ngữ nghĩa không được là bằng chứng dương duy nhất** | 45 cặp chỉ có phiếu ngữ nghĩa: 58% đúng (điểm chuẩn của hai trường khác nhau…); có thêm thực thể/từ vựng: 47/50 | `only_semantic()`, `gate()` |
| 6 | **Áp lại chốt chặn SAU hiệu chỉnh** | isotonic ánh xạ điểm 0,5 của cặp bị chặn thành 0,68, làm 1.796 cặp "chỉ ngữ nghĩa" lọt lại vào tầng mở rộng | `finalize()` |
| 7 | Negative phải khác nghĩa (cos < 0,55) | xếp negative theo độ giống ngữ nghĩa mà không chặn thì dễ chọn trúng cặp "cùng nghĩa, khác chữ" | `select_training()` |
| 8 | Thêm `train_triplets_extended.jsonl` (p ≥ 0,6, cột `tier`) | xem 13.3 | `build.py` |
| 9 | `evaluate.py`: precision/recall có trọng số theo tầng + CI | 13.1 | `evaluate.py` |
| 10 | `--force-pairs`: ép các cặp audit cũ vào tập ứng viên để đo lại đúng các cặp đó | – | `build.py` |

### 13.3 Kết quả (mẫu audit v2: 400 cặp, độc lập, Claude gán mù)

| | Precision (có trọng số) | Recall (có trọng số) | Bộ ba train |
|---|---|---|---|
| v2 (p ≥ 0,8) | 0,93 [0,88; 0,98] | 0,20 [0,16; 0,25] | 4.051 |
| **v3 lõi (p ≥ 0,8)** | **0,93** [0,85; 0,98] | **0,28** [0,22; 0,37] | **5.381** |
| v3 mở rộng (p ≥ 0,6) | 0,83 [0,75; 0,90] | 0,43 [0,35; 0,54] | 7.596 |

Các kiểm tra trên mẫu chưa từng dùng để chỉnh:
- Cặp dương **mới** do tín hiệu ngữ nghĩa sinh ra, tầng lõi: 0,94 [0,86; 1,00].
- **Riêng phần mở rộng** (0,6 ≤ p < 0,8): 0,69 [0,60; 0,79], đúng bằng p đã hiệu chỉnh (≈ 0,68).
- Negative khó: sai 2%.

**Kết luận:**
- **Tầng lõi** tăng recall 0,20 → 0,28 (+40% tương đối) mà precision giữ nguyên. Đây là dữ liệu train mặc định.
- **Tầng mở rộng** gấp đôi recall nhưng phần thêm vào chỉ đúng 0,69, dưới mốc 0,8, nên chỉ dùng làm thí nghiệm so sánh. Lỗi còn lại phần lớn là **các diễn biến khác nhau của một câu chuyện lớn** (đặc phái viên Mỹ tới Kyiv với điện đàm Trump–Putin), tức câu hỏi về định nghĩa sự kiện chứ không còn là lỗi kỹ thuật.

### 13.4 Chạy lại

```bash
make embed                                       # MiniLM, tải ~135 MB lần đầu, nhúng ~9 phút trên CPU
make weak-labels                                 # ~2,5 phút → data/weak_labels/v3/
uv run python -m eventrank.weak_labels.evaluate --system v3=data/weak_labels/v3/pairs.jsonl
```

Đổi sang `bge-m3` khi có mạng tốt: `make embed EMBED_MODEL=Xenova/bge-m3` (khoảng 590 MB). Sau đó **chỉnh lại `--dense-pos/--dense-neg` trên tập chỉnh** (thang cosine của mỗi mô hình khác nhau), chạy `make weak-labels EMBED_MODEL=Xenova/bge-m3`, rồi đo lại bằng `evaluate.py`.

## Phụ lục A: Chạy lại

```bash
make weak-labels                                   # ~2 phút, ~2 GB RAM, CPU
uv run python -m eventrank.weak_labels.build --help  # mọi tham số: cửa sổ, prior, ngưỡng, mốc holdout…
uv run pytest tests/weak_labels -q                 # 21 test
```

Tham số mặc định: `--window-hours 168 --holdout-start 2026-09-13 --gap-hours 48 --prior 0.10 --pos-threshold 0.85 --neg-threshold 0.15 --max-pos-per-anchor 3`.

## Phụ lục B: Vì sao không cần huấn luyện mô hình để tạo nhãn

| Thành phần | Có học từ dữ liệu không | Ghi chú |
|---|---|---|
| NER | Không (đã có trong Gold) | |
| TF-IDF | Không | chỉ đếm từ |
| Label model | Ước lượng khoảng 50 tham số (8 LF × 2 lớp × 3 giá trị) bằng EM trong vài giây | **không dùng nhãn thật** |
| Gán bằng LLM | Không | chỉ dùng để **đo** chất lượng, không dùng tạo dữ liệu train |

Mô hình duy nhất phải huấn luyện là **mô hình embedding**, ở bước sau, trên Kaggle/Colab, dùng `train_triplets.jsonl` / `train_pairs.jsonl`.
