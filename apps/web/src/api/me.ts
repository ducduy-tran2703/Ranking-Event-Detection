// "Của tôi" + báo sai: hợp đồng DỰ KIẾN (thiết kế database, migration 004/005 chưa làm):
//   GET/PUT /api/me/settings · /api/me/bookmarks · /api/me/follows · /api/me/subscriptions · /api/me/sessions · DELETE /api/me
//   GET /api/me/notifications · POST /api/me/notifications/read · POST /api/events/{id}/feedback
// Giả lập khi AUTH_MOCK (xem auth.ts).
import { AUTH_MOCK, AuthError, accountFetch, mockCurrentUser } from "./auth";
import {
  delay, load, meOf, newId, nowIso, save,
  type Bookmark, type FeedbackKind, type Follow, type Notification, type Settings, type Snapshot, type Subscription,
} from "./mockdb";

export type { Bookmark, FeedbackKind, Follow, Notification, Settings, Snapshot, Subscription };
export interface Session { id: string; device: string; created_at: string; last_seen: string; current: boolean }

export interface MeApi {
  notifications(): Promise<Notification[]>;
  markAllRead(): Promise<void>;
  follows(): Promise<Follow[]>;
  follow(ev: Snapshot): Promise<void>;
  unfollow(eventId: string): Promise<void>;
  setFollowNotify(eventId: string, notify: boolean): Promise<void>;
  bookmarks(): Promise<Bookmark[]>;
  bookmark(ev: Snapshot, note?: string): Promise<void>;
  unbookmark(eventId: string): Promise<void>;
  subscriptions(): Promise<Subscription[]>;
  subscribe(kind: Subscription["kind"], value: string): Promise<void>;
  unsubscribe(id: string): Promise<void>;
  settings(): Promise<Settings>;
  updateSettings(patch: Partial<Settings>): Promise<Settings>;
  sessions(): Promise<Session[]>;
  revokeSession(id: string): Promise<void>;
  deleteAccount(): Promise<void>;
  /** Báo sai không cần đăng nhập. */
  feedback(eventId: string, body: { kind: FeedbackKind; note: string; event_name: string }): Promise<void>;
}

const MAX_TOPICS = 50;

const realMe: MeApi = {
  notifications: () => accountFetch("GET", "/api/me/notifications"),
  markAllRead: () => accountFetch("POST", "/api/me/notifications/read"),
  follows: () => accountFetch("GET", "/api/me/follows"),
  follow: (ev) => accountFetch("POST", "/api/me/follows", { event_id: ev.event_id }),
  unfollow: (id) => accountFetch("DELETE", `/api/me/follows/${encodeURIComponent(id)}`),
  setFollowNotify: (id, notify) => accountFetch("PUT", `/api/me/follows/${encodeURIComponent(id)}`, { notify }),
  bookmarks: () => accountFetch("GET", "/api/me/bookmarks"),
  bookmark: (ev, note = "") => accountFetch("POST", "/api/me/bookmarks", { event_id: ev.event_id, note }),
  unbookmark: (id) => accountFetch("DELETE", `/api/me/bookmarks/${encodeURIComponent(id)}`),
  subscriptions: () => accountFetch("GET", "/api/me/subscriptions"),
  subscribe: (kind, value) => accountFetch("POST", "/api/me/subscriptions", { kind, value }),
  unsubscribe: (id) => accountFetch("DELETE", `/api/me/subscriptions/${encodeURIComponent(id)}`),
  settings: () => accountFetch("GET", "/api/me/settings"),
  updateSettings: (patch) => accountFetch("PUT", "/api/me/settings", patch),
  sessions: () => accountFetch("GET", "/api/me/sessions"),
  revokeSession: (id) => accountFetch("DELETE", `/api/me/sessions/${encodeURIComponent(id)}`),
  deleteAccount: () => accountFetch("DELETE", "/api/me"),
  feedback: (id, body) => accountFetch("POST", `/api/events/${encodeURIComponent(id)}/feedback`, body),
};

/** Dữ liệu "của tôi" của người đang đăng nhập (giả lập); chưa đăng nhập → lỗi 401 như máy chủ. */
function mine() {
  const u = mockCurrentUser();
  if (!u) throw new AuthError("unauthorized", "Bạn cần đăng nhập.");
  const db = load();
  return { db, u, me: meOf(db, u.id) };
}

const mockMe: MeApi = {
  async notifications() { await delay(120); return mine().me.notifications; },
  async markAllRead() { const { db, me } = mine(); me.notifications.forEach((n) => { n.read = true; }); save(db); },
  async follows() { await delay(120); return mine().me.follows; },
  async follow(ev) {
    const { db, me } = mine();
    if (!me.follows.some((f) => f.event_id === ev.event_id)) me.follows.unshift({ ...ev, notify: true, at: nowIso() });
    save(db);
  },
  async unfollow(id) { const { db, me } = mine(); me.follows = me.follows.filter((f) => f.event_id !== id); save(db); },
  async setFollowNotify(id, notify) {
    const { db, me } = mine();
    const f = me.follows.find((x) => x.event_id === id);
    if (f) f.notify = notify;
    save(db);
  },
  async bookmarks() { await delay(120); return mine().me.bookmarks; },
  async bookmark(ev, note = "") {
    const { db, me } = mine();
    if (!me.bookmarks.some((b) => b.event_id === ev.event_id)) me.bookmarks.unshift({ ...ev, note, at: nowIso() });
    save(db);
  },
  async unbookmark(id) { const { db, me } = mine(); me.bookmarks = me.bookmarks.filter((b) => b.event_id !== id); save(db); },
  async subscriptions() { await delay(120); return mine().me.subscriptions; },
  async subscribe(kind, value) {
    const { db, me } = mine();
    const v = value.trim();
    if (!v) throw new AuthError("validation", "Hãy nhập từ khoá.");
    if (me.subscriptions.length >= MAX_TOPICS) throw new AuthError("validation", `Tối đa ${MAX_TOPICS} chủ đề.`);
    if (!me.subscriptions.some((s) => s.kind === kind && s.value.toLowerCase() === v.toLowerCase()))
      me.subscriptions.push({ id: newId(), kind, value: v, at: nowIso() });
    save(db);
  },
  async unsubscribe(id) { const { db, me } = mine(); me.subscriptions = me.subscriptions.filter((s) => s.id !== id); save(db); },
  async settings() { await delay(80); return mine().me.settings; },
  async updateSettings(patch) {
    const { db, me } = mine();
    me.settings = { ...me.settings, ...patch };
    save(db);
    return me.settings;
  },
  async sessions() {
    await delay(80);
    const { db, u } = mine();
    return db.sessions.filter((s) => s.user_id === u.id)
      .map((s) => ({ id: s.id, device: s.device, created_at: s.created_at, last_seen: s.last_seen, current: s.id === db.current }))
      .sort((a, b) => Number(b.current) - Number(a.current) || b.last_seen.localeCompare(a.last_seen));
  },
  async revokeSession(id) {
    const { db } = mine();
    db.sessions = db.sessions.filter((s) => s.id !== id);
    if (db.current === id) db.current = null;
    save(db);
  },
  async deleteAccount() {
    await delay();
    const { db, u } = mine();
    db.users = db.users.filter((x) => x.id !== u.id);
    db.sessions = db.sessions.filter((s) => s.user_id !== u.id);
    delete db.me[u.id];
    db.current = null;
    save(db);
  },
  async feedback(eventId, body) {
    await delay();
    const db = load();
    const u = mockCurrentUser();
    db.feedback.unshift({ id: newId(), event_id: eventId, event_name: body.event_name, kind: body.kind,
                          note: body.note.slice(0, 1000), who: u ? u.display_name : "khách", at: nowIso(), status: "open" });
    save(db);
  },
};

export const meApi: MeApi = AUTH_MOCK ? mockMe : realMe;
