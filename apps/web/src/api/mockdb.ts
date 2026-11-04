// "Cơ sở dữ liệu" GIẢ LẬP cho khu tài khoản/quản trị khi chưa có backend (bảng 003–006 + /api/auth/* chưa làm).
// Lưu trong localStorage CỦA TRÌNH DUYỆT NÀY; mọi đọc/ghi bọc try/catch (chế độ riêng tư, bị chặn lưu trữ → giữ trong
// bộ nhớ, mất khi tải lại trang). Không bao giờ log mật khẩu; mật khẩu người dùng tự tạo chỉ lưu dạng băm SHA-256.
// Chỉ được import từ src/api/ (auth.ts, me.ts, admin.ts).

export type Role = "user" | "editor" | "admin";

export interface MockUser {
  id: string; email: string; display_name: string; role: Role; email_verified: boolean; created_at: string;
  pass: string;                 // "demo" = mật khẩu demo chung (tài khoản mẫu); không thì "sha256:<hex>" / "fnv:<hex>"
  failed: number; locked_until: number | null;
}
export interface MockSession { id: string; user_id: string; device: string; created_at: string; last_seen: string }
export interface Snapshot { event_id: string; ten: string; size: number; n_sources: number; chuyen_muc: string | null }
export interface Follow extends Snapshot { notify: boolean; at: string }
export interface Bookmark extends Snapshot { note: string; at: string }
export interface Subscription { id: string; kind: "keyword" | "category"; value: string; at: string }
export interface Notification { id: string; kind: string; text: string; event_id: string | null; at: string; read: boolean }
export interface Settings {
  push: boolean; digest: "off" | "daily" | "weekly"; quiet_from: string; quiet_to: string; hidden_sources: string[];
}
export interface MeData {
  follows: Follow[]; bookmarks: Bookmark[]; subscriptions: Subscription[]; notifications: Notification[]; settings: Settings;
}
export type FeedbackKind = "wrong_name" | "stray_article" | "duplicate" | "other";
export interface Feedback {
  id: string; event_id: string; event_name: string; kind: FeedbackKind; note: string; who: string; at: string;
  status: "open" | "resolved" | "rejected";
}
export interface Mail { id: string; at: string; to: string; kind: "verify" | "reset"; token: string; used: boolean; expires_at: string }
export interface ApiToken { id: string; label: string; source: string; prefix: string; created_at: string; revoked: boolean }

interface DB {
  version: 1; users: MockUser[]; sessions: MockSession[]; current: string | null; me: Record<string, MeData>;
  feedback: Feedback[]; outbox: Mail[]; tokens: ApiToken[];
}

export const DEMO_PASSWORD = "matkhau-demo";
export const DEMO_ACCOUNTS: { email: string; role: Role; name: string }[] = [
  { email: "admin@example.com", role: "admin", name: "Quản trị Demo" },
  { email: "bientap@example.com", role: "editor", name: "Biên tập Demo" },
  { email: "ban@example.com", role: "user", name: "Bạn Đọc Demo" },
];
const KEY = "eventrank.mock.v1";

const nowIso = () => new Date().toISOString();
export const newId = () =>
  (globalThis.crypto && "randomUUID" in globalThis.crypto)
    ? globalThis.crypto.randomUUID()
    : `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;

export const emptyMe = (): MeData => ({
  follows: [], bookmarks: [], subscriptions: [], notifications: [],
  settings: { push: true, digest: "off", quiet_from: "22:00", quiet_to: "07:00", hidden_sources: [] },
});

function seed(): DB {
  const at = nowIso();
  return {
    version: 1, current: null, sessions: [], feedback: [], outbox: [], tokens: [],
    users: DEMO_ACCOUNTS.map((a, i) => ({
      id: `demo-${i + 1}`, email: a.email, display_name: a.name, role: a.role, email_verified: true, created_at: at,
      pass: "demo", failed: 0, locked_until: null,
    })),
    me: {},
  };
}

let memory: DB | null = null;

export function load(): DB {
  if (memory) return memory;
  try {
    const raw = window.localStorage.getItem(KEY);
    if (raw) {
      const db = JSON.parse(raw) as DB;
      if (db && db.version === 1 && Array.isArray(db.users)) return (memory = db);
    }
  } catch { /* bị chặn lưu trữ hoặc dữ liệu hỏng → dựng lại */ }
  return (memory = seed());
}

export function save(db: DB): void {
  memory = db;
  try { window.localStorage.setItem(KEY, JSON.stringify(db)); } catch { /* chỉ giữ trong bộ nhớ */ }
}

/** Xoá toàn bộ dữ liệu giả lập của trình duyệt này (nút trên trang Quản trị / Của tôi). */
export function resetMock(): void {
  memory = null;
  try { window.localStorage.removeItem(KEY); } catch { /* bỏ qua */ }
}

export function meOf(db: DB, userId: string): MeData {
  return (db.me[userId] ??= emptyMe());
}

/** Băm mật khẩu để không lưu bản rõ (giả lập; máy chủ thật dùng Argon2id). */
export async function hashPassword(pw: string): Promise<string> {
  try {
    if (globalThis.crypto?.subtle) {
      const buf = await globalThis.crypto.subtle.digest("SHA-256", new TextEncoder().encode(`eventrank:${pw}`));
      return "sha256:" + [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");
    }
  } catch { /* rơi về FNV bên dưới */ }
  let h = 0x811c9dc5;
  for (const ch of `eventrank:${pw}`) h = Math.imul(h ^ ch.charCodeAt(0), 0x01000193) >>> 0;
  return `fnv:${h.toString(16)}`;
}

export async function checkPassword(u: MockUser, pw: string): Promise<boolean> {
  if (u.pass === "demo") return pw === DEMO_PASSWORD;
  return u.pass === (await hashPassword(pw));
}

export function deviceLabel(): string {
  const ua = typeof navigator === "undefined" ? "" : navigator.userAgent;
  const browser = /Edg\//.test(ua) ? "Edge" : /Firefox\//.test(ua) ? "Firefox" : /Chrome\//.test(ua) ? "Chrome"
    : /Safari\//.test(ua) ? "Safari" : "Trình duyệt";
  const os = /Windows/.test(ua) ? "Windows" : /Android/.test(ua) ? "Android" : /iPhone|iPad/.test(ua) ? "iOS"
    : /Mac OS X/.test(ua) ? "macOS" : /Linux/.test(ua) ? "Linux" : "máy không rõ";
  return `${browser} trên ${os}`;
}

export const randomToken = (bytes = 18) => {
  const a = new Uint8Array(bytes);
  try { globalThis.crypto.getRandomValues(a); } catch { a.forEach((_, i) => { a[i] = Math.floor(Math.random() * 256); }); }
  return [...a].map((b) => b.toString(16).padStart(2, "0")).join("");
};

/** Độ trễ giả như gọi mạng để thấy được trạng thái "đang gửi…". */
export const delay = (ms = 250) => new Promise((r) => setTimeout(r, ms));
export { nowIso };
