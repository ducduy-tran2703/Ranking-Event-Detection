// Quản trị: hợp đồng DỰ KIẾN (thiết kế database, migration 006 chưa làm):
//   /api/admin/users · /api/admin/feedback · /api/admin/api-tokens · /api/admin/outbox (thư hệ thống, bản demo không gửi)
// Giả lập khi AUTH_MOCK (xem auth.ts): dữ liệu là của trình duyệt này — người dùng đã đăng ký thử, báo sai đã gửi thử.
import { AUTH_MOCK, AuthError, accountFetch, mockCurrentUser, type User } from "./auth";
import { delay, load, newId, nowIso, randomToken, save, type ApiToken, type Feedback, type Mail, type Role } from "./mockdb";

export type { ApiToken, Feedback, Mail };
export interface AdminUser extends User { locked_until: string | null }

export interface AdminApi {
  users(): Promise<AdminUser[]>;
  setRole(id: string, role: Role): Promise<void>;
  unlock(id: string): Promise<void>;
  feedback(): Promise<Feedback[]>;
  resolveFeedback(id: string, status: "resolved" | "rejected"): Promise<void>;
  outbox(): Promise<Mail[]>;
  tokens(): Promise<ApiToken[]>;
  /** Trả khoá ĐẦY ĐỦ — chỉ hiện một lần. */
  createToken(label: string, source: string): Promise<string>;
  revokeToken(id: string): Promise<void>;
}

const realAdmin: AdminApi = {
  users: () => accountFetch("GET", "/api/admin/users"),
  setRole: (id, role) => accountFetch("PUT", `/api/admin/users/${encodeURIComponent(id)}`, { role }),
  unlock: (id) => accountFetch("POST", `/api/admin/users/${encodeURIComponent(id)}/unlock`),
  feedback: () => accountFetch("GET", "/api/admin/feedback"),
  resolveFeedback: (id, status) => accountFetch("PUT", `/api/admin/feedback/${encodeURIComponent(id)}`, { status }),
  outbox: () => accountFetch("GET", "/api/admin/outbox"),
  tokens: () => accountFetch("GET", "/api/admin/api-tokens"),
  createToken: async (label, source) =>
    (await accountFetch<{ token: string }>("POST", "/api/admin/api-tokens", { label, source, scope: "ingest:write" })).token,
  revokeToken: (id) => accountFetch("DELETE", `/api/admin/api-tokens/${encodeURIComponent(id)}`),
};

function requireAdmin() {
  const u = mockCurrentUser();
  if (!u) throw new AuthError("unauthorized", "Bạn cần đăng nhập.");
  if (u.role !== "admin") throw new AuthError("unauthorized", "Cần vai trò quản trị.");
  return load();
}

const mockAdmin: AdminApi = {
  async users() {
    await delay(120);
    return requireAdmin().users.map((u) => ({
      id: u.id, email: u.email, display_name: u.display_name, role: u.role, email_verified: u.email_verified,
      created_at: u.created_at, locked_until: u.locked_until && u.locked_until > Date.now() ? new Date(u.locked_until).toISOString() : null,
    }));
  },
  async setRole(id, role) {
    const db = requireAdmin();
    const u = db.users.find((x) => x.id === id);
    if (u) u.role = role;
    save(db);
  },
  async unlock(id) {
    const db = requireAdmin();
    const u = db.users.find((x) => x.id === id);
    if (u) { u.locked_until = null; u.failed = 0; }
    save(db);
  },
  async feedback() { await delay(120); return requireAdmin().feedback; },
  async resolveFeedback(id, status) {
    const db = requireAdmin();
    const f = db.feedback.find((x) => x.id === id);
    if (f) f.status = status;
    save(db);
  },
  async outbox() { await delay(120); return requireAdmin().outbox; },
  async tokens() { await delay(120); return requireAdmin().tokens; },
  async createToken(label, source) {
    const db = requireAdmin();
    const token = `er_${randomToken(20)}`;
    db.tokens.unshift({ id: newId(), label: label.trim() || "Không tên", source, prefix: token.slice(0, 10), created_at: nowIso(),
                        revoked: false });
    save(db);
    return token;           // không lưu khoá đầy đủ (máy chủ thật chỉ lưu sha256)
  },
  async revokeToken(id) {
    const db = requireAdmin();
    const t = db.tokens.find((x) => x.id === id);
    if (t) t.revoked = true;
    save(db);
  },
};

export const adminApi: AdminApi = AUTH_MOCK ? mockAdmin : realAdmin;
