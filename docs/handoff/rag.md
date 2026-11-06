# Môi trường RAG local

**Bắt đầu ở [kế hoạch RAG](../plan-rag.md)** để xem toàn bộ lộ trình và điểm tiếp nhận chat mới.
Mốc hiện tại 06/11/2026: NER/chunk/BM25, hai dịch vụ model, dense Qdrant và hybrid RRF đã có.
Kho đủ 96.230 point, collection đã publish. Đã có context + hỏi đáp có nguồn qua CLI/API;
phạm vi được chốt là snapshot hiện tại. Các mở rộng bước 6–8 và đánh giá chất lượng làm sau.

## Hỏi đáp CLI/API trên snapshot (06/11)

Luồng `pipeline.py`: hybrid → hydrate Postgres → chọn context → Gemma → kiểm JSON/citation/quote.
Mặc định tối đa 8 chunk, 2/bài, 3/nguồn; bỏ text trùng và chunk chồng offset, giữ nguyên chunk.
Đếm cả system/query/metadata/chat template bằng tokenizer đúng revision Gemma, dành tối đa
1024 token output trong cửa sổ 8192. Counter dùng OpenAI text blocks như renderer vLLM;
đã đối chiếu prompt/token IDs thật (dạng string thuần lệch 1 token ở system).

```powershell
# Chỉ tải tokenizer lần đầu, không tải trọng số model về máy.
.\.venv\Scripts\python.exe -X utf8 -m eventrank.rag.token_budget prepare
.\.venv\Scripts\python.exe -X utf8 -m eventrank.rag.pipeline ask 'U23 Việt Nam thắng U23 Philippines với tỷ số bao nhiêu?' --source thanhnien --date-from 2026-09-18 --date-to 2026-09-18 --trace data/rag/reports/qa-NEW.json
# API riêng không nạp Silver/R2 khi startup.
.\.venv\Scripts\python.exe -m uvicorn apps.api.rag:app --host 127.0.0.1 --port 8001
```

Make tương đương: `rag-tokenizer`, `rag-ask ARGS='"câu hỏi" ...'`, `rag-api`.
Swagger: http://127.0.0.1:8001/docs → `POST /api/rag/ask`; router cũng được gắn vào app chính.
Ví dụ body:

```json
{"question":"U23 Việt Nam thắng U23 Philippines với tỷ số bao nhiêu?","source":"thanhnien","date_from":"2026-09-18","date_to":"2026-09-18","max_tokens":512,"allow_fallback":false}
```

Response gồm `status`, `answer`, `sources`, `snapshot`, `retrieval_mode`, `degraded`, `trace`.
Snapshot truy vấn thật có 28.725 bài/6 nguồn, published_at từ 2008-05-08 đến 2026-09-19
(min/max dữ liệu DB, không phải cam kết bao phủ liên tục các ngày trong khoảng).
Source chứa URL/ngày/ID/offset lấy từ DB và quote được kiểm trong chunk, không nhận URL model tự bịa.
Gemma dùng constrained JSON schema; invalid ID/quote/schema hoặc output bị cắt sẽ trả
`invalid_generation` và không xuất nội dung model như câu trả lời hợp lệ. Quote so khớp NFC/whitespace;
đây là kiểm provenance, chưa chứng minh từng phát biểu được bằng chứng suy ra đúng về ngữ nghĩa.
Không đặt ngưỡng RRF tùy ý; thiếu bằng chứng để model từ chối, bộ lọc ngoài snapshot trả sớm không gọi GPU.
Câu hỏi ngày tương đối thiếu filter ngày và thống kê toàn kho được trả `unsupported_query`.
Lỗi hạ tầng trả HTTP 503, request không hợp lệ 400/422; API giới hạn 1 câu đang xử lý, quá tải trả 429.
Cold start Modal có thể mất nhiều phút; client kiểm thử nên dùng timeout 1200 giây.
Không bật fallback ngầm; cần `--allow-fallback`/`allow_fallback=true` khi muốn chấp nhận một nhánh retrieval.
API local phục vụ kiểm thử, chưa có auth/rate limit nhiều người dùng, streaming hay lịch sử hội thoại.

Kiểm thử cuối `tests/rag tests/common tests/api`: **198 passed, 1 skipped** (test SPA cần bản
web build, hiện chưa có); Ruff đạt. Test dùng fixture/mock, test DB dùng database tạm.
OpenAPI và TypeScript đã sinh lại từ `schemas.py`. `npm run typecheck` chưa đạt do các import
có sẵn tới ba file không tồn tại: `pages/data/{DataQualityPage,ModelsPage,ClusterMapPage}`.
Không có lỗi TypeScript từ hợp đồng RAG mới. Máy này không có `make`/Node trên PATH mặc định;
đã chạy recipe tương đương bằng Python và Node cài sẵn trong Eclipse.
Fingerprint status sau triển khai vẫn là
`00876904a5ec3a32f8e6ba91efbaec1ca3276547a5ff989f64ea938f279eecdb`,
96.230 BM25/Qdrant ready và exact point count 96.230. Report
`data/rag/reports/qa-index-integrity-20261106-01.json`.
HTTP `/docs` trả 200; hỏi ngoài snapshot trả `insufficient_evidence`, “hôm nay/mới nhất” thiếu
filter trả `unsupported_query`, đều không gọi GPU. Report `qa-api-early-20261106-01.json`.
Trong lúc API đang bận, request thứ hai thật nhận HTTP 429; report `qa-api-concurrency-20261106-01.json`.

Smoke toàn luồng thật thành công, không dùng fallback:

- CLI `qa-cli-20261106-02.json`: `answered`, mode `hybrid`, 3 chunk context, 2 nguồn citation;
  trả kết quả U.23 Việt Nam thắng U.23 Philippines 2–0, giữ quote nguyên văn và metadata DB.
- HTTP API `qa-api-20261106-02.json`: HTTP 200, cùng answer/sources, `degraded=false`.
- Cả hai đếm local/server khớp **2625 prompt token**, completion 280, finish_reason `stop`,
  validation `passed=true` (citation IDs, exact quotes, metadata URLs). Dành 512 token output.
- Lượt đầu chưa constrained schema trả JSON sai cấu trúc; guard trả `invalid_generation`,
  không xuất nội dung đó như câu trả lời hợp lệ. Đã thêm JSON-schema response format và kiểm lại thật;
  không nới validator để chấp nhận JSON lỗi. Report cũ `qa-smoke-20261106-01.json`.

Đây là smoke chức năng/toàn vẹn, chưa phải điểm chất lượng trên tập đánh giá. Thời gian CLI lần này
660,13 giây gồm chờ Modal cấp GPU/cold start hai model; không dùng làm benchmark inference.
Không chạy lại NER/chunk/BM25/document embedding, không deploy lại Modal trong bước hỏi đáp.
Sau smoke đã kiểm stats: cả Qwen và Gemma **0 container, 0 backlog, 0 running input**.
API local :8001 vẫn chạy để kiểm thử chung; request mới có thể cần cold start.

## Hybrid RRF (06/11)

`src/eventrank/rag/hybrid.py` ghép top 30 BM25 và top 30 dense theo
`sum(1/(60+rank))`, rank bắt đầu 1. Cấu hình ở `configs/rag.yaml` mục `retrieval`.
Không cộng BM25 score với cosine, không tune tham số theo vài câu smoke.
Dedup theo UUID chunk (một contribution/nhánh); khi RRF bằng nhau dùng UUID tăng dần.
Trace giữ toàn bộ union ứng viên, rank/score từng nhánh, RRF score, filter, corpus/model/index
versions và snapshot BM25/collection dense. Python API trả text đầy đủ; CLI mặc định snippet,
thêm `--full-text` nếu cần. Không dedup theo bài ở bước này; đó là việc chọn context bước 5.

```powershell
.\.venv\Scripts\python.exe -X utf8 -m eventrank.rag.hybrid search 'Nghị quyết 57-NQ/TW' --limit 5 --trace data/rag/reports/hybrid-NEW.json
.\.venv\Scripts\python.exe -X utf8 -m eventrank.rag.hybrid search 'khôi phục điện' --source nhandan --date-from 2026-09-01 --date-to 2026-09-19 --limit 5
# Chỉ cho phép giảm xuống một nhánh khi yêu cầu rõ:
.\.venv\Scripts\python.exe -X utf8 -m eventrank.rag.hybrid search 'Nghị quyết 57-NQ/TW' --allow-fallback
# Kiểm tra tích hợp (có gọi Qwen query, không embed lại tài liệu):
.\.venv\Scripts\python.exe -X utf8 -u -m eventrank.rag.verify_hybrid --report data/rag/reports/hybrid-checks-NEW.json
```

Make tương đương: `make rag-hybrid-search ARGS='"câu hỏi" --limit 5'`.
File `--trace`/`--report` phải có tên mới; không ghi đè. `--config` đặt trước `search`.
Các report/trace trong `data/` không đi theo Git.

Hai nhánh dùng chung query NFC, source viết thường và ngày ĐĂNG inclusive theo giờ VN.
Khi hydrate, mọi ứng viên được đối chiếu text/metadata với Postgres và trạng thái ready của
nhánh tương ứng, kiểm canonical slice. Cùng `index_version` nhưng khác fingerprint/count
corpus hoặc sai model/input view cũng dừng; không lấy dữ liệu cũ làm evidence.

**Lỗi và fallback:** mặc định một nhánh lỗi → exit code 1, `mode=failed`; trace lỗi vẫn ghi nếu yêu cầu.
Chỉ khi có `--allow-fallback` mới trả `bm25_only` hoặc `dense_only`, luôn `degraded=true`
và nêu nhánh lỗi (không log message network/DB có thể chứa secret). Một nhánh rỗng nhưng
khỏe không phải outage. Cả hai nhánh lỗi hoặc Postgres hydrate lỗi vẫn dừng. Sai binding/evidence
là lỗi toàn vẹn, không được né bằng fallback. Fallback BM25 không đòi Qdrant ready hoặc token Modal
khi Qdrant không truy cập được. Cold start vẫn chịu timeout của ModelClient, chưa phải SLA API.

**Kết quả chạy thật:**

- `data/rag/reports/hybrid-smoke-20261106-01.json`: CLI hybrid khỏe, BM25 30 + dense 30,
  union 48 UUID, đầy đủ evidence/rank/score/version.
- `data/rag/reports/hybrid-checks-20261106-01.json`: **passed=true**; 9 case query/filter,
  lặp query cho candidates/ranks/scores giống nhau, đối chiếu union và công thức RRF, evidence
  khớp DB. Hai fault injection chỉ thay client (không tắt dịch vụ thật): default strict lỗi,
  bật fallback trả đúng `bm25_only` và `dense_only`.
- CLI với config thử nghiệm trỏ Qdrant sang cổng đóng: strict exit=1 và fallback exit=0,
  report `hybrid-cli-{strict,fallback}-20261106-01.json`. Không đổi cấu hình Qdrant đang dùng.
- 96.230 point giữ nguyên; fingerprint toàn bộ trạng thái/error/updated_at DB trước/sau giống nhau
  (`00876904a5ec3a32f8e6ba91efbaec1ca3276547a5ff989f64ea938f279eecdb`). Verifier gọi một batch
  3 query embedding, không gọi document embedding/Gemma, không ghi DB/index.
- `tests/rag` + `tests/common`: **100 passed**, có DB test tạm; Ruff đạt. Test hybrid bao gồm
  RRF/dedup/tie, mismatch corpus/model, stale evidence, fallback, lỗi DB, trace không lộ error secrets,
  không ghi đè trace và ngày cuối có phần giây `23:59:59.5`.
- Kiểm Modal sau smoke: **0 container, 0 backlog, 0 running input**; min_containers đã về 0.

Đây là smoke/toàn vẹn, **chưa có đánh giá relevance hay kết luận hybrid tốt hơn dense/BM25**.
Ví dụ query tỷ số U23, RRF hiện đưa bài dự đoán lên top 1. Không sửa tham số để né ví dụ này;
việc chọn context/grounding phải phân biệt tin kết quả với dự đoán và cần đánh giá riêng.

## Kết quả full corpus (06/11)

Kiểm tra thật sau lượt resume: Postgres có 96.230 chunk, toàn bộ BM25/Qdrant `ready`;
Qdrant exact count=96.230, metadata `published=true`. Worker đã kiểm fingerprint corpus
và toàn bộ UUID/payload hash/version/vector trước publication; không còn pending/failed.
Report hoàn tất: `data/rag/reports/dense-4l4-resume-20261106-133924.json`.
Lượt cuối tái sử dụng 70.496 point cũ, embed thêm 25.734, `status_updated=25.734`,
tổng thời gian 1.418,883 giây (gồm scan/resume, chờ GPU và verification; không phải benchmark).
Kiểm stats Modal sau hoàn tất: 0 container, 0 backlog, 0 running input.

Dense search thật và resume đã kiểm thành công (mục dưới). Không chạy lại preparation hoặc
embed toàn corpus. Hybrid và hỏi đáp đã triển khai (mục trên); tiếp theo kiểm thử chung snapshot.

## Kiểm dense search và resume (06/11)

Lệnh kiểm tái lập, report phải có tên mới:

```powershell
.\.venv\Scripts\python.exe -X utf8 -u -m eventrank.rag.verify_dense --report data/rag/reports/dense-checks-NEW.json
# --step search hoặc --step resume để chạy riêng; resume không gọi Modal.
```

Report thật: `data/rag/reports/dense-checks-20261106-01.json`, **passed=true**.

- **9/9 trường hợp search đạt:** 3 câu hỏi tiếng Việt; lọc nguồn không phân biệt hoa/thường;
  khoảng ngày; nguồn kết hợp ngày; nguồn không có; ngày ngoài corpus; đúng một ngày đăng theo giờ VN.
  Mỗi trường hợp dương trả 5 chunk; hai trường hợp âm trả 0. Đối chiếu từng hit với Postgres:
  chunk/article ID, text, canonical slice/offset, title, URL, source, published_at; kiểm rank/score.
- Chỉ gọi **1 request query embedding cho 3 câu hỏi** rồi tái sử dụng vector query cho các bộ lọc;
  **0 request document embedding**. Không gọi Gemma, không deploy/cache lại Modal.
- **Resume full 96.230 point đạt:** `embedding_calls=0`, `embedded=0`, `status_updated=0`,
  count và binding/publication không đổi. Guard từ chối mọi lời gọi embedding nếu thiếu point.
  Fingerprint của toàn bộ `rag_index_status` (cả hai nhánh, error, updated_at) trước/sau giống nhau:
  `00876904a5ec3a32f8e6ba91efbaec1ca3276547a5ff989f64ea938f279eecdb`.
- Sau kiểm tra: Modal **0 container, 0 backlog, 0 running input**. Bộ `tests/rag` + `tests/common`:
  **77 passed**, gồm DB test với database tạm; Ruff đạt. 3 test mới kiểm guard và phát hiện status đổi.

Đây là smoke/toàn vẹn, chưa phải đánh giá chất lượng ranking, chưa có nhãn relevance/baseline/CI.
Ví dụ quan sát từ report: câu hỏi tỷ số U23 trả top 1 là bài kết quả 2-0 nhưng top 2 là bài dự đoán 3-0;
câu hỏi khôi phục điện trả nhiều chunk cùng một bài. Không lấy top-k làm context nguyên xi;
đánh dấu các tình huống này để kiểm bước chọn context/rerank sau, chưa tune theo vài câu smoke.

Các mục bên dưới giữ lịch sử triển khai/cạm bẫy.

## Dense Qdrant — lịch sử pilot và chạy với 4 L4

Đã thêm `src/eventrank/rag/dense.py`, cấu hình `dense` trong YAML và Make targets
`rag-dense`, `rag-dense-search`. Dùng nguyên `rag_chunks.text`, cosine 1024 chiều,
UUID chunk làm point ID; metadata collection ràng buộc corpus/model/chunking/input view.
Resume đối chiếu payload hash/version và vector, không gọi model cho point đã có;
chỉ mark ready sau upsert `wait=True`. Search mặc định chặn collection chưa công bố.

Pilot thật 32 chunk thành công; chạy lại `embedded=0`, `status_updated=0`.
Report: `data/rag/reports/dense-pilot-20261105-01.json` và
`dense-pilot-reuse-20261105-01.json`. Full từng gặp lỗi request tạm thời;
gọi lại cùng lô thành công, đã bổ sung retry giới hạn cho lỗi inference tạm thời.
HTTP 413 không retry/cắt text. Test toàn bộ RAG/common: 69 passed (có Postgres);
sau thêm test retry: riêng `test_dense.py` 9 passed. Ruff đạt.

**Trạng thái khi dừng:** 1.696 point trong `rag_v1_qwen_text_v1`,
1.696 `qdrant_status=ready`, 94.534 pending, toàn bộ 96.230 BM25 vẫn ready;
collection `published=false`. Hai tiến trình Python của lượt build đã dừng.
Ở thời điểm tạm dừng này chưa hoàn tất full corpus; trạng thái mới nhất nằm ở đầu tài liệu.
Ngày 06/11 người dùng đã chọn 4 L4 và cho chạy tiếp. Cấu hình mới: GPU `L4`
(không fallback T4), tối đa 4 container embedding, mỗi container 1 request tại một thời điểm;
min_containers=0, scaledown_window=60. Đã deploy cấu hình này, embedding_version vẫn
`emb-f258fee371bedcb31b0b`; không gọi lại cache hay Gemma smoke.

`dense.concurrency=4`: chỉ gửi inference song song, tối đa 4 request × 32 chunk;
Qdrant/Postgres vẫn do một luồng điều phối ghi dưới cùng advisory lock.
Lỗi một lô → lưu các lô khác đang chạy thành công rồi dừng, không gửi nhóm tiếp theo.
Resume kiểm point/hash/version trước khi gọi model. `--concurrency 1..4` ghi đè cấu hình CLI.
GPU/container/concurrency không nằm trong hash embedding, nên không cần embed lại 1.696 point cũ.

Kiểm thử 06/11 trước khi resume: **72 passed**, gồm DB test trên database tạm; Ruff đạt.
Test mới xác nhận 4 request đồng thời, một luồng ghi, lỗi một request vẫn lưu request khác,
và resume không gọi lại model cho point cũ. Không làm lại NER/chunking/BM25 khi tiếp nhận.

Lượt resume 4 L4 đã khởi động nền ngày 06/11:
`data/rag/reports/dense-4l4-20261106-101747.stdout.log` (tiến độ),
`.stderr.log` (lỗi), `.json` (chỉ tạo khi hoàn tất toàn bộ và kiểm đủ point).
Tên gốc chung là `dense-4l4-20261106-101747`. Không khởi động thêm worker khi lượt này còn chạy;
advisory lock sẽ chặn. Cần xem log/trạng thái thật trước khi báo full corpus đã hoàn tất.

**Phân biệt cấu hình và cấp phát thực tế:** đã đặt GPU=L4, max_containers=4,
4 request đồng thời và buffer_containers=3 (cập nhật autoscaler runtime; cũng ghi trong YAML/code).
Tại lần kiểm tra ban đầu Modal vẫn chỉ báo 1 runner dù có lúc backlog=3;
environment không đặt GPU limit riêng và spend_limit_reached=false. Chưa xác định nguyên nhân.
Thử yêu cầu min_containers=4 ngắn hạn vẫn chỉ ghi nhận 1 runner, đã trả min_containers=0.
Không báo "4 GPU đang chạy" chỉ dựa vào max_containers=4. Cần kiểm tra stats thật nếu tiếp nhận.

Kiến trúc đã chọn: Postgres, Qdrant, BM25 và backend điều phối chạy local/server dự án;
Modal hiện chạy embedding và generator. Reranker/query NER là phần mở rộng chưa triển khai.

## Cài đặt

`uv sync --locked` cài nhóm mặc định `dev`, `ml`, `rag`. Nhóm `rag` gồm
`qdrant-client`, `tantivy` (BM25 inverted index), `modal` (SDK và CLI),
`transformers==5.22.1`, `sentencepiece`, `jinja2` để đếm chat token đúng revision.
Nếu máy đã cài nhóm embedding, dùng `uv sync --locked --group embed` để giữ nhóm đó.
Không cần PyTorch hay trọng số model local; Transformers chỉ dùng tokenizer/template.

```powershell
docker compose -f infra/docker-compose.rag.yml up -d
.\.venv\Scripts\modal.exe --version
```

Qdrant: REST `http://127.0.0.1:6333`, dashboard Docker `http://127.0.0.1:6333/dashboard`,
gRPC `127.0.0.1:6334`. Image ghim `v1.20.0`; dữ liệu lưu trong Docker named volume
`eventrank-rag-search_qdrant_data`. `make qdrant-up`, `make qdrant-stop`,
`make qdrant-status` là lệnh tương đương. Dừng container vẫn giữ dữ liệu.

### Windows khi Docker Hub không truy cập được

Tải `qdrant-x86_64-pc-windows-msvc.zip` từ
[release chính thức v1.20.0](https://github.com/qdrant/qdrant/releases/tag/v1.20.0),
giải nén `qdrant.exe` vào `data/tools/qdrant-v1.20.0/`, rồi chạy:

```powershell
powershell -ExecutionPolicy Bypass -File infra/start-qdrant.ps1
```

Script chạy nền, chỉ bind localhost. Storage, snapshot và log ở `data/rag/qdrant/`.
Script in PID; dừng bằng `Stop-Process -Id <PID vừa in>`. Không chạy Docker Qdrant đồng thời.
Storage native và Docker volume là hai kho riêng; chuyển giữa hai cách bằng snapshot Qdrant,
không chép trực tiếp file storage. Máy đang làm việc dùng cách native này vì Docker Hub timeout.

**Dashboard native (sửa 06/11):** binary Windows không đi kèm thư mục `static`, nên
`6333/dashboard` trả 404 dù `/readyz` và `/collections` vẫn 200. Đã tải Web UI chính thức
[v0.2.20](https://github.com/qdrant/qdrant-web-ui/releases/tag/v0.2.20), asset `dist-qdrant.zip`,
kiểm SHA256 `331d6f83ee3c0e771a02b80ec58df3857e7ebab99b7cbdd1a15be205a9215d3d`,
giải nén vào `data/tools/qdrant-web-ui-v0.2.20/` (không đi theo Git).
`infra/serve_qdrant_dashboard.py` phục vụ assets ở **http://127.0.0.1:6335/dashboard/**
và proxy API cùng origin về native 6333. Đây là UI/proxy, không tạo thêm kho Qdrant và
không đổi endpoint indexer. Không khởi động Docker Qdrant trên cổng 6333 đang được native giữ.

```powershell
.\.venv\Scripts\python.exe -X utf8 -m infra.serve_qdrant_dashboard
# Terminal khác:
Start-Process 'http://127.0.0.1:6335/dashboard/'
```

Máy hiện tại đã chạy proxy nền; log ở `data/rag/qdrant/dashboard.{stdout,stderr}.log`.
Kiểm thật: HTML, JS/CSS assets và `/collections` qua proxy đều 200; count đọc đúng collection
native đang được index. Không cần restart Qdrant hay worker để mở UI.

Lỗi JSON của trình duyệt đã sửa 06/11: browser gửi `Accept-Encoding: ... br, zstd`,
Qdrant trả Brotli nhưng httpx local chưa có decoder Brotli; proxy cũ bỏ header nén trong khi
body vẫn nén. Proxy hiện yêu cầu `Accept-Encoding: identity` ở upstream local.
Test hồi quy bằng fixture Brotli + HTTP mock đã tái hiện lỗi trước sửa và đạt sau sửa.
Kiểm thật sau restart riêng proxy: version, collections, collection info và scroll đều trả
JSON hợp lệ với header của Chrome. Không dừng Qdrant hoặc worker embedding.

Lượt `dense-4l4-20261106-101747` sau đó được phát hiện đã tự dừng vì Modal HTTP 408,
không liên quan việc restart proxy: 70.496 point/ready, 32 failed, 25.702 pending;
BM25 vẫn 96.230 ready. Đã bổ sung 408 vào retry transient (413 vẫn không retry/cắt input),
test dense + dashboard đạt **13 passed**, Ruff đạt. Đã resume bằng concurrency=4;
log/report mới có prefix `data/rag/reports/dense-4l4-resume-20261106-`.

Tantivy là thư viện chạy trong tiến trình Python, không phải dịch vụ riêng.
Index BM25 thật nằm dưới `data/rag/bm25/`, đã dựng cho 96.230 chunk.

Postgres dùng `DATABASE_URL` trong môi trường local. Máy đang làm việc đã khôi phục dump R2
bằng cấu hình riêng `data/db_dump/postgres.compose.yml`, project `eventrank-rag`,
cổng `127.0.0.1:5433`. Không chạy thêm `make db-up` trên cùng cổng.
Không dùng volume Postgres 18 này với image Postgres 16 của compose chung.

## Modal

Đã xác thực bằng `MODAL_TOKEN_ID`/`MODAL_TOKEN_SECRET` trong môi trường local, deploy và smoke
hai dịch vụ thành công; cấu hình/lệnh ở mục “Model services trên Modal” bên dưới.
Không cần đăng nhập lại hoặc sửa profile CLI cũ chỉ vì bắt đầu chat mới. Máy khác tự cấu hình token
hoặc chỉ nạp `.env.client` nếu gọi inference. Không in secret; không tự chạy job GPU chỉ để kiểm cài đặt.

## Kiểm tra môi trường (04/11/2026)

- Python 3.12.12; qdrant-client 1.20.0; tantivy 0.27.0; modal 1.6.3.
- `uv sync --locked --offline`: thành công sau khi cài dependency.
- Qdrant native 1.20.0: `/readyz` trả thành công; ghi 2 vector mẫu, lọc payload và tìm cosine đúng;
  collection mẫu đã dọn, còn 0 collection. Chưa có vector retrieval thật.
- Tantivy: truy vấn `điện` tìm đúng tài liệu mẫu tiếng Việt; mở lại index trên disk vẫn truy vấn được.
  Đây là kiểm tra cài đặt, chưa đánh giá lexical analyzer hay chất lượng retrieval.
- Postgres: kết nối Python thành công, bảng `articles` vẫn có 28.725 dòng.
- Migration 001–007: tất cả `applied`, chạy lại không có migration mới. Test migration/RAG riêng:
  **19 passed**; toàn bộ nhóm test Postgres sau đồng bộ: **48 passed, 297 deselected**.
- Đồng bộ 003–006 làm lộ lỗi `TRUNCATE` bị FK bookmark rỗng chặn trong `serving/db_import.py`.
  Đã đổi sang DELETE con → cha trong transaction; có bookmark tham chiếu thì FK chặn và rollback,
  không xoá lan dữ liệu người dùng (có test bằng bảng bookmark thật).
- Pytest: **293 passed, 41 skipped, 2 failed**. Hai lỗi ở `tests/lake/test_reader.py`:
  đường dẫn Windows trả `\\` thay `/`, làm sai tên file và tách thư mục nguồn.
  Chưa sửa phần đọc kho trong thay đổi cài môi trường RAG này.

## Trạng thái và việc tiếp theo

- Migration 003–006 đã đồng bộ từ R2 `db_NguyenDinhHieu/v1/schema/` (Git dev tại thời điểm đồng bộ chỉ có 001–002).
- Migration `007_rag.sql` tạo `article_ner`, `rag_chunks`, `rag_index_status` theo thiết kế gọn,
  chỉ giữ phiên bản hiện hành. Hợp đồng chi tiết: `docs/tong-hop.md` mục 5.2–5.3.
- NER local và Silver đã đối chiếu; 28.725 bài trong DB đều có NER tương ứng.
- Đã nhập 28.725 dòng NER (939.203 entity), tạo 96.230 chunk và 96.230 trạng thái pending.
  Kiểm toàn kho không có lỗi hash, slice, boundary entity, độ phủ hay thiếu status.
  Độ dài chunk theo whitespace units: min 41, trung vị 295, p95 318, max 321 (4 chunk 321).
- 21 bài NER ngoài DB thiếu ngày đăng; giữ nguyên dữ liệu nguồn.
- Importer NER, chunking, BM25 và dense snapshot đã có trong `src/eventrank/rag/`;
  96.230 dòng `bm25_status=ready`, `qdrant_status=ready`; collection đã publish và kiểm search/resume.
- Hybrid RRF, chọn context và pipeline hỏi đáp CLI/API đã có; chưa có worker cập nhật tăng dần.
- Embedding Qwen và generator Gemma đã deploy Modal, đã kiểm API thật và idle về 0 container.
- Bước tiếp: kiểm thử chung hỏi đáp snapshot; NER/cluster expansion, reranker, worker delta
  và đánh giá chất lượng là các phạm vi sau theo [plan](../plan-rag.md).
- Không dùng vector `bkai_ft_v1_s44` cho retrieval khi chưa đánh giá query–passage.

Thay đổi schema Postgres phải thêm migration mới và cập nhật `docs/tong-hop.md` trong cùng PR.

## Bước 1–2: nhập NER và chia chunk

Đầu vào là snapshot Silver nguyên gốc và NER của cùng corpus. Không dựng canonical text từ
`articles.content_text` vì ingest đã chuẩn hoá khoảng trắng. Importer kiểm content hash theo hợp đồng
ingest để từ chối Silver cũ so với DB, rồi dựng canonical text bằng đúng template NER và kiểm mọi slice.
Chỉ giữ 4 trường entity cần dùng; trường kỹ thuật như `rule`, `orig_text` vẫn còn trong file nguồn.

```powershell
# Đổi đường dẫn cho đúng snapshot trên máy mình; glob phải đặt trong dấu nháy.
.\.venv\Scripts\python.exe -X utf8 -m eventrank.rag.prepare --steps ner --dry-run --silver-glob 'data/lake/silver/*/*.jsonl' --ner data/lake/gold/gold_data.jsonl --ner-version bamibert-s43-clean-20260929
.\.venv\Scripts\python.exe -X utf8 -m eventrank.rag.prepare --steps all --silver-glob 'data/lake/silver/*/*.jsonl' --ner data/lake/gold/gold_data.jsonl --ner-version bamibert-s43-clean-20260929 --report data/rag/reports/prepare-001.json
```

Máy hiện tại dùng Silver/NER ở thư mục anh em `../NER_Detect/data/` qua tham số CLI;
không hardcode đường dẫn máy vào code/config. `make rag-prepare ARGS="…"` tương đương;
`make rag-chunks` chỉ chạy bước 2. Make dùng `uv run --no-sync` để không gỡ nhóm embed đang cài.
`--dry-run` dùng riêng với `--steps ner` hoặc `chunks`. File report phải có tên mới, không ghi đè.

Chunking cấu hình trong `configs/rag.yaml`: mục tiêu 320 đơn vị whitespace, overlap 48;
ưu tiên ranh giới đoạn/câu trong 40% cuối cửa sổ, không cắt ngang entity. Đây không phải token của model
và chưa tune trên tập đo. Entity dài hơn giới hạn được giữ nguyên và đếm `oversized_chunks`.
Chunk ID dùng UUIDv5 của article ID, hash canonical text, phiên bản chunking (băm cả tham số) và offset.

Chạy lại không thay timestamp hay reset trạng thái ready nếu dữ liệu/cấu hình không đổi. Đổi NER/chunking
chỉ được dựng lại dữ liệu dẫn xuất chưa index (mọi nhánh vẫn pending). Đã ready/failed thì dừng để worker
đồng bộ point cũ trước, không âm thầm bỏ ID cũ khỏi DB. Worker đó chưa nằm trong bước 1–2.
Đổi index_version khi mọi nhánh pending được phép; sau khi đã index cần quy trình đồng bộ riêng.

Importer hiện yêu cầu NER đủ cho mọi bài trong DB (full snapshot); không nhận gói delta thiếu NER cũ.
Nguồn có ID trùng, JSON hỏng, thiếu Silver, stale content hash hoặc entity sai → preflight dừng trước khi ghi NER.
Commit theo lô 200 bài; lỗi DB giữa chừng có thể để lại các lô đã commit, chạy lại để tiếp tục.
Các lệnh preparation dùng advisory lock để không chạy chồng nhau. Worker tương lai phải tuân thủ cùng lock
và chỉ đặt ready sau khi đã ghi bền chỉ mục; schema chỉ có pending/ready/failed, chưa có lease nhiều worker.

Test viết trước: stub ban đầu thất bại 11 test text/chunking và test import đầu tiên;
sau triển khai bộ RAG đạt 18 passed. Fixture ở `tests/fixtures/rag/`, không gọi mạng/model.
Kiểm tra cuối `tests/rag` + `tests/common`: **37 passed**. Chạy lại toàn kho:
0 NER inserted/updated (28.725 unchanged), 0 chunk inserted (96.230 unchanged),
0 trạng thái mới/reset; report `data/rag/reports/prepare-rerun-20261104.json`.
Report chạy thật: `data/rag/reports/prepare-20261104.json`; kiểm toàn kho:
`data/rag/reports/verify-20261104.json`. Không dùng các số đếm kiểm toàn vẹn này làm số đo chất lượng retrieval.

## BM25 baseline (05/11/2026)

```powershell
.\.venv\Scripts\python.exe -X utf8 -m eventrank.rag.bm25 build --report data/rag/reports/bm25-build-001.json
.\.venv\Scripts\python.exe -X utf8 -m eventrank.rag.bm25 search 'Nghị quyết 57-NQ/TW' --limit 5
.\.venv\Scripts\python.exe -X utf8 -m eventrank.rag.bm25 search 'khôi phục điện' --source vnexpress --date-from 2026-08-01 --date-to 2026-09-19
```

`make rag-bm25` và `make rag-search ARGS='"câu hỏi" --limit 5'` tương đương. Build cần Postgres;
search chỉ đọc disk, không cần DB/Modal/Qdrant. Thêm `--full-text` để CLI trả toàn chunk; mặc định CLI chỉ
trả snippet 320 ký tự đầu, không phải highlight khớp query. Python `BM25Index.search()` luôn trả text đầy đủ,
chunk/article ID, offset, title, URL, source, ngày đăng và score/rank cho bước hybrid.

Analyzer `vi_syllable_codes_v1`: NFC + casefold, giữ dấu, tách âm tiết/chữ/số bằng regex Unicode;
giữ cả mã có dấu nối/chấm/gạch chéo và thành phần (`57-NQ/TW`, `TP.HCM`). Không dùng subword BamiBERT,
stemming, bỏ dấu hay stopword; bỏ term dài hơn 256 ký tự. Chỉ bỏ tiền tố template NER ở đầu dòng trên bản
indexing, text gốc/offset không đổi. Corpus và query dùng đúng cùng hàm `analyze` rồi whitespace tokenizer.
Query là OR các term duy nhất, chấm BM25 mặc định Tantivy; không diễn giải cú pháp người dùng.
Đây là baseline chưa tune/đánh giá retrieval, không khẳng định tốt hơn VnCoreNLP.

Lọc nguồn khớp chính xác, không phân biệt hoa/thường. Ngày lọc là ngày ĐĂNG theo giờ Việt Nam,
bao gồm cả ngày đầu và cuối; không phải thời gian sự kiện. Query tối đa 2048 ký tự/128 term, limit 1–100.
Chưa dedup theo bài hoặc thêm entity boost/cluster expansion; đó là phần chọn ứng viên/context phía sau.

Mỗi build tạo snapshot riêng và manifest chứa analyzer/engine/index_version, corpus SHA256, số document.
Tantivy commit và hoàn thành merge, đối chiếu lại fingerprint DB rồi mới publish `CURRENT.json` bằng
atomic replace. Đây là metadata local của index, không commit hay dùng làm registry đồng bộ nhóm.
Sau publish mới mark BM25 ready; không sửa qdrant_status và không xoá lỗi của nhánh Qdrant.
Nếu UPDATE DB lỗi sau publish, chạy lại sẽ dùng artifact bền để sửa status. Build lỗi/corpus đổi không
publish, không báo ready; index cũ được giữ nguyên. Thư mục build chưa publish có thể còn để kiểm tra lỗi.
Các reader đã mở giữ snapshot cũ tới khi tạo lại `BM25Index` (chưa có cơ chế reload nền).

Build hiện là full snapshot; cùng fingerprint/config/engine thì reuse, 0 cập nhật status nếu đã ready.
Chưa có worker cập nhật/delete theo delta, chưa tự phát hiện bài mới cần chạy NER/chunking. Sau thay đổi corpus
phải chạy preparation phù hợp rồi build BM25; preparation chặn thay chunk đã index cho tới khi có quy trình
đồng bộ index cũ. Đừng sửa trạng thái ready thủ công để né guard.

Kiểm thật: 96.230 document (151.287.651 byte), bộ chunk ID khớp toàn bộ Postgres và fingerprint preparation;
96.230 trạng thái BM25 ready/Qdrant pending. Build lại reuse cùng snapshot, status_updated=0.
Report: `data/rag/reports/bm25-{build,reuse,verify}-20261105.json`.
Test BM25 gồm analyzer NFD/mã, bộ lọc ngày/nguồn, reopen disk, không ghi đè, rollback publication khi lỗi,
corpus đổi và reuse không đổi trạng thái. Fixture tiếng Việt đã sửa về UTF-8 sau khi test mới phát hiện
fixture cũ bị mất dấu do PowerShell pipe; không sửa assertion để né lỗi. Dữ liệu thật không dùng fixture đó.
Kiểm tra cuối: **49 passed** (`tests/rag` + `tests/common`), Ruff đạt.

Tài liệu: [Qdrant local](https://qdrant.tech/documentation/quickstart/),
[Tantivy Python](https://github.com/quickwit-oss/tantivy-py),
[Modal setup](https://modal.com/docs/guide/getting-started).

## Model services trên Modal

Model/chốt revision, GPU, giới hạn token đặt ở `configs/rag.yaml` mục `models`:
Qwen/Qwen3-Embedding-0.6B (1024 chiều, chuẩn hoá L2, tối đa 2048 token/input)
và google/gemma-4-12B-it-qat-w4a16-ct (vLLM, context 8192, client giới hạn output 1024).
Query embedding thêm instruction tiếng Anh; document không thêm instruction. Input vượt giới hạn
bị từ chối, không cắt âm thầm. `embedding_version` băm model/revision/dimension/instruction/max_length;
client kiểm tra version và vector trước khi nhận. Đổi embedding phải dựng lại collection dense tương ứng.

```powershell
# Chỉ chủ workspace cần hai biến MODAL_TOKEN_ID/MODAL_TOKEN_SECRET trong .env.
.\.venv\Scripts\python.exe -m eventrank.rag.modal_setup deploy
# CPU tải hai model vào Modal Volume; không chạy GPU cho việc tải trọng số.
.\.venv\Scripts\python.exe -m eventrank.rag.modal_setup cache
# Gọi thử cả hai API thật, có phát sinh GPU trong thời gian xử lý.
.\.venv\Scripts\python.exe -X utf8 -m eventrank.rag.modal_setup smoke
```

Make tương ứng: `rag-modal-deploy`, `rag-modal-cache`, `rag-model-smoke`.
Mỗi model có endpoint riêng, proxy auth bắt buộc. Từ 06/11 Qwen dùng tối đa 4 container L4,
mỗi container nhận 1 request; Gemma vẫn tối đa 1 container, ưu tiên L4 và dự phòng A10,
min_containers=0 và scaledown_window=60 giây. Lần gọi đầu sau khi nghỉ cần chờ cold start;
Volume chỉ cache trọng số, không chứa Postgres, Qdrant, BM25 hay toàn bộ corpus.
Khoảng chờ scale-down vẫn có thể tính phí tài nguyên, Volume có phí lưu trữ riêng.
Client xử lý redirect 303 khi cold start lâu, chỉ theo URL cùng origin để không gửi token sang host khác.
Gemma dùng CUDA development image có nvcc cho FlashInfer, `--enforce-eager` để giảm công việc compile
khi cold start. Đổi lựa chọn này cần đo lại độ trễ/throughput trên bộ workload cố định.
Cache tải bằng HTTP (`HF_HUB_DISABLE_XET=1`) sau khi Xet bị kẹt trên lần thử thực tế;
file tải dở được tải lại bằng thư viện trước khi dùng, không nối tiếp dữ liệu Xet theo HTTP.

Deploy ghi URL + proxy token vào `.env` và xuất `.env.client` (đều gitignore).
Chỉ gửi `.env.client` cho thành viên cần gọi inference. File này không chứa token quản trị,
khóa R2 hay DATABASE_URL. Proxy token được cấp quyền gọi các endpoint có proxy auth trong
workspace khi không bật RBAC; workspace bật RBAC thì được cấp theo environment đang chọn
(mặc định `main`). Token không giới hạn riêng app này. Thu hồi token trong Modal
khi ngừng chia sẻ; không đưa file vào frontend/browser. Có thể tự tạo proxy token riêng từng người
trên Modal rồi thay hai biến trong file client của họ.

Backend của thành viên nạp file client trước khi tạo HTTP client:

```python
from dotenv import load_dotenv
from eventrank.rag.models import ModelClient

load_dotenv('.env.client')
client = ModelClient.from_env()
try:
    vectors = client.embed(['Nội dung một chunk'], input_type='document')
    query_vector = client.embed(['Câu hỏi của người dùng'], input_type='query')
    answer = client.chat([{'role': 'user', 'content': 'Trả lời dựa trên context ...'}])
finally:
    client.close()
```

`client.chat` chỉ gọi model, chưa tự retrieve hay tạo citation. Dense indexing, hybrid retrieval,
context selection, grounding và endpoint hỏi đáp local đã được nối trong `pipeline.py`. Không nhầm smoke test
với đánh giá chất lượng RAG. Đổi model/GPU có thể qua `RAG_EMBEDDING_*`/`RAG_LLM_*` trong `.env`;
đổi model ID phải kèm revision SHA đầy đủ rồi deploy/cache lại. Chưa hỗ trợ thay dimension hoặc
instruction bằng env: sửa YAML để version/index được thay đổi có chủ đích.

Nguồn: [Qwen model card](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B),
[Gemma QAT](https://huggingface.co/google/gemma-4-12B-it-qat-w4a16-ct),
[vLLM Gemma 4 recipe](https://github.com/vllm-project/recipes/blob/main/Google/Gemma4.md),
[Modal proxy auth](https://modal.com/docs/guide/webhook-proxy-auth).

Kiểm tra thực tế 05/11/2026: app `eventrank-rag-models` trong workspace `doquocchung1234`
đã deploy; cache hai model hoàn tất, không còn file `.incomplete`. Request không token trả 401 ở cả
hai endpoint. Query/document embedding đều trả 1 vector 1024 chiều; version
`emb-f258fee371bedcb31b0b`. Gemma trả `Thủ đô Việt Nam là Hà Nội [1].`, finish_reason=stop,
57 prompt token + 12 completion token. Report: `data/rag/reports/modal-smoke-20261105-2245.json`.
Sau khi để idle, kiểm tra API stats xác nhận cả hai dịch vụ có backlog=0 và num_total_runners=0;
không để container GPU chạy thường trực.
Lần smoke cold start quan sát được: embedding 18,74 giây cho hai request, LLM 231,11 giây gồm startup
và biên dịch kernel. Đây là một lần kiểm kết nối, không phải benchmark hay đánh giá chất lượng RAG.
Container mới có thể cần vài phút; hiện mới cache trọng số, chưa lưu cache kernel JIT qua các lần tắt.
Kết nối control plane từ máy này đôi lúc timeout; chạy lại lệnh deploy/cache không cần tạo lại token.
Nếu startup vLLM lỗi, hàm phát hiện process thoát và dừng sớm thay vì giữ GPU chờ hết timeout mở cổng.

Kiểm thử cuối: `pytest tests/rag tests/common -q -p no:cacheprovider` → **35 passed, 24 skipped**;
24 test Postgres thiếu TEST_DATABASE_URL nên chưa chạy lại trong đợt model services. Ruff đạt.
Test mới dùng HTTP mock, bao gồm version/dimension/vector norm, tách admin/client env, token có/không RBAC,
redirect cold-start cùng origin và từ chối chuyển proxy token sang host khác.
