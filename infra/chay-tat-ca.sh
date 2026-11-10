#!/usr/bin/env bash
# Bật / tắt / xem toàn bộ hệ thống EventRank trên máy local (WSL hoặc Linux).
#
#   make up       bật Postgres (chỉ kiểm), Qdrant, crawler, API, web, worker; Ctrl+C tắt hết
#   make down     tắt mọi thứ `make up` đã bật (dùng khi terminal chạy `make up` bị đóng ngang)
#   make status   xem dịch vụ nào đang chạy, RAM còn bao nhiêu
#
# Tuỳ chọn (biến môi trường, đặt trước lệnh, ví dụ `WORKER=0 make up`):
#   CRAWLER=1|0        bật crawler 8 báo :8002 (mặc định 1)
#   WORKER=auto|1|0    worker liên tục; auto = chỉ bật khi RAM trống ≥ WORKER_MIN_FREE_MB (mặc định auto)
#   WORKER_MIN_FREE_MB RAM trống tối thiểu cho WORKER=auto, MB (mặc định 2000; một vòng worker đỉnh ~1,9–2,2 GB)
#   QDRANT=1|0         bật Qdrant cho Hỏi đáp RAG (mặc định 1)
#   WEB_DIR            thư mục frontend (mặc định apps/web; bản Neumorphism: ../RED-web-redesign/apps/web)
#   WEB_HOST           địa chỉ Vite nghe (mặc định 0.0.0.0 để trình duyệt Windows vào được web trong WSL)
#   DETACH=1           bật xong thì trả terminal, dịch vụ chạy nền; tắt bằng `make down`
#
# Log: data/logs/<dịch vụ>.log · PID: data/run/<dịch vụ>.pid (cả hai trong /data/, đã gitignore).

set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

LOG_DIR="data/logs"
RUN_DIR="data/run"
SERVICES=(crawler api web worker)   # thứ tự bật; tắt theo thứ tự ngược lại

CRAWLER="${CRAWLER:-1}"
WORKER="${WORKER:-auto}"
WORKER_MIN_FREE_MB="${WORKER_MIN_FREE_MB:-2000}"
QDRANT="${QDRANT:-1}"
WEB_DIR="${WEB_DIR:-apps/web}"
WEB_HOST="${WEB_HOST:-0.0.0.0}"
API_PORT="${API_PORT:-8000}"
DETACH="${DETACH:-0}"
DOCKER_DESKTOP_EXE="${DOCKER_DESKTOP_EXE:-C:\\Program Files\\Docker\\Docker\\Docker Desktop.exe}"

if [ -t 1 ]; then B=$'\e[1m'; G=$'\e[32m'; Y=$'\e[33m'; R=$'\e[31m'; D=$'\e[2m'; N=$'\e[0m'; else B= G= Y= R= D= N=; fi
say()  { printf '%s\n' "${B}▸${N} $*"; }
ok()   { printf '%s\n' "  ${G}✓${N} $*"; }
warn() { printf '%s\n' "  ${Y}!${N} $*"; }
fail() { printf '%s\n' "  ${R}✗${N} $*"; }
die()  { fail "$*"; exit 1; }

port_of() {
    case "$1" in crawler) echo 8002 ;; api) echo "$API_PORT" ;; web) echo 5173 ;; *) echo "" ;; esac
}
url_of() {
    case "$1" in
        crawler) echo "http://localhost:8002/crawl/jobs" ;;
        api) echo "http://localhost:$API_PORT/docs" ;;
        web) echo "http://localhost:5173" ;;
        *) echo "-" ;;
    esac
}
mem_free_mb() { awk '/^MemAvailable:/ {print int($2/1024)}' /proc/meminfo; }
port_busy() { ss -ltnH "sport = :$1" 2>/dev/null | grep -q .; }
env_value() {  # đọc một biến từ .env mà không chạy file .env như script
    grep -m1 "^$1=" .env 2>/dev/null | cut -d= -f2- | sed -e 's/^"//' -e 's/"$//' -e "s/^'//" -e "s/'$//"
}

pid_of() {  # PID còn sống của dịch vụ (do script này bật), rỗng nếu không có
    local f="$RUN_DIR/$1.pid" pid
    [ -f "$f" ] || return 0
    pid="$(cat "$f")"
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then echo "$pid"; else rm -f "$f"; fi
}

start_service() {  # start_service <tên> <lệnh shell>
    local name="$1" cmd="$2" port pid
    port="$(port_of "$name")"
    if [ -n "$(pid_of "$name")" ]; then ok "$name đã chạy sẵn (PID $(pid_of "$name"))"; return 0; fi
    if [ -n "$port" ] && port_busy "$port"; then
        warn "$name: cổng $port đang bị tiến trình khác dùng, bỏ qua (tắt tiến trình đó hoặc dùng nó luôn)"
        return 1
    fi
    # setsid: dịch vụ có nhóm tiến trình riêng, `make down` tắt được cả make → uv → uvicorn/node.
    setsid bash -c "$cmd" >"$LOG_DIR/$name.log" 2>&1 </dev/null &
    pid=$!
    echo "$pid" >"$RUN_DIR/$name.pid"
    STARTED+=("$name")
    ok "$name đang khởi động (PID $pid, log $LOG_DIR/$name.log)"
}

wait_http() {  # wait_http <tên> <url> <giây>
    local name="$1" url="$2" limit="$3" i
    for ((i = 0; i < limit; i += 2)); do
        if curl -sf -o /dev/null --max-time 3 "$url"; then ok "$name sẵn sàng sau ${i}s"; return 0; fi
        if [ -z "$(pid_of "$name")" ]; then
            fail "$name đã thoát. Cuối log:"; tail -n 15 "$LOG_DIR/$name.log" | sed 's/^/      /'; return 1
        fi
        sleep 2
    done
    warn "$name chưa trả lời sau ${limit}s, vẫn để chạy; xem $LOG_DIR/$name.log"
    return 1
}

stop_service() {
    local name="$1" pid i
    pid="$(pid_of "$name")"
    [ -n "$pid" ] || return 0
    kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null
    for ((i = 0; i < 20; i++)); do kill -0 "$pid" 2>/dev/null || break; sleep 0.5; done
    kill -0 "$pid" 2>/dev/null && kill -KILL -- "-$pid" 2>/dev/null
    rm -f "$RUN_DIR/$name.pid"
    ok "đã tắt $name"
}

# --------------------------------------------------------------------------------------------- các bước

check_postgres() {
    say "Postgres"
    local url
    url="$(env_value DATABASE_URL)"
    [ -n "$url" ] || die "Thiếu DATABASE_URL trong .env"
    if ! pg_isready -q -d "$url" -t 3 2>/dev/null; then
        warn "Postgres chưa chạy, thử bật: sudo service postgresql start"
        sudo -n service postgresql start >/dev/null 2>&1 || true
        sleep 2
        pg_isready -q -d "$url" -t 5 2>/dev/null ||
            die "Không kết nối được Postgres. Tự chạy \`sudo service postgresql start\` (hoặc \`make db-up\` nếu dùng Postgres Docker) rồi thử lại."
    fi
    ok "Postgres kết nối được"
    local st
    st="$(uv run --group embed python -m eventrank.common.db status 2>&1)" || die "Không đọc được trạng thái migration:\n$st"
    if grep -Eq '^\s*(pending|modified|missing)\b' <<<"$st"; then
        warn "Có migration chưa áp hoặc bị sửa (không tự áp):"
        grep -E '^\s*(pending|modified|missing)\b' <<<"$st" | sed 's/^/      /'
        warn "Xem lại rồi chạy \`make db-migrate\` nếu đúng là cần áp."
    else
        ok "Migration đã áp đủ"
    fi
}

ensure_docker() {
    docker info >/dev/null 2>&1 && return 0
    if command -v powershell.exe >/dev/null 2>&1; then
        warn "Docker chưa chạy, đang bật Docker Desktop trên Windows (chờ tối đa 120 s)…"
        powershell.exe -NoProfile -Command "Start-Process '$DOCKER_DESKTOP_EXE'" >/dev/null 2>&1 || true
        local i
        for ((i = 0; i < 120; i += 5)); do docker info >/dev/null 2>&1 && return 0; sleep 5; done
    fi
    return 1
}

start_qdrant() {
    say "Qdrant (Hỏi đáp RAG)"
    if [ "$QDRANT" != "1" ]; then warn "bỏ qua (QDRANT=0): trang Hỏi đáp sẽ báo chưa sẵn sàng"; return; fi
    if ! ensure_docker; then
        warn "Không có Docker: bỏ qua Qdrant, trang Hỏi đáp sẽ báo chưa sẵn sàng. Bật Docker Desktop rồi chạy \`make qdrant-up\`."
        return
    fi
    docker compose -f infra/docker-compose.rag.yml up -d >"$LOG_DIR/qdrant.log" 2>&1 ||
        { warn "docker compose lỗi, xem $LOG_DIR/qdrant.log"; return; }
    local i
    for ((i = 0; i < 60; i += 2)); do
        curl -sf -o /dev/null --max-time 3 http://127.0.0.1:6333/readyz && { ok "Qdrant sẵn sàng · http://localhost:6333/dashboard"; return; }
        sleep 2
    done
    warn "Qdrant chưa sẵn sàng sau 60 s, xem \`docker compose -f infra/docker-compose.rag.yml logs\`"
}

start_crawler() {
    say "Crawler 8 báo"
    if [ "$CRAWLER" != "1" ]; then warn "bỏ qua (CRAWLER=0)"; return; fi
    if [ -z "$(env_value CRAWLER_USER_AGENT)" ]; then
        warn "bỏ qua: .env thiếu CRAWLER_USER_AGENT (tên bot + liên hệ thật, xem .env.example)"; return
    fi
    start_service crawler "make crawler" || return
    wait_http crawler http://127.0.0.1:8002/health 90 || return
    sleep 2   # bộ lập lịch tick ngay khi khởi động; chờ nó quyết định có cào bù khung giờ hiện tại hay không
    local info
    info="$(curl -sf --max-time 5 http://127.0.0.1:8002/crawl/schedule | python3 -c '
import sys, json
s = json.load(sys.stdin)
if s.get("active_job_id"):
    print("đang cào (job %s)" % s["active_job_id"][:8])
elif not s.get("enabled"):
    print("lịch cào đang TẮT, bật bằng PATCH /crawl/schedule {\"enabled\": true}")
else:
    print("khung giờ này đã cào, lượt kế tiếp lúc %s (cào ngay: make crawl-now)" % (s.get("next_run_at") or "?")[11:16])
' 2>/dev/null)"
    [ -n "$info" ] && ok "Crawler $info"
    warn "Mỗi báo cào xong mới nạp vào DB; lượt đầu có thể vài chục phút. Tiến độ: make ingest-status"
}

start_api() {
    say "API backend"
    start_service api "make api API_PORT=$API_PORT" && wait_http api "http://127.0.0.1:$API_PORT/api/trending" 240
}

start_web() {
    say "Web frontend ($WEB_DIR)"
    [ -d "$WEB_DIR" ] || { fail "Không có thư mục $WEB_DIR"; return; }
    [ -d "$WEB_DIR/node_modules" ] || { fail "Chưa cài thư viện web: cd $WEB_DIR && npm ci"; return; }
    start_service web "cd '$WEB_DIR' && npm run dev -- --host $WEB_HOST --port 5173 --strictPort" &&
        wait_http web http://127.0.0.1:5173/ 60
}

start_worker() {
    say "Worker (bài mới → sự kiện, 5 phút/vòng)"
    local free
    free="$(mem_free_mb)"
    case "$WORKER" in
        0) warn "bỏ qua (WORKER=0). Chạy tay một vòng: make worker ARGS=\"--once\""; return ;;
        auto)
            if [ "$free" -lt "$WORKER_MIN_FREE_MB" ]; then
                warn "bỏ qua: RAM trống ${free} MB < ${WORKER_MIN_FREE_MB} MB, một vòng worker cần tới ~2,2 GB."
                warn "Khi cào xong: tắt API rồi chạy \`make worker ARGS=\"--once\"\`, hoặc ép bật: WORKER=1 make up"
                return
            fi ;;
    esac
    start_service worker "make worker"
}

summary() {
    echo
    say "Tình trạng"
    local name pid
    for name in "${SERVICES[@]}"; do
        pid="$(pid_of "$name")"
        if [ -n "$pid" ]; then
            printf '  %s%-8s%s %-7s %-38s %s\n' "$G" "$name" "$N" "chạy" "$(url_of "$name")" "${D}$LOG_DIR/$name.log${N}"
        else
            printf '  %s%-8s%s %-7s\n' "$D" "$name" "$N" "tắt"
        fi
    done
    if curl -sf -o /dev/null --max-time 2 http://127.0.0.1:6333/readyz; then
        printf '  %s%-8s%s %-7s %s\n' "$G" "qdrant" "$N" "chạy" "http://localhost:6333/dashboard"
    else
        printf '  %s%-8s%s %-7s\n' "$D" "qdrant" "$N" "tắt"
    fi
    if pg_isready -q -d "$(env_value DATABASE_URL)" -t 2 2>/dev/null; then
        printf '  %s%-8s%s %-7s %s\n' "$G" "postgres" "$N" "chạy" "localhost:5432 (xem bằng DBeaver / VS Code)"
    else
        printf '  %s%-8s%s %-7s\n' "$D" "postgres" "$N" "tắt"
    fi
    echo "  RAM trống: $(mem_free_mb) MB"
}

# --------------------------------------------------------------------------------------------- lệnh

cmd_up() {
    [ -f .env ] || die "Chưa có .env: cp .env.example .env rồi điền (xem docs/huong-dan-chay.md)"
    mkdir -p "$LOG_DIR" "$RUN_DIR"
    STARTED=()
    say "RAM trống lúc bắt đầu: $(mem_free_mb) MB"
    check_postgres
    start_qdrant
    start_crawler
    start_api
    start_web
    start_worker   # bật cuối để quyết định theo RAM còn lại sau khi API và web đã chạy
    summary

    if [ "$DETACH" = "1" ]; then
        echo; say "Các dịch vụ chạy nền. Tắt bằng: make down"
        return 0
    fi
    echo; say "Ctrl+C để tắt crawler, API, web, worker (Postgres và Qdrant vẫn chạy)."
    trap 'echo; say "Đang tắt…"; for ((i=${#SERVICES[@]}-1; i>=0; i--)); do stop_service "${SERVICES[$i]}"; done; exit 0' INT TERM
    declare -A reported=()
    while true; do
        sleep 10
        for name in "${STARTED[@]}"; do
            if [ -z "$(pid_of "$name")" ] && [ -z "${reported[$name]:-}" ]; then
                reported[$name]=1
                fail "$name vừa dừng. Cuối log $LOG_DIR/$name.log:"
                tail -n 15 "$LOG_DIR/$name.log" | sed 's/^/      /'
            fi
        done
    done
}

cmd_down() {
    say "Tắt dịch vụ do \`make up\` bật"
    local i
    for ((i = ${#SERVICES[@]} - 1; i >= 0; i--)); do stop_service "${SERVICES[$i]}"; done
    if [ "${QDRANT_STOP:-0}" = "1" ] && docker info >/dev/null 2>&1; then
        docker compose -f infra/docker-compose.rag.yml stop >/dev/null 2>&1 && ok "đã dừng Qdrant"
    else
        ok "Qdrant và Postgres vẫn chạy (QDRANT_STOP=1 make down để dừng cả Qdrant)"
    fi
}

case "${1:-up}" in
    up) cmd_up ;;
    down) mkdir -p "$RUN_DIR"; cmd_down ;;
    status) mkdir -p "$RUN_DIR"; summary ;;
    *) echo "Dùng: $0 up|down|status"; exit 2 ;;
esac
