# Dùng đầu ra gom cụm sự kiện để làm RAG

Bàn giao của Nguyễn Đình Hiếu, viết ngày 04/11/2026. Tài liệu dành cho người xây hệ thống hỏi–đáp (RAG) trên kho tin tức
của đồ án. Nội dung: gom cụm cho ra gì, lấy dữ liệu ở đâu, ý nghĩa từng bảng và cột, cách dựng kho truy hồi, và các cạm
bẫy phải biết trước. Các số liệu đo trên lần chạy `2026-11-03_v2`. Các đoạn code đã chạy thử trên DB thật.

## 0. Tóm tắt

- **Nên dùng bản dump Postgres** ở R2 `db_NguyenDinhHieu/v1/`. Cách cài có trong `README.md` của prefix đó. Trong dump có
  bài báo đầy đủ (`articles`), sự kiện (`events`), bài nào thuộc sự kiện nào (`event_articles`), điểm xu hướng theo giờ
  (`trend_scores`) và vector của từng bài (`article_embeddings`).
- Một **sự kiện** là một nhóm bài của nhiều báo cùng đưa một tin, khoá là `event_id` (ví dụ `E20260917-ec294af2`). Mỗi bài
  thuộc đúng một sự kiện.
- 19.938 sự kiện, nhưng **79% chỉ có 1 bài**. Sự kiện "thật" (≥ 2 bài) có 4.213 cái, gồm 13.000 bài.
- **Tên sự kiện do mô hình sinh, chưa có người duyệt**, ước tính khoảng 12% sai nghĩa. Câu trả lời của RAG phải dựa trên
  nội dung bài, không lấy tên làm sự thật.
- **Không có pgvector.** Vector lưu dạng `bytea`, nên tìm kiếm phải làm bằng numpy/FAISS hoặc một vector DB riêng
  (mục 5.4).

## 1. Gom cụm đã làm gì

```
Bài báo (tiêu đề + sapo)
  → embedding bkai_ft_v1_s44 (PhoBERT bi-encoder fine-tune cho bài toán "cùng sự kiện", tách từ pyvi, 768 chiều, chuẩn hoá L2)
  → gom cụm agglomerative average-linkage: cosine ≥ 0,83, chỉ nối các bài cách nhau ≤ 48 giờ
  → mỗi cụm = 1 sự kiện; medoid = bài gần tâm cụm nhất (bài đại diện)
  → đặt tên: ViT5 (vit5_v1_s42) cho sự kiện ≥ 2 bài, hậu kiểm thô (số, chữ hoa, lặp thực thể);
     rớt hậu kiểm → dùng tiêu đề medoid; sự kiện 1 bài → dùng tiêu đề bài
  → điểm xu hướng mỗi giờ (công thức t2: số nguồn hiệu dụng × log(1 + vận tốc có phân rã nửa đời 3h / mức nền theo giờ))
```

Code: `src/eventrank/clustering/`, `src/eventrank/naming/`, `src/eventrank/trending/`, điều phối ở
`src/eventrank/serving/pipeline.py`. Cấu hình: `configs/clustering.yaml`, `configs/pipeline.yaml`.

**Chất lượng gom cụm** (B-Cubed F1 trên tập vàng ngày 15/09/2026, 1 ngày, nhãn **do Claude gán và kiểm tra lại, chưa có
nhãn người**):

| Cách gom | B-Cubed F1 |
|---|---|
| Mỗi bài một cụm (mốc sàn) | 0,838 |
| TF-IDF + agglomerative | 0,927 |
| bkai zero-shot + agglomerative | 0,950 |
| **bkai fine-tune v1 + agglomerative (đang dùng)** | **0,967**, CI 95% [0,955; 0,976] |
| Pipeline chạy trên toàn kho, chấm lại trên 15/09 | 0,964 |

Hơn TF-IDF có ý nghĩa thống kê. Hơn bản zero-shot thì **chưa** có ý nghĩa thống kê. Lỗi còn lại chủ yếu là **tách thừa**
(một tin bị chia thành 2–3 sự kiện), xem mục 6.

## 2. Lấy dữ liệu ở đâu

| Cách | Ở đâu | Nên dùng khi |
|---|---|---|
| **A. Dump Postgres (khuyên dùng)** | R2 `db_NguyenDinhHieu/v1/eventrank_2026-11-04.dump` (147 MB) + `README.md` (cài Postgres, tải, `pg_restore` ≥ 18, kiểm tra) | Làm RAG: có toàn văn, URL, vector, đã ẩn tên đúng luật |
| B. CSV của lần chạy | R2 `events_NguyenDinhHieu/v2/` (`su_kien.csv`, `bai_su_kien.csv`, `xu_huong.csv`…) | Chỉ cần bảng nhẹ. ⚠ Có tên ViT5 của cửa sổ 14–15/09 (mục 6.3). Không có toàn văn: phải join Silver theo `article_id` |
| C. Silver gốc | R2 `silver/*/*.jsonl` | Cần bài báo thô, không cần sự kiện |

Với cách A, mọi truy vấn dưới đây chạy trên DB bạn đã khôi phục ở máy mình. Kết nối:

```python
import psycopg
conn = psycopg.connect("postgresql://eventrank:<mật khẩu>@127.0.0.1:5432/eventrank")
```

Không cần quyền ghi; RAG chỉ đọc.

## 3. Các bảng dùng cho RAG

```
sources 1─n articles 1─1 event_articles n─1 events 1─n trend_scores
                 │                              └─1─n event_names
                 └─1─n article_embeddings (theo model_version)
```

### `events`: một dòng một sự kiện

| Cột | Ý nghĩa |
|---|---|
| `event_id` | Khoá. `E<ngày bài đầu tiên YYYYMMDD>-<8 ký tự đầu article_id của bài đầu tiên>` |
| `display_name` | Tên đang hiển thị (đã áp luật ẩn tên). Đây là cột tên **duy nhất** nên dùng |
| `name_source` | `model` (ViT5 sinh), `medoid` (tiêu đề bài đại diện, khi tên mô hình rớt hậu kiểm hoặc bị ẩn), `title` (sự kiện 1 bài) |
| `name_hidden` | `true` = tên mô hình bị ẩn, hiển thị tiêu đề medoid (mục 6.3) |
| `size`, `n_sources`, `sources` | Số bài, số báo, `{"vnexpress": 3, …}` |
| `first_seen`, `last_seen` | Giờ đăng bài đầu tiên và cuối cùng (`timestamptz`) |
| `medoid_article_id`, `medoid_title` | Bài đại diện |
| `category_std` | Chuyên mục gặp nhiều nhất trong các bài (đã gộp cách viết khác nhau giữa các báo) |
| `total_score`, `peak_score`, `peak_at`, `top10_hours` | Tóm tắt điểm xu hướng: tổng điểm theo giờ (dùng để xếp "nổi bật"), điểm và lúc cao nhất, số giờ nằm trong top 10. NULL nếu sự kiện chưa từng là ứng viên |
| `status` | `open` hoặc `closed` (quá 48 giờ không có bài mới). Bỏ qua `merged`, `hidden` nếu sau này có |
| `algo_version`, `model_version`, `trend_version` | `v1`, `bkai_ft_v1_s44`, `t2` |

### `event_articles`: bài nào thuộc sự kiện nào

`article_id` (khoá, mỗi bài đúng một sự kiện), `event_id`, `is_medoid` (mỗi sự kiện tối đa một bài), `similarity` (cosine
trung bình với các bài khác cùng cụm; NULL với sự kiện 1 bài; trung bình 0,895, thấp nhất 0,797). Có thể dùng
`similarity` để xếp bài "trung tâm" lên trước khi nhồi ngữ cảnh.

### `articles`: bài báo đầy đủ (theo hợp đồng Silver)

`article_id` (= sha256(url)), `url`, `source`, `category` (chuyên mục nguyên văn của báo), `title`, `sapo`, `author`,
`published_at`, `content_text` (toàn văn), `quality_flags` (`no_body`, `short_body`, `missing_sapo`, `missing_author`).

### `article_embeddings`: vector có sẵn

`(article_id, model_version)` → `vec` (`bytea`, 768 × float32 little-endian, đã chuẩn hoá L2), `dim`, `content_hash`.
Vector được tính từ **tiêu đề + ". " + sapo**, không phải toàn văn.

### `trend_scores`: điểm xu hướng mỗi giờ

`(trend_version, t, event_id)` → `score`, `rank` (thứ hạng tại giờ t trong mọi ứng viên), `n_articles` (số bài tới t),
`n_articles_3h`, `n_sources`, `n_sources_eff`, `velocity`. Có từ 01/08 đến 19/09/2026 (1.122 mốc giờ có ứng viên),
18.396 dòng. Chỉ sự kiện có ≥ 2 bài tới thời điểm t và ≥ 1 bài trong 3 giờ gần nhất mới là ứng viên.

### Bảng phụ

`event_names` (lịch sử tên; `checks.ly_do_fallback` cho biết vì sao tên mô hình bị thay), `category_map` (chuyên mục gốc
→ chuyên mục chung), `sources` (tên hiển thị của báo), `worker_runs` (các lần nạp; `versions->>'run_id'` = lần chạy
pipeline nguồn).

## 4. Dữ liệu trông thế nào

| | |
|---|---|
| Bài | 28.725 bài của 6 báo: Tuổi Trẻ 5.447 · Thanh Niên 5.154 · VietnamNet 4.645 · Nhân Dân 4.517 · VnExpress 4.485 · Báo Chính phủ 4.477 |
| Thời gian | Bài đăng từ 2008 đến 19/09/2026, nhưng 76% nằm trong 01/08–19/09/2026. Từ 17/09 thiếu VnExpress và VietnamNet |
| Kích thước sự kiện | 1 bài: 15.725 · 2–4 bài: 3.725 · 5–9 bài: 393 · 10–19 bài: 75 · ≥ 20 bài: 20 (lớn nhất 92) |
| Số báo (sự kiện ≥ 2 bài) | 1 báo: 1.154 · 2: 2.014 · 3: 645 · 4: 273 · 5: 90 · 6: 37 |
| Chuyên mục (sự kiện ≥ 2 bài) | Chính trị 549 · Pháp luật 500 · Thể thao 488 · Giáo dục 481 · Thế giới 454 · Kinh tế 423 · Du lịch 365 · KH–CN 336 · Sức khỏe 333 · Văn hóa 284 |
| Độ dài toàn văn | Trung vị 2.897 ký tự (p10 1.435, p90 5.631, dài nhất 79.051). 183 bài toàn văn rỗng, 8 bài thiếu sapo |

Ví dụ một sự kiện:

```
E20260902-dc986ab0 · "Lãnh đạo nhiều nước chúc mừng 81 năm Quốc khánh Việt Nam"
8 bài · 6 báo {nhandan: 2, baochinhphu: 2, tuoitre: 1, thanhnien: 1, vnexpress: 1, vietnamnet: 1}
02/09 06:38 → 04/09 02:39 (giờ VN) · Thế giới · tổng điểm xu hướng 86,1
```

## 5. Gợi ý thiết kế RAG

### 5.1 Đơn vị truy hồi: hai tầng

Gom cụm có ích cho RAG ở chỗ nó cho biết **những bài nào nói cùng một chuyện**. Gợi ý:

1. **Truy hồi ở mức bài, hoặc đoạn của bài**, mỗi mục mang metadata `event_id`, `source`, `published_at`, `url`.
2. **Mở rộng theo sự kiện:** từ các bài tìm được, gom theo `event_id` rồi lấy thêm vài bài cùng sự kiện của **báo khác**.
   Ngữ cảnh đưa vào mô hình sẽ đa nguồn, ít trùng lặp, và có đủ URL để trích dẫn.
3. Có thể thêm **thẻ sự kiện** (tên + thời gian + nguồn + tiêu đề, sapo các bài) làm một tài liệu riêng, để trả lời câu hỏi
   kiểu "chuyện X diễn ra thế nào".

Lý do không chỉ tìm theo bài: một tin thường có 3–6 bài gần như cùng nội dung, nên top-k sẽ bị một tin chiếm hết. Gom theo
`event_id` giúp đa dạng hoá câu trả lời ngay.

### 5.2 Dựng kho tài liệu theo sự kiện (đã chạy thử: 4.213 sự kiện ≥ 2 bài)

```python
rows = conn.execute("""
SELECT e.event_id, e.display_name, e.size, e.n_sources, e.first_seen, e.last_seen, e.category_std,
       a.article_id, a.url, a.source, a.published_at, a.title, a.sapo, ea.is_medoid
FROM events e JOIN event_articles ea USING (event_id) JOIN articles a USING (article_id)
WHERE e.status IN ('open', 'closed') AND e.size >= 2
ORDER BY e.event_id, a.published_at""").fetchall()
docs = {}
for eid, name, size, nsrc, f, l, cat, aid, url, src, pub, title, sapo, med in rows:
    d = docs.setdefault(eid, {"event_id": eid, "ten": name, "size": size, "n_sources": nsrc,
                              "tu": f, "den": l, "chuyen_muc": cat, "bai": []})
    d["bai"].append({"article_id": aid, "url": url, "source": src, "published_at": pub,
                     "title": title, "sapo": sapo, "is_medoid": med})
```

Muốn lấy cả sự kiện 1 bài thì bỏ `AND e.size >= 2`. Muốn lấy toàn văn thì thêm `a.content_text`.

### 5.3 Chia đoạn toàn văn

Vector có sẵn chỉ phủ tiêu đề + sapo. Muốn truy hồi theo nội dung chi tiết (số liệu, lời phát biểu) thì phải tự chia đoạn
`content_text`. Toàn văn trung vị khoảng 2.900 ký tự, nên chia đoạn khoảng 800–1.200 ký tự theo ranh giới đoạn văn (`\n`),
mỗi đoạn kèm tiêu đề bài ở đầu, sẽ cho trung bình 3–4 đoạn mỗi bài. Đây là gợi ý xuất phát, cần đo lại trên tập câu hỏi
của bạn. Bỏ các bài có `quality_flags` chứa `no_body`.

### 5.4 Vector: dùng sẵn hay tự tính

**Dùng sẵn `article_embeddings`.** Mã hoá câu hỏi bằng **đúng mô hình và đúng tiền xử lý** (mô hình trên R2 ở
`models/embedding_v1_NguyenDinhHieu/`, ở máy Hiếu là `data/models/bkai_ft_v1_s44/`):

```python
import unicodedata, numpy as np
from pyvi import ViTokenizer
from sentence_transformers import SentenceTransformer

ids, mats = [], []
for aid, blob in conn.execute("SELECT article_id, vec FROM article_embeddings "
                              "WHERE model_version = 'bkai_ft_v1_s44'"):
    ids.append(aid)
    mats.append(np.frombuffer(blob, dtype="<f4"))
E = np.stack(mats)                                     # (28725, 768), ~88 MB, nạp ~4 s

model = SentenceTransformer("<thư mục model>", device="cpu")
def encode(text):                                      # BẮT BUỘC: NFC + tách từ pyvi, như lúc train
    return model.encode([ViTokenizer.tokenize(unicodedata.normalize("NFC", text))],
                        normalize_embeddings=True)[0]

scores = E @ encode("U23 Việt Nam thắng Philippines")  # cosine (vector đã chuẩn hoá)
top = np.argsort(-scores)[:20]                         # rồi gom theo event_id (bảng event_articles)
```

Đã chạy thử, ba sự kiện đứng đầu sau khi gom theo `event_id`:

| Câu hỏi | Kết quả |
|---|---|
| "U23 Việt Nam thắng Philippines" | "U23 Việt Nam thắng Philippines 2-0, vào…" 0,859 · "U23 Việt Nam thắng Philippines lượt trận…" 0,845 · "Đội tuyển Việt Nam gặp Myanmar…" 0,835 |
| "giá vàng tăng" | 3 sự kiện giá vàng của các ngày khác nhau, khoảng 0,64 |
| "xét tuyển đại học 2027" | "Bộ GD-ĐT dự kiến siết phương thức xét tuyển…" 0,812 · 2 sự kiện tuyển sinh khác ≈ 0,74 |

Ví dụ 2 cho thấy rõ: **câu hỏi không có thời gian thì mô hình không phân biệt được "ngày nào"**. Hãy lọc theo
`published_at` (mục 5.6).

**Hạn chế của mô hình này với RAG:**
- Mô hình được huấn luyện để so **bài với bài** ("hai bài có cùng sự kiện không"), không phải câu hỏi với tài liệu. Câu
  hỏi ngắn, giống tiêu đề thì chạy tốt như trên; câu hỏi dài, dạng hỏi đáp thì chưa được đo.
- Chỉ đọc tối đa 256 token tiêu đề + sapo. Muốn mã hoá các đoạn toàn văn thì nên thử thêm một bộ truy hồi tổng quát (ví dụ
  `bkai-foundation-models/vietnamese-bi-encoder` bản gốc, hoặc `intfloat/multilingual-e5-*` với tiền tố
  `query:`/`passage:`) và **so trên tập câu hỏi của bạn**.
- Nên kết hợp với BM25 trên tiêu đề + sapo + toàn văn (hybrid). Tên riêng và con số thường được BM25 bắt tốt hơn vector.

**Lưu trữ vector:** 28.725 × 768 float32 nên tìm brute-force bằng numpy là đủ nhanh (một phép nhân ma trận). Muốn dùng
FAISS, Chroma hay Qdrant thì xuất từ bảng trên. Postgres của dự án **cố ý không cài pgvector**; muốn dùng pgvector thì cài
trong DB riêng của bạn, đừng đưa vào migration chung.

### 5.5 Mở rộng ngữ cảnh theo sự kiện

```sql
-- các bài của một sự kiện, bài trung tâm và đa nguồn trước
SELECT a.source, a.published_at, a.title, a.sapo, a.url, ea.similarity
FROM event_articles ea JOIN articles a USING (article_id)
WHERE ea.event_id = %(event_id)s
ORDER BY ea.is_medoid DESC, ea.similarity DESC NULLS LAST, a.published_at;
```

Gợi ý: mỗi sự kiện lấy tối đa 1–2 bài cho mỗi báo, ưu tiên bài medoid. Đưa vào prompt cả nguồn và giờ đăng để mô hình trích
dẫn.

### 5.6 Câu hỏi về thời gian và xu hướng: dùng SQL, không dùng vector

Các câu như "hôm 10/9 có tin gì nổi bật", "sự kiện nóng nhất tuần này" nên trả lời bằng truy vấn, rồi mới đưa bài vào ngữ
cảnh:

```sql
-- top 10 xu hướng lúc 08:00 ngày 19/09/2026
SELECT ts.rank, e.event_id, e.display_name, round(ts.score::numeric, 3) AS diem, ts.n_articles, ts.n_sources
FROM trend_scores ts JOIN events e USING (event_id)
WHERE ts.trend_version = 't2' AND ts.t = '2026-09-19 08:00+07'
ORDER BY ts.rank LIMIT 10;

-- sự kiện "nổi bật" nhất trong một khoảng ngày
SELECT event_id, display_name, size, n_sources, first_seen, round(total_score::numeric, 1) AS tong_diem
FROM events
WHERE size >= 2 AND first_seen < '2026-09-11+07' AND last_seen >= '2026-09-10+07'
ORDER BY total_score DESC NULLS LAST LIMIT 10;
```

Với truy hồi bằng vector, thêm bộ lọc `published_at` khi câu hỏi có mốc thời gian. Câu hỏi về thời điểm ngoài
01/08–19/09/2026 thì nên trả lời "không có dữ liệu", vì bài ngoài khoảng này rất thưa.

### 5.7 Khung prompt gợi ý

```
Bạn trả lời câu hỏi về tin tức Việt Nam CHỈ dựa trên các bài báo dưới đây. Mỗi ý phải ghi nguồn [số].
Nếu các bài không đủ thông tin, nói rõ là không đủ. Không suy đoán ngoài bài.

[1] Tuổi Trẻ · 17/09/2026 08:15 · <tiêu đề>
<sapo / đoạn văn>
[2] VnExpress · 17/09/2026 09:02 · <tiêu đề>
…
Câu hỏi: …
```

Có thể đưa tên sự kiện (`display_name`) vào làm tiêu đề nhóm, nhưng đừng để mô hình lấy tên đó làm dữ kiện (mục 6.2).

## 6. Cạm bẫy (đọc trước khi dùng)

1. **Phần lớn "sự kiện" chỉ có 1 bài** (15.725/19.938). Đó là tin lẻ, chưa báo nào khác đưa. Muốn nói "nhiều báo cùng đưa"
   thì lọc `size >= 2` hoặc `n_sources >= 2`.
2. **Tên do mô hình sinh, chưa người duyệt.** Một kiểm tra độc lập ước khoảng 12% tên mô hình sai nghĩa hoặc bịa chi tiết;
   hậu kiểm hiện tại chỉ bắt được lỗi thô. Câu trả lời phải dựa trên bài. Nếu cần tên "an toàn" thì dùng `medoid_title`
   (tiêu đề bài thật).
3. **Tên của cửa sổ 14–15/09/2026 đang bị ẩn có chủ đích** (1.027 sự kiện, trong đó 363 sự kiện ≥ 2 bài, `name_hidden =
   true`): `display_name` = tiêu đề bài medoid. Cửa sổ này là tập test của bước đặt tên, và người viết tên cho tập test phải
   không thấy tên mô hình. Vì vậy:
   - **Không** khôi phục tên từ CSV `events_NguyenDinhHieu/v2/` (`ten_su_kien.csv`, `su_kien.csv`, `events.json`) để đưa vào RAG.
   - Hỏi Hiếu trước nếu định dùng 14–15/09 làm tập đánh giá cho RAG.
4. **Tách thừa và gộp nhầm vẫn có.** F1 0,964 chứ không phải 1. Ví dụ thật: hai sự kiện riêng cho cùng một trận "U23 Việt
   Nam thắng Philippines" (mục 5.4); ba sự kiện iPhone ngày 08–10/09 nằm sát nhau trên bản đồ vector, nghi tách thừa
   nhưng chưa kiểm tra (`E20260908-a8e2759e`, `E20260909-02ac65ea`, `E20260910-f13de392`). Khi trình bày câu trả lời, nên gộp các
   sự kiện có tên hoặc tiêu đề rất giống nhau và cách nhau ít giờ. Ngược lại, đôi khi một cụm lớn chứa bài "cùng câu chuyện
   nhưng khác diễn biến".
5. **Gom cụm chạy trên toàn kho, một lần.** Nhìn lại một giờ trong quá khứ, cụm và tên vẫn được tính bằng cả bài đăng sau
   giờ đó. Không dùng để mô phỏng "lúc đó hệ thống biết gì".
6. **Dữ liệu tĩnh** đến 19/09/2026. Từ 17/09 thiếu VnExpress và VietnamNet, nên mấy ngày cuối có ít nguồn hơn.
7. **Điểm xu hướng chưa được đánh giá**, vì chưa có nhãn "Xem nhiều". Có thể dùng để xếp, nhưng đừng gọi là "được đọc nhiều nhất".
8. **Nhãn chấm gom cụm do Claude gán**, chưa có nhãn người. Báo cáo con số nào thì phải ghi rõ điều này.
9. **Tiền xử lý mô hình embedding là bắt buộc:** NFC + tách từ pyvi, văn bản = tiêu đề + ". " + sapo. Thiếu tách từ thì
   chất lượng giảm rõ (AP 0,69 → 0,56 ở bản zero-shot).
10. **Bản quyền:** đây là bài của các báo. Chỉ dùng cho học tập trong nhóm, luôn trích URL gốc, không đăng lại toàn văn.

## 7. Đánh giá RAG

Quy tắc của dự án: **không báo cáo con số nào thiếu baseline và khoảng tin cậy** (bootstrap).

- **Tập câu hỏi:** viết tay hoặc sinh từ các sự kiện ≥ 2 bài rồi người duyệt, kèm đáp án là `event_id` và `article_id`
  liên quan. Tránh cửa sổ 14–15/09 (mục 6.3), trừ khi đã hỏi.
- **Truy hồi:** Recall@k và MRR theo `event_id` (tìm đúng sự kiện chưa) và theo bài.
- **Câu trả lời:** tỉ lệ ý có trích dẫn đúng nguồn, tỉ lệ ý không có trong bài (bịa), người chấm so cặp mù.
- **Baseline nên có:** BM25 ở mức bài; vector ở mức bài không mở rộng; vector + mở rộng theo sự kiện (mục 5.1). So các
  biến thể này mới thấy gom cụm có giúp RAG hay không.

## 8. Những gì sẽ thay đổi

- **`event_id` hiện ổn định trong lần chạy `2026-11-03_v2`.** Khi gom cụm lại (mô hình hoặc ngưỡng mới, hay worker chạy
  liên tục sau này), một số sự kiện có thể tách, gộp hoặc đổi id. Hãy lưu cùng chỉ mục RAG giá trị
  `SELECT max(run_id), max(finished_at) FROM worker_runs WHERE status = 'ok'` và dựng lại chỉ mục khi giá trị này đổi.
- Giai đoạn sau, worker sẽ cào liên tục, gán bài mới vào sự kiện và gom lại mỗi 15 phút, ghi vào **cùng các bảng này**.
  Code đọc các bảng ở trên sẽ vẫn dùng được. Lịch sử bài đổi sự kiện nằm ở `event_assignment_log`.
- Có thể đổi mô hình embedding (`model_version` mới trong `article_embeddings`). Luôn lọc theo `model_version` và mã hoá
  câu hỏi bằng đúng mô hình đó.

## 9. Tài liệu liên quan

| | |
|---|---|
| Cài DB từ dump | R2 `db_NguyenDinhHieu/v1/README.md` |
| Schema đầy đủ, có chú thích | `infra/db/migrations/001_ingest.sql`, `002_events.sql` |
| Bố cục kho R2, hợp đồng Silver | `docs/tong-hop.md` mục 5.2, 5.3 |
| Gom cụm, đặt tên, xu hướng, cách đánh giá | `docs/tong-hop.md` mục 9, 10 |
| Mô hình embedding | R2 `models/embedding_v1_NguyenDinhHieu/README.md` |
| Nạp một lần chạy pipeline vào DB | `src/eventrank/serving/db_import.py` (`make db-import-run`) |
