# Hướng dẫn cài đặt và chạy dự án

> Làm lần lượt từ trên xuống. Mỗi bước có lệnh để **kiểm tra đã làm đúng chưa** trước khi sang bước sau.
> Mọi lệnh chạy trong terminal Linux / WSL, **tại thư mục gốc của repo** (trừ khi ghi khác).

## Bắt đầu nhanh

### Lần đầu trên một máy

Cần có sẵn 3 điều kiện — nếu chưa có, làm mục tương ứng trước:

| Điều kiện | Kiểm tra bằng | Chưa có thì xem |
|---|---|---|
| Đã cài `git`, `make`, `uv`, `node` ≥ 20 | `make --version && uv --version && node --version` | [Mục 1](#1-cài-công-cụ-một-lần-trên-mỗi-máy) |
| Đã clone repo về máy | `ls Ranking-Event-Detection` | [Mục 2](#2-đăng-nhập-github-đúng-tài-khoản), [Mục 3](#3-lấy-code) |
| Có khoá R2 (xin trưởng nhóm, nên là khoá chỉ đọc) | — | [Mục 5](#5-cấu-hình-khoá-r2) |

Sau đó chỉ 4 lệnh:

```bash
cd Ranking-Event-Detection     # đúng chữ HOA/thường — Linux phân biệt: ranking-event-detection là thư mục KHÁC
make install                   # cài thư viện Python + JavaScript
cp .env.example .env           # rồi mở .env, điền khoá R2
make dev                       # bật backend + frontend
```

Mở **http://127.0.0.1:5173**. Dừng bằng `Ctrl+C`.

### Những lần sau

```bash
cd Ranking-Event-Detection
git pull
make dev
```

**Chỉ cần chạy lại `make install` khi có người thêm hoặc đổi thư viện.** Kiểm tra ngay sau `git pull`:

```bash
git diff --name-only HEAD@{1} HEAD | grep -E 'uv.lock|package-lock.json' && echo "→ cần chạy: make install"
```

Không in gì nghĩa là thư viện không đổi, bỏ qua `make install`.

### Chưa có khoá R2?

Vẫn chạy được bằng 5 bài dữ liệu mẫu có sẵn trong repo — đủ để làm giao diện:

```bash
LAKE_BACKEND=local LAKE_LOCAL_ROOT=tests/fixtures make dev
```

---

## Mục lục

1. [Cài công cụ](#1-cài-công-cụ-một-lần-trên-mỗi-máy)
2. [Đăng nhập GitHub đúng tài khoản](#2-đăng-nhập-github-đúng-tài-khoản)
3. [Lấy code](#3-lấy-code)
4. [Cài thư viện](#4-cài-thư-viện)
5. [Cấu hình khoá R2](#5-cấu-hình-khoá-r2)
6. [Chạy test](#6-chạy-test)
7. [Chạy web và trang kiểm soát](#7-chạy-web-và-trang-kiểm-soát)
8. [Gọi API bằng terminal](#8-gọi-api-bằng-terminal)
9. [Kiểm tra kết nối R2](#9-kiểm-tra-kết-nối-r2)
10. [Quy trình làm việc với git](#10-quy-trình-làm-việc-với-git)
11. [Xử lý sự cố](#11-xử-lý-sự-cố)
12. [Bảng tra nhanh](#12-bảng-tra-nhanh)
13. [Triển khai cho cả nhóm truy cập](trien-khai.md)
14. [Kế hoạch tiền xử lý dữ liệu](tien-xu-ly.md)

---

## 1. Cài công cụ (một lần trên mỗi máy)

Cần 5 công cụ: **git** (quản lý code), **gh** (đăng nhập GitHub), **make** (gộp lệnh), **uv** (Python và thư viện Python), **Node.js ≥ 20** kèm **npm** (thư viện JavaScript cho web React).

```bash
# git, gh, make
sudo apt update
sudo apt install -y git gh make

# Node.js (bản LTS) — cần cho web React trong apps/web
curl -fsSL https://deb.nodesource.com/setup_lts.x | sudo -E bash -
sudo apt install -y nodejs

# uv — tự cài Python đúng phiên bản cho dự án, không cần cài Python riêng
curl -LsSf https://astral.sh/uv/install.sh | sh
source "$HOME/.local/bin/env"        # hoặc mở terminal mới
```

Kiểm tra:

```bash
git --version
gh --version
make --version
uv --version
node --version          # phải ≥ v20
npm --version
```

Mọi lệnh đều phải in ra số phiên bản. Nếu `gh` không cài được bằng `apt`, xem https://github.com/cli/cli#installation.

---

## 2. Đăng nhập GitHub đúng tài khoản

Repo đang để **private**. Tài khoản đang dùng phải được chủ repo (Trần Đức Duy) thêm làm collaborator và **đã chấp nhận lời mời**.

```bash
gh auth login
```

Chọn lần lượt: `GitHub.com` → `HTTPS` → `Yes` → `Login with a web browser`. Mở https://github.com/login/device, đăng nhập **đúng tài khoản**, dán mã 8 ký tự.

Nếu máy có **nhiều tài khoản GitHub**, chuyển sang tài khoản có quyền vào repo:

```bash
gh auth status                              # xem các tài khoản, tài khoản nào đang dùng
gh auth switch --user <tên-tài-khoản>       # chuyển tài khoản
```

Kiểm tra tài khoản hiện tại **thật sự** vào được repo:

```bash
gh repo view ducduy-tran2703/Ranking-Event-Detection --json name,visibility
```

Phải in ra `"visibility":"PRIVATE"`. Nếu báo `Could not resolve to a Repository` → tài khoản chưa có quyền, xem [mục 11](#11-xử-lý-sự-cố).

---

## 3. Lấy code

**Máy chưa có code:**

```bash
git clone https://github.com/ducduy-tran2703/Ranking-Event-Detection.git
cd Ranking-Event-Detection
```

**Máy đã có code, cần cập nhật:**

```bash
git switch main
git pull
```

⚠️ Đọc kỹ kết quả của `git pull`. Nếu báo `Repository not found` nghĩa là **chưa cập nhật được** — đừng làm tiếp trên bản cũ, quay lại [mục 2](#2-đăng-nhập-github-đúng-tài-khoản).

Kiểm tra đã có bản mới nhất:

```bash
git log --oneline -3                        # commit gần nhất
ls AGENTS.md CLAUDE.md docs/                # các file này phải tồn tại
```

---

## 4. Cài thư viện

```bash
make install
```

Lệnh này làm hai việc:

| Việc | Lệnh thật bên trong | Đọc từ | Cài vào |
|---|---|---|---|
| Thư viện Python | `uv sync` | `pyproject.toml` + `uv.lock` | `.venv/` — tự tải Python 3.12 nếu máy chưa có |
| Thư viện JavaScript | `npm ci` (trong `apps/web/`) | `package.json` + `package-lock.json` | `apps/web/node_modules/` |

Cả hai đều cài **đúng phiên bản đã khoá**, nên máy ai chạy cũng ra cùng một bộ thư viện. Dùng `npm ci` chứ không dùng `npm install`: `npm ci` cài đúng theo file khoá, không tự nâng phiên bản.

Kiểm tra:

```bash
uv run python --version                     # phải là Python 3.12.x
```

Hai thư mục `.venv/` và `node_modules/` **không có trong git** (nặng hàng trăm MB, phụ thuộc hệ điều hành). Mỗi người tự tạo bằng `make install`.

---

## 5. Cấu hình khoá R2

Khoá R2 **không có trong git**. Xin trưởng nhóm **một khoá chỉ đọc** (Object Read only) — trang kiểm soát chỉ cần đọc.

```bash
cp .env.example .env
nano .env                                   # hoặc mở bằng VS Code: code .env
```

Điền 3 dòng còn trống:

```bash
R2_ACCOUNT_ID=...
R2_ACCESS_KEY_ID=...
R2_SECRET_ACCESS_KEY=...
```

Kiểm tra **đã điền đủ** mà **không in khoá ra màn hình**:

```bash
( set -a; source .env; set +a
  for v in R2_ACCOUNT_ID R2_ACCESS_KEY_ID R2_SECRET_ACCESS_KEY R2_BUCKET; do
    val="${!v}"; [ -n "$val" ] && echo "$v: có (${#val} ký tự)" || echo "$v: TRỐNG"
  done )
```

Độ dài đúng: `R2_ACCOUNT_ID` và `R2_ACCESS_KEY_ID` là **32** ký tự, `R2_SECRET_ACCESS_KEY` là **64** ký tự.

Kiểm tra `.env` **không thể bị commit**:

```bash
git check-ignore -v .env                    # phải in ra một dòng trong .gitignore
```

⚠️ **Không bao giờ** dán khoá vào nhóm chat, notebook, ảnh chụp màn hình, hay khi hỏi AI. Lỡ để lộ thì báo trưởng nhóm thu hồi khoá ngay.

---

## 6. Chạy test

Test dùng dữ liệu mẫu trong `tests/fixtures/` — **không cần khoá, không cần mạng**. Chạy được ngay sau bước 4.

```bash
uv run pytest -q                            # toàn bộ test
uv run pytest tests/lake -q                 # chỉ test phần đọc dữ liệu
uv run pytest tests/api -q                  # chỉ test API
uv run pytest -q -k "mui_gio"               # chỉ test có chữ "mui_gio" trong tên
```

Kiểm tra định dạng code:

```bash
uv run ruff check src apps tests
```

Kết quả đúng: `21 passed` (số có thể tăng khi thêm test) và `All checks passed!`.

Chạy **mọi** kiểm tra một lần (Python + lint + kiểm tra kiểu TypeScript của web):

```bash
make test
```

---

## 7. Chạy web và trang kiểm soát

### Cách chạy hằng ngày: một lệnh

```bash
make dev
```

Lệnh này bật **hai tiến trình** trong cùng một terminal. `Ctrl+C` dừng cả hai.

| Tiến trình | Cổng | Mở trình duyệt | Là gì |
|---|---|---|---|
| Frontend — Vite | 5173 | http://127.0.0.1:5173 | **Web React** (`apps/web/`) |
| Backend — FastAPI | 8000 | http://127.0.0.1:8000 | **Trang kiểm soát dữ liệu** nội bộ (`apps/api/static/`) |
| | | http://127.0.0.1:8000/docs | Tài liệu API tự sinh |

```
Trình duyệt ──► :5173  Vite ──┬── trang React, JS, CSS: tự phục vụ
                              └── /api/... ──chuyển tiếp──► :8000 FastAPI ──► R2
```

Web React gọi `/api/...` trên **cùng địa chỉ 5173**; Vite đẩy các yêu cầu đó sang FastAPI (cấu hình trong `apps/web/vite.config.ts`). Vì với trình duyệt đó là cùng một địa chỉ, **không cần cấu hình CORS**.

### Vì sao là `make dev` mà không phải `npm run dev`

`make dev` **không thay thế** `npm run dev` — nó **gọi** `npm run dev` bên trong, và chạy thêm backend cùng lúc:

| Lệnh | Chạy những gì | Đứng ở đâu để chạy |
|---|---|---|
| `npm run dev` | **Chỉ** frontend (Vite, cổng 5173) | Trong `apps/web/` |
| `make dev` | Frontend **và** backend (FastAPI, cổng 8000), song song | Gốc repo |

Bên trong `Makefile`:

```makefile
api:  uv run uvicorn apps.api.main:app ... --port 8000   ← backend
web:  cd apps/web && npm run dev                          ← chính là npm run dev
dev:  make -j2 api web                                    ← chạy song song cả hai
```

**Nếu chỉ chạy `npm run dev`**, trang React vẫn mở được nhưng mọi chỗ cần dữ liệu đều báo *"Không tải được dữ liệu"*: Vite chuyển tiếp `/api` sang cổng 8000, mà không có backend nào đang chạy ở đó.

```
Trình duyệt ──► :5173 Vite ──► giao diện hiện ra được            ✓
                         └──► /api/... ──► :8000 KHÔNG AI CHẠY    ✗
```

`make dev` còn **kiểm tra file `.env` trước**: thiếu thì dừng ngay kèm hướng dẫn, không bật dở dang tiến trình nào.

### Chạy riêng từng tiến trình (hai terminal)

Kết quả **giống hệt** `make dev`, nhưng log mỗi bên nằm riêng một cửa sổ nên dễ đọc hơn:

```bash
make api                  # terminal 1: backend :8000
make web                  # terminal 2: frontend :5173
```

Không có `make` (ví dụ Windows không dùng WSL) thì gõ thẳng lệnh gốc:

```bash
# terminal 1 — backend
uv run uvicorn apps.api.main:app --host 127.0.0.1 --port 8000 --reload

# terminal 2 — frontend
cd apps/web
npm run dev
```

### Nên dùng cách nào

| Tình huống | Dùng |
|---|---|
| Làm việc hằng ngày, muốn một lệnh là xong | `make dev` |
| Cần đọc log từng bên cho rõ, hoặc đang gỡ lỗi backend | Hai terminal: `make api` + `make web` |
| Backend đã chạy sẵn, chỉ sửa giao diện | `cd apps/web && npm run dev` |
| Máy không có `make` | Hai terminal với lệnh gốc |

### Khi sửa API

```bash
# 1. sửa apps/api/schemas.py (và endpoint trong apps/api/main.py)
make types      # 2. sinh lại apps/web/openapi.json và apps/web/src/api/schema.d.ts
make test       # 3. TypeScript báo lỗi ở mọi chỗ frontend dùng sai → sửa cho hết
```

Commit **cả hai file sinh ra** trong cùng PR với thay đổi API. Không sửa tay `schema.d.ts`.

### Đóng gói web

```bash
make build      # ra apps/web/dist/ — file tĩnh, đem lên máy chủ hoặc Cloudflare Pages
```

---

## 7b. Chỉ chạy trang kiểm soát dữ liệu (không cần Node)

Frontend (`apps/api/static/`) và backend (`apps/api/main.py`) **chạy chung một server**, không cần build, không cần `npm`.

**Khi đang sửa code:**

```bash
uv run uvicorn apps.api.main:app --host 127.0.0.1 --port 8000 --reload
```

**Khi chỉ cần xem dữ liệu:**

```bash
uv run uvicorn apps.api.main:app --host 127.0.0.1 --port 8000
```

Chờ đến khi thấy dòng `Application startup complete.` rồi mở trình duyệt:

| Địa chỉ | Nội dung |
|---|---|
| http://127.0.0.1:8000 | Trang kiểm soát dữ liệu |
| http://127.0.0.1:8000/docs | Tài liệu API, thử gọi API ngay trên trình duyệt |

Dừng server: bấm `Ctrl+C` trong terminal đang chạy nó.

**Chạy với dữ liệu mẫu, không cần khoá R2:**

```bash
LAKE_BACKEND=local LAKE_LOCAL_ROOT=tests/fixtures \
  uv run uvicorn apps.api.main:app --host 127.0.0.1 --port 8000
```

**Khi nào cần làm gì:**

| Bạn vừa… | Cần làm |
|---|---|
| Sửa HTML / JS / CSS trong `apps/api/static/` | Bấm **F5** trên trình duyệt |
| Sửa file Python | Có `--reload` thì server tự khởi động lại và nạp lại dữ liệu; không có thì `Ctrl+C` rồi chạy lại |
| Biết có người vừa đẩy dữ liệu mới lên kho | Bấm nút **Tải lại từ kho** trên trang |

---

## 8. Gọi API bằng terminal

Mở **một terminal khác** trong lúc server đang chạy.

```bash
# Server còn sống không, đang có bao nhiêu bài
curl -s http://127.0.0.1:8000/api/health

# Tổng quan theo nguồn — python3 -m json.tool để in cho dễ đọc
curl -s http://127.0.0.1:8000/api/stats/overview | python3 -m json.tool

# Lỗi chất lượng theo nguồn
curl -s http://127.0.0.1:8000/api/stats/quality | python3 -m json.tool | head -40

# Tìm bài: nguồn tuoitre, có chữ "bão", 5 bài mới nhất
curl -s "http://127.0.0.1:8000/api/articles?source=tuoitre&q=b%C3%A3o&page_size=5" | python3 -m json.tool

# Bài thiếu tác giả của baochinhphu trong một khoảng ngày
curl -s "http://127.0.0.1:8000/api/articles?source=baochinhphu&issue=missing_author&date_from=2026-09-01&date_to=2026-09-16" | python3 -m json.tool

# Số bài theo ngày của một nguồn
curl -s "http://127.0.0.1:8000/api/stats/timeline?granularity=day&source=vnexpress" | python3 -m json.tool

# Danh sách file trên kho và thời điểm cập nhật cuối
curl -s http://127.0.0.1:8000/api/files | python3 -m json.tool

# Nạp lại dữ liệu từ kho (giống nút "Tải lại từ kho")
curl -s -X POST http://127.0.0.1:8000/api/admin/reload
```

Chữ tiếng Việt trong URL phải mã hoá: `bão` → `b%C3%A3o`. Cách dễ hơn là dùng tham số của `curl`:

```bash
curl -s -G http://127.0.0.1:8000/api/articles \
  --data-urlencode "q=bão" --data-urlencode "source=tuoitre" --data-urlencode "page_size=5" \
  | python3 -m json.tool
```

Giá trị hợp lệ của tham số:

| Tham số | Giá trị |
|---|---|
| `source` | `tuoitre`, `vietnamnet`, `vnexpress`, `baochinhphu` |
| `issue` | `missing_author`, `empty_content`, `short_content`, `bad_date`, `future_date`, `duplicate_url`, `duplicate_id` |
| `sort` | `newest`, `oldest`, `longest`, `shortest` |
| `granularity` | `day`, `hour` |
| `date_from`, `date_to` | Định dạng `YYYY-MM-DD`, tính theo giờ Việt Nam |

---

## 9. Kiểm tra kết nối R2

Liệt kê file trên kho — dùng được với **khoá chỉ đọc**, không ghi gì:

```bash
( set -a; source .env; set +a
uv run python - <<'PY'
import os, boto3
s3 = boto3.client(
    "s3",
    endpoint_url=f"https://{os.environ['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
    aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
    aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
    region_name="auto",
)
bucket = os.environ["R2_BUCKET"]
objs = s3.list_objects_v2(Bucket=bucket).get("Contents", [])
print(f"Kết nối được bucket {bucket}: {len(objs)} object")
for o in objs:
    print(f"  {o['Key']:<50} {o['Size']/1e6:6.1f} MB  {o['LastModified']:%Y-%m-%d %H:%M} UTC")
PY
)
```

Đếm số bài theo nguồn trực tiếp bằng DuckDB:

```bash
( set -a; source .env; set +a
uv run python - <<'PY'
import os, duckdb
con = duckdb.connect()
con.execute("INSTALL httpfs; LOAD httpfs;")
con.execute(f"""CREATE SECRET lake (TYPE r2,
    KEY_ID '{os.environ["R2_ACCESS_KEY_ID"]}', SECRET '{os.environ["R2_SECRET_ACCESS_KEY"]}',
    ACCOUNT_ID '{os.environ["R2_ACCOUNT_ID"]}')""")
print(con.sql(f"""
    SELECT lower(source) AS source, count(*) AS so_bai
    FROM read_json('r2://{os.environ["R2_BUCKET"]}/silver/*/*.jsonl', format = 'newline_delimited')
    GROUP BY 1 ORDER BY 2 DESC"""))
PY
)
```

Cấu trúc kho và schema từng trường: xem [lake-layout.md](lake-layout.md) và [data-contracts.md](data-contracts.md).

---

## 10. Quy trình làm việc với git

```bash
# 1. Luôn bắt đầu từ main mới nhất
git switch main
git pull

# 2. Tạo nhánh riêng cho việc mình làm
git switch -c feat/<module>-<mo-ta-ngan>          # ví dụ: feat/ingest-tuoitre-theo-ngay

# 3. Làm việc, chạy test, xem mình đã đổi gì
uv run pytest -q
uv run ruff check src apps tests
git status
git diff

# 4. Chọn đúng file để commit — KHÔNG dùng "git add ." khi chưa xem kỹ
git add <file-1> <file-2>
git diff --cached --name-only                     # kiểm tra lại: không có .env, không có dữ liệu

# 5. Commit, message bắt đầu bằng mã module
git commit -m "[INGEST] cào Tuổi Trẻ theo ngày qua sitemap"

# 6. Đẩy lên và mở Pull Request
git push -u origin HEAD
gh pr create --fill                               # mẫu PR tự điền, sửa lại cho đủ các mục
```

Mã module: `INGEST`, `LAKE`, `NLP`, `WEAK`, `EMB`, `CLUST`, `NAME`, `TREND`, `EVAL`, `API`, `WEB`, `MOBILE`, `INFRA`, `DOCS`.

Quy tắc đầy đủ: [AGENTS.md](../AGENTS.md), mục "Git".

---

## 11. Xử lý sự cố

| Lỗi | Nguyên nhân | Cách xử lý |
|---|---|---|
| `remote: Repository not found` khi `git pull` / `git push` | Tài khoản GitHub đang dùng không có quyền vào repo | `gh auth status` → `gh auth switch --user <tài-khoản-có-quyền>`; nếu chưa có tài khoản nào có quyền, nhờ Duy thêm làm collaborator |
| `uv: command not found` | Chưa nạp đường dẫn sau khi cài uv | `source "$HOME/.local/bin/env"` hoặc mở terminal mới |
| `Chưa có file .env nên backend không đọc được kho dữ liệu R2` khi `make dev` | Chưa tạo `.env` | `cp .env.example .env` rồi điền khoá — [mục 5](#5-cấu-hình-khoá-r2) |
| `ValueError: Thiếu biến môi trường: R2_...` khi chạy server | Đã có `.env` nhưng còn dòng trống | Điền đủ các dòng — [mục 5](#5-cấu-hình-khoá-r2) |
| `cd: no such file or directory: ranking-event-detection` | Gõ sai chữ hoa/thường — Linux phân biệt | `cd Ranking-Event-Detection` (gõ vài chữ đầu rồi bấm `Tab` để tự điền) |
| `AccessDenied` / `403` khi nạp dữ liệu | Khoá sai, đã bị thu hồi, hoặc chưa được gắn vào bucket | Xin khoá mới; kiểm tra độ dài bằng lệnh ở mục 5 |
| `NoSuchBucket` | Tên bucket trong `.env` sai | `R2_BUCKET=vietnam-news-datalake` |
| `[Errno 98] address already in use` | Cổng 8000 đang bị một server khác chiếm | Xem lệnh ngay dưới bảng |
| `Port 5173 is already in use` | Một Vite khác đang chạy | `pkill -f "[n]ode_modules/.bin/vite"` |
| Web React báo "Không tải được dữ liệu" | Backend chưa chạy — Vite không có chỗ để chuyển tiếp `/api` | Chạy `make dev` thay vì chỉ `make web` |
| `make types` báo `Cannot read properties of undefined (reading 'createKeywordTypeNode')` | Ai đó nâng TypeScript lên bản 7 | Trong `apps/web/`: `npm install -D typescript@5` |
| `npm ci` báo `package.json and package-lock.json are not in sync` | Có người sửa `package.json` mà không commit `package-lock.json` | Người đó chạy `npm install` rồi commit cả hai file |
| Trang mở được nhưng **không có biểu đồ** | Trình duyệt không tải được thư viện biểu đồ Chart.js | Cần Internet; bấm F12 → tab Console để xem lỗi |
| Số liệu trên trang cũ hơn dữ liệu trên kho | Server nạp dữ liệu một lần lúc khởi động | Bấm **Tải lại từ kho** |
| `git pull` báo có thay đổi chưa commit | Đang có file sửa dở | `git stash` → `git pull` → `git stash pop` |

**Giải phóng cổng 8000:**

```bash
ss -ltnp | grep ':8000'                           # xem tiến trình nào đang giữ cổng
pkill -f "[u]vicorn apps.api"                     # tắt server trang kiểm soát
```

Hoặc chạy server ở cổng khác: thay `--port 8000` bằng `--port 8001`.

---

## 12. Bảng tra nhanh

| Việc | Lệnh |
|---|---|
| Cập nhật code | `git switch main && git pull` |
| Cài / cập nhật thư viện (Python + JS) | `make install` |
| **Chạy web + backend** | **`make dev`** → http://127.0.0.1:5173 |
| Chạy mọi kiểm tra | `make test` |
| Sinh lại kiểu TypeScript sau khi sửa API | `make types` |
| Chạy test Python | `uv run pytest -q` |
| Kiểm tra định dạng code | `uv run ruff check src apps tests` |
| Chạy trang kiểm soát (đang sửa code) | `uv run uvicorn apps.api.main:app --host 127.0.0.1 --port 8000 --reload` |
| Chạy với dữ liệu mẫu, không cần khoá | `LAKE_BACKEND=local LAKE_LOCAL_ROOT=tests/fixtures uv run uvicorn apps.api.main:app --port 8000` |
| Server còn sống không | `curl -s http://127.0.0.1:8000/api/health` |
| Nạp lại dữ liệu từ kho | `curl -s -X POST http://127.0.0.1:8000/api/admin/reload` |
| Xem tài khoản GitHub đang dùng | `gh auth status` |
| Tắt server đang chạy nền | `pkill -f "[u]vicorn apps.api"` |
| Tắt Vite đang chạy nền | `pkill -f "[n]ode_modules/.bin/vite"` |
| Chạy bản triển khai (một cổng) | `make prod` → http://127.0.0.1:8000 |
| Mở ra Internet cho cả nhóm | Xem [docs/trien-khai.md](trien-khai.md) |
