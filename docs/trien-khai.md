# Triển khai để cả nhóm truy cập bằng domain

> Mục tiêu: đồng đội mở một địa chỉ trên trình duyệt là xem được trang, không cần cài gì.

## 1. Khi triển khai, mọi thứ chạy trên MỘT cổng

Lúc phát triển có hai tiến trình (Vite 5173 + FastAPI 8000). Khi triển khai thì **đóng gói web React thành file tĩnh và để FastAPI phục vụ luôn**:

```
                        make prod
                            │
                 ┌──────────▼───────────┐
   Trình duyệt ─►│  FastAPI  cổng 8000  │
                 │  /            → web React (apps/web/dist)
                 │  /api/...     → dữ liệu JSON
                 │  /legacy/     → trang kiểm soát nội bộ cũ
                 │  /docs        → tài liệu API
                 └──────────────────────┘
```

Một cổng nên **không cần cấu hình CORS**, chỉ cần mở một địa chỉ ra Internet.

```bash
make prod        # tự chạy `make build` rồi bật server
```

## 2. Bắt buộc: đặt mật khẩu trước khi mở ra Internet

Trang hiển thị **toàn văn bài báo có bản quyền** và toàn bộ dữ liệu của nhóm. Không được để ai có link cũng xem được.

Thêm vào `.env`:

```bash
DASHBOARD_USER=nhom
DASHBOARD_PASSWORD=<đặt chuỗi dài, ngẫu nhiên>
```

Tạo mật khẩu ngẫu nhiên:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(24))"
```

Có hai biến này thì **mọi đường dẫn** (kể cả `/api` và `/docs`) đều hỏi đăng nhập. Để trống thì trang mở tự do — chỉ dùng khi chạy ở `127.0.0.1`.

Khoá R2 dùng khi triển khai nên là **khoá chỉ đọc** (Object Read only).

## 3. Chọn cách triển khai

| | Cách A — Tunnel tạm | Cách B — Tunnel + domain | Cách C — VPS + domain |
|---|---|---|---|
| Thời gian dựng | **5 phút** | 30 phút | 1–2 giờ |
| Cần domain | Không | **Có** (~250k/năm) | **Có** |
| Địa chỉ | Ngẫu nhiên, **đổi mỗi lần chạy** | Cố định | Cố định |
| Máy chạy | Máy bạn | Máy bạn hoặc VPS | VPS (~165k/tháng) |
| Mở cổng ra Internet | Không | Không | Có (80/443) |
| Chạy 24/7 | Không (tắt máy là mất) | Nếu đặt trên VPS | Có |
| Hợp cho | Demo, cho nhóm xem ngay hôm nay | **Dùng lâu dài** | Khi đã có VPS cho crawler |

---

## Cách A — Cloudflare Tunnel tạm thời (5 phút, không cần domain)

Cài `cloudflared` (không cần quyền quản trị):

```bash
mkdir -p ~/.local/bin
curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 \
  -o ~/.local/bin/cloudflared && chmod +x ~/.local/bin/cloudflared
cloudflared --version
```

Chạy hai terminal:

```bash
# Terminal 1 — server (nhớ đã đặt DASHBOARD_USER / DASHBOARD_PASSWORD trong .env)
make prod

# Terminal 2 — mở ra Internet
make tunnel
```

`cloudflared` in ra một địa chỉ dạng `https://<vài-chữ-ngẫu-nhiên>.trycloudflare.com`. Gửi địa chỉ đó **kèm tài khoản và mật khẩu** cho đồng đội.

⚠️ Địa chỉ **đổi mỗi lần chạy lại**, và **tắt máy là mất**. Chỉ hợp để xem tạm.

---

## Cách B — Domain riêng, địa chỉ cố định (khuyến nghị)

### B1. Có một domain trong tài khoản Cloudflare

Mua ở Cloudflare Registrar, hoặc mua nơi khác rồi trỏ nameserver về Cloudflare. Nhóm đã có tài khoản Cloudflare cho R2 nên dùng chung tài khoản đó.

### B2. Tạo tunnel

```bash
cloudflared tunnel login                     # mở trình duyệt, chọn domain
cloudflared tunnel create eventrank          # in ra UUID và đường dẫn file khoá
cloudflared tunnel route dns eventrank data.<domain-cua-ban>
```

### B3. Cấu hình

Tạo `~/.cloudflared/config.yml`:

```yaml
tunnel: <UUID vừa in ra>
credentials-file: /home/<user>/.cloudflared/<UUID>.json

ingress:
  - hostname: data.<domain-cua-ban>
    service: http://127.0.0.1:8000
  - service: http_status:404
```

### B4. Chạy

```bash
make prod                 # terminal 1
cloudflared tunnel run eventrank   # terminal 2
```

Mở `https://data.<domain-cua-ban>` — Cloudflare tự cấp HTTPS.

### B5. Chạy nền, tự bật lại sau khi khởi động máy

```bash
sudo cloudflared service install           # cloudflared chạy như dịch vụ hệ thống
```

Cho server FastAPI, tạo `/etc/systemd/system/eventrank.service`:

```ini
[Unit]
Description=Trang du lieu su kien tin tuc
After=network.target

[Service]
User=<user>
WorkingDirectory=/home/<user>/Ranking-Event-Detection
EnvironmentFile=/home/<user>/Ranking-Event-Detection/.env
ExecStart=/home/<user>/.local/bin/uv run uvicorn apps.api.main:app --host 127.0.0.1 --port 8000
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now eventrank
sudo systemctl status eventrank
```

### B6. Thay mật khẩu chung bằng đăng nhập từng người (tuỳ chọn, miễn phí)

Cloudflare **Zero Trust → Access → Applications → Add self-hosted**, chọn domain `data.<domain>`, đặt policy cho phép đúng email của 4 thành viên. Gói miễn phí hỗ trợ tới 50 người.

Khi đó mỗi người đăng nhập bằng email của mình, biết ai vào lúc nào, và bỏ được mật khẩu dùng chung.

---

## Cách C — VPS công khai + Caddy

Chỉ nên chọn khi nhóm đã thuê VPS cho crawler. Trên VPS:

```bash
# Caddy tự xin chứng chỉ HTTPS
sudo apt install -y caddy
```

`/etc/caddy/Caddyfile`:

```
data.<domain-cua-ban> {
    reverse_proxy 127.0.0.1:8000
}
```

```bash
sudo systemctl reload caddy
```

Trỏ bản ghi DNS `data` về IP của VPS. Nhớ mở tường lửa cổng 80 và 443, và **không mở cổng 8000** ra ngoài.

---

## 4. Cập nhật khi có code mới

```bash
git pull
make install        # chỉ khi uv.lock hoặc package-lock.json đổi
make build          # đóng gói lại web React
sudo systemctl restart eventrank     # hoặc Ctrl+C rồi `make prod` nếu chạy tay
```

## 5. Kiểm tra sau khi triển khai

```bash
curl -s -o /dev/null -w "%{http_code}\n" https://data.<domain>/            # 401 khi chưa đăng nhập
curl -s -u nhom:<mật khẩu> https://data.<domain>/api/health                # {"status":"ok",...}
```

Mở trang trên trình duyệt, kiểm tra nút **⟳ Cập nhật dữ liệu** hoạt động.

## 6. Những điều cần nhớ

| | |
|---|---|
| Dữ liệu vẫn nằm trên R2 | Máy chạy server chỉ giữ **bản sao trong RAM**; tắt server không mất dữ liệu |
| Server cần khoá R2 | Đặt trong `.env` trên máy chạy, dùng **khoá chỉ đọc** |
| Không bật public cho bucket R2 | Người dùng xem dữ liệu **qua trang**, không truy cập thẳng kho |
| Trang có nội dung báo có bản quyền | Luôn giữ mật khẩu hoặc Cloudflare Access; không công khai |
| Tài liệu API `/docs` cũng bị chặn | Vì nó nằm sau cùng lớp đăng nhập |
