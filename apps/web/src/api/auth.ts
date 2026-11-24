// Tài khoản: backend thật ở apps/api/accounts.py (migration 003–006, cần Postgres):
//   POST /api/auth/register | login | logout | logout-all | verify-email | forgot-password | reset-password | change-password
//   GET  /api/auth/me
// Mặc định gọi MÁY CHỦ THẬT. Chỉ làm frontend mà không có Postgres → đặt VITE_AUTH_MOCK=1 khi chạy/đóng gói web để
// dùng ADAPTER GIẢ LẬP (mockdb.ts, lưu trên trình duyệt này), không phải sửa trang nào.
import {
  checkPassword, delay, deviceLabel, hashPassword, load, meOf, newId, nowIso, randomToken, save,
  type MockUser, type Role,
} from "./mockdb";

const flag = String(import.meta.env.VITE_AUTH_MOCK ?? "0").trim().toLowerCase();
/** true khi khu tài khoản/quản trị chạy giả lập (chỉ khi đặt VITE_AUTH_MOCK=1). */
export const AUTH_MOCK = ["1", "true", "on", "yes"].includes(flag);

export type { Role };
export interface User {
  id: string; email: string; display_name: string; role: Role; email_verified: boolean; created_at: string;
}
export type AuthErrorCode = "invalid_credentials" | "locked" | "weak_password" | "validation" | "unauthorized" | "server";

export class AuthError extends Error {
  /** `status`: mã HTTP máy chủ trả; không có khi không gọi tới được máy chủ (lỗi mạng) hoặc lỗi của bản giả lập. */
  constructor(public code: AuthErrorCode, message: string, public status?: number) { super(message); }
}

/** `detail` của FastAPI → câu đọc được. 422 trả MẢNG {loc, msg}: gộp "tên trường: msg" (không bao giờ ra "[object Object]"). */
function detailText(detail: unknown, fallback: string): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const parts = detail.map((d) => {
      if (typeof d === "string") return d;
      const { loc, msg } = (d ?? {}) as { loc?: unknown; msg?: unknown };
      if (typeof msg !== "string") return "";
      const field = Array.isArray(loc) ? loc.filter((x) => x !== "body" && x !== "query" && x !== "path").join(".") : "";
      const m = msg.replace(/^Value error,\s*/, "");
      return field ? `${field}: ${m}` : m;
    }).filter(Boolean);
    if (parts.length) return `Dữ liệu không hợp lệ — ${parts.join("; ")}`;
  }
  return fallback;
}

export const GENERIC_LOGIN_ERROR = "Email hoặc mật khẩu không đúng. Sai 5 lần liên tiếp, tài khoản bị khoá 15 phút.";
const MAX_FAILED = 5;
const LOCK_MS = 15 * 60_000;
const COMMON = ["12345678", "123456789", "password", "matkhau123", "11111111", "qwertyui", "abc12345", "iloveyou"];

/** Kiểm tra mật khẩu mới (giống luật dự kiến của máy chủ). Trả thông báo lỗi hoặc null. */
export function passwordProblem(pw: string): string | null {
  if (pw.length < 8) return "Mật khẩu cần ít nhất 8 ký tự.";
  if (COMMON.includes(pw.toLowerCase())) return "Mật khẩu quá phổ biến, hãy chọn mật khẩu khác.";
  return null;
}

export interface AuthApi {
  me(): Promise<User | null>;
  login(email: string, password: string, remember: boolean): Promise<User>;
  register(input: { display_name: string; email: string; password: string; role?: Role }): Promise<void>;
  logout(): Promise<void>;
  logoutAll(): Promise<void>;
  verifyEmail(token: string): Promise<void>;
  forgotPassword(email: string): Promise<void>;
  resetPassword(token: string, password: string): Promise<void>;
  changePassword(oldPassword: string, newPassword: string): Promise<void>;
}

// ------------------------------------------------------------------ máy chủ thật (khi VITE_AUTH_MOCK=0)
/** Mã CSRF từ cookie `csrf_token` (gửi kèm header X-CSRF-Token cho mọi lệnh ghi). */
export function csrf(): string {
  try {
    return document.cookie.split("; ").find((c) => c.startsWith("csrf_token="))?.split("=")[1] ?? "";
  } catch { return ""; }
}

/** Gọi API tài khoản (cookie phiên SameSite=Lax + header X-CSRF-Token cho POST/PUT/DELETE — theo thiết kế). */
export async function accountFetch<T>(method: string, path: string, body?: unknown): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, {
      method, credentials: "same-origin",
      headers: { "Content-Type": "application/json", ...(method !== "GET" ? { "X-CSRF-Token": csrf() } : {}) },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new AuthError("server", "Không kết nối được máy chủ.");
  }
  if (res.status === 401) throw new AuthError("unauthorized", "Phiên đăng nhập đã hết hạn.", 401);
  if (res.status === 423) throw new AuthError("locked", GENERIC_LOGIN_ERROR, 423);
  if (!res.ok) {
    const fallback = res.status === 422 ? "Dữ liệu gửi lên không hợp lệ." : res.statusText || `Lỗi ${res.status}.`;
    let detail: unknown = fallback;
    try { detail = (await res.json()).detail ?? fallback; } catch { /* không phải JSON */ }
    throw new AuthError(res.status === 400 || res.status === 422 ? "validation" : "server", detailText(detail, fallback), res.status);
  }
  return (res.status === 204 ? undefined : await res.json()) as T;
}

const realAuth: AuthApi = {
  me: async () => {
    try { return await accountFetch<User>("GET", "/api/auth/me"); }
    catch (e) { if (e instanceof AuthError && e.code === "unauthorized") return null; throw e; }
  },
  login: async (email, password, remember) => {
    try { return await accountFetch<User>("POST", "/api/auth/login", { email, password, remember }); }
    catch (e) {
      if (e instanceof AuthError && (e.code === "unauthorized" || e.code === "validation"))
        throw new AuthError("invalid_credentials", GENERIC_LOGIN_ERROR);
      throw e;
    }
  },
  register: (input) => accountFetch("POST", "/api/auth/register", input),
  logout: () => accountFetch("POST", "/api/auth/logout"),
  logoutAll: () => accountFetch("POST", "/api/auth/logout-all"),
  verifyEmail: (token) => accountFetch("POST", "/api/auth/verify-email", { token }),
  forgotPassword: (email) => accountFetch("POST", "/api/auth/forgot-password", { email }),
  resetPassword: (token, password) => accountFetch("POST", "/api/auth/reset-password", { token, password }),
  changePassword: (old_password, new_password) =>
    accountFetch("POST", "/api/auth/change-password", { old_password, new_password }),
};

// ------------------------------------------------------------------ giả lập
const publicUser = (u: MockUser): User => ({
  id: u.id, email: u.email, display_name: u.display_name, role: u.role, email_verified: u.email_verified,
  created_at: u.created_at,
});
const normEmail = (e: string) => e.trim().toLowerCase();

/** Người dùng của phiên hiện tại trên trình duyệt này (null nếu chưa đăng nhập / phiên bị thu hồi). */
export function mockCurrentUser(): MockUser | null {
  const db = load();
  const s = db.sessions.find((x) => x.id === db.current);
  return (s && db.users.find((u) => u.id === s.user_id)) || null;
}

function queueMail(to: string, kind: "verify" | "reset"): void {
  const db = load();
  const hours = kind === "verify" ? 24 : 1;
  db.outbox.unshift({ id: newId(), at: nowIso(), to, kind, token: randomToken(), used: false,
                      expires_at: new Date(Date.now() + hours * 3_600_000).toISOString() });
  save(db);
}

const mockAuth: AuthApi = {
  async me() {
    await delay(80);
    const u = mockCurrentUser();
    if (!u) return null;
    const db = load();
    const s = db.sessions.find((x) => x.id === db.current);
    if (s) { s.last_seen = nowIso(); save(db); }
    return publicUser(u);
  },
  async login(email, password) {
    await delay();
    const db = load();
    const u = db.users.find((x) => x.email === normEmail(email));
    if (u?.locked_until && u.locked_until > Date.now()) throw new AuthError("locked", GENERIC_LOGIN_ERROR);
    if (!u || !(await checkPassword(u, password))) {
      if (u) {
        u.failed += 1;
        if (u.failed >= MAX_FAILED) { u.locked_until = Date.now() + LOCK_MS; u.failed = 0; }
        save(db);
      }
      throw new AuthError("invalid_credentials", GENERIC_LOGIN_ERROR);
    }
    u.failed = 0; u.locked_until = null;
    const s = { id: newId(), user_id: u.id, device: deviceLabel(), created_at: nowIso(), last_seen: nowIso() };
    db.sessions.push(s);
    db.current = s.id;
    save(db);
    return publicUser(u);
  },
  async register({ display_name, email, password, role }) {
    await delay();
    const problem = passwordProblem(password);
    if (problem) throw new AuthError("weak_password", problem);
    if (!display_name.trim() || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim()))
      throw new AuthError("validation", "Hãy nhập tên hiển thị và một email hợp lệ.");
    const db = load();
    const e = normEmail(email);
    // Giống máy chủ dự kiến: email đã có tài khoản thì KHÔNG báo khác đi (tránh dò email), chỉ không tạo thêm.
    if (db.users.some((u) => u.email === e)) return;
    const u: MockUser = {
      id: newId(), email: e, display_name: display_name.trim(), role: role ?? "user", email_verified: false,
      created_at: nowIso(), pass: await hashPassword(password), failed: 0, locked_until: null,
    };
    db.users.push(u);
    meOf(db, u.id).notifications.unshift({
      id: newId(), kind: "Hệ thống", text: "Chào mừng bạn. Hãy mở link xác minh trong email để hoàn tất.", event_id: null,
      at: nowIso(), read: false,
    });
    // Giống máy chủ: đăng ký KHÔNG tạo phiên; tài khoản đăng nhập được ngay, kể cả khi chưa xác minh email.
    save(db);
    queueMail(e, "verify");
  },
  async logout() {
    await delay(120);
    const db = load();
    db.sessions = db.sessions.filter((s) => s.id !== db.current);
    db.current = null;
    save(db);
  },
  async logoutAll() {
    await delay(120);
    const db = load();
    const u = mockCurrentUser();
    if (u) db.sessions = db.sessions.filter((s) => s.user_id !== u.id);
    db.current = null;
    save(db);
  },
  async verifyEmail(token) {
    await delay();
    const db = load();
    const m = db.outbox.find((x) => x.kind === "verify" && x.token === token);
    if (!m || m.used || Date.parse(m.expires_at) < Date.now())
      throw new AuthError("validation", "Link xác minh không hợp lệ hoặc đã hết hạn.");
    m.used = true;
    const u = db.users.find((x) => x.email === m.to);
    if (u) u.email_verified = true;
    save(db);
  },
  async forgotPassword(email) {
    await delay();
    const e = normEmail(email);
    if (load().users.some((u) => u.email === e)) queueMail(e, "reset");   // không có tài khoản: im lặng như máy chủ
  },
  async resetPassword(token, password) {
    await delay();
    const problem = passwordProblem(password);
    if (problem) throw new AuthError("weak_password", problem);
    const db = load();
    const m = db.outbox.find((x) => x.kind === "reset" && x.token === token);
    if (!m || m.used || Date.parse(m.expires_at) < Date.now())
      throw new AuthError("validation", "Link đặt lại mật khẩu không hợp lệ hoặc đã hết hạn.");
    const u = db.users.find((x) => x.email === m.to);
    if (!u) throw new AuthError("validation", "Link đặt lại mật khẩu không hợp lệ hoặc đã hết hạn.");
    m.used = true;
    u.pass = await hashPassword(password);
    u.failed = 0; u.locked_until = null;
    db.sessions = db.sessions.filter((s) => s.user_id !== u.id);     // đặt mật khẩu mới → đăng xuất mọi thiết bị
    if (db.current && !db.sessions.some((s) => s.id === db.current)) db.current = null;
    save(db);
  },
  async changePassword(oldPassword, newPassword) {
    await delay();
    const u = mockCurrentUser();
    if (!u) throw new AuthError("unauthorized", "Bạn cần đăng nhập lại.");
    if (!(await checkPassword(u, oldPassword))) throw new AuthError("invalid_credentials", "Mật khẩu hiện tại không đúng.");
    const problem = passwordProblem(newPassword);
    if (problem) throw new AuthError("weak_password", problem);
    const db = load();
    const x = db.users.find((y) => y.id === u.id)!;
    x.pass = await hashPassword(newPassword);
    db.sessions = db.sessions.filter((s) => s.user_id !== u.id || s.id === db.current);   // giữ phiên này
    save(db);
  },
};

export const authApi: AuthApi = AUTH_MOCK ? mockAuth : realAuth;
