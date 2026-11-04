import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router";
import { ApiError } from "./api/client";
import { App } from "./App";
import "./styles.css";

// Chỉ thử lại MỘT lần khi lỗi mạng hoặc lỗi 5xx tạm thời. 4xx (404…) và 503 ("chưa có kết quả pipeline") là trạng thái
// thật của server → hiện lỗi ngay, không bắt người xem chờ "Đang tải…".
const retry = (failureCount: number, error: unknown) =>
  failureCount < 1 && !(error instanceof ApiError && (error.status < 500 || error.status === 503));

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 60_000, retry } },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
