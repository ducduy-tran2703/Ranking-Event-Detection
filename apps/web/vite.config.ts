import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Khi phát triển: trình duyệt mở http://127.0.0.1:5173 (Vite).
// Mọi yêu cầu bắt đầu bằng /api được Vite chuyển tiếp sang FastAPI ở cổng 8000.
// Nhờ vậy, với trình duyệt thì frontend và API "cùng một địa chỉ" → không cần cấu hình CORS.
export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    proxy: { "/api": "http://127.0.0.1:8000" },
  },
});
