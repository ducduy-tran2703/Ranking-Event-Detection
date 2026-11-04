import { useEffect, useRef, useState, type CSSProperties, type FormEvent, type ReactNode } from "react";
import { Link, useNavigate } from "react-router";
import {
  meApi, useBookmarks, useChangePassword, useCurrentUser, useDeleteAccount, useFollows, useLogout, useMeAction,
  useNotifications, useSessions, useSettings, useSubscriptions,
} from "../../api/accountQueries";
import { AuthError } from "../../api/auth";
import type { Settings } from "../../api/me";
import { useRunInfo } from "../../api/queries";
import { ConfirmBox } from "../../components/ConfirmBox";
import { PreviewStrip } from "../../components/Layouts";
import { ErrorBox, Loading } from "../../components/Status";
import { fmtShort, timeAgo } from "../../lib/format";
import { eventHref } from "../../lib/routes";
import { DEFAULT_SOURCES, sourceName } from "../../lib/sources";
import { useTitle } from "../../lib/useTitle";

const delay = (s: number): CSSProperties => ({ animationDelay: `${s}s` });
const SECTIONS = [
  ["thong-bao", "Thông báo"], ["theo-doi", "Đang theo dõi"], ["da-luu", "Đã lưu"], ["chu-de", "Chủ đề"],
  ["cai-dat", "Cài đặt"], ["bao-mat", "Bảo mật"],
] as const;
const errText = (e: unknown) => (e instanceof AuthError ? e.message : e instanceof Error ? e.message : String(e));

/** Trang "Của tôi" (thiết kế Me). Dữ liệu qua src/api/me.ts — giả lập trên trình duyệt này khi VITE_AUTH_MOCK bật. */
export function MePage() {
  useTitle("Trang của tôi");
  const { data: user } = useCurrentUser();
  const logout = useLogout();
  const navigate = useNavigate();
  const [active, setActive] = useState<string>("thong-bao");
  if (!user) return null;
  return (
    <div className="page">
      <PreviewStrip />
      <div className="split" style={{ gap: 28 }}>
        <nav aria-label="Trang của tôi" className="side-nav me-nav rise" style={{ flex: "1 1 200px", minWidth: 0 }}>
          {SECTIONS.map(([id, label]) => (
            <a key={id} href={`#${id}`} className={active === id ? "active" : undefined} onClick={() => setActive(id)}>{label}</a>
          ))}
          <button type="button" className="logout" onClick={() => logout.mutateAsync().then(() => navigate("/"), () => undefined)}>
            Đăng xuất
          </button>
        </nav>
        <div className="main" style={{ flex: "999 1 640px" }}>
          <h1 className="rise" style={{ fontSize: 28 }}>Xin chào, <span style={{ color: "var(--accent)" }}>{user.display_name}</span></h1>
          <Notifications />
          <Follows />
          <Saved />
          <Topics />
          <SettingsCard />
          <Security email={user.email} verified={user.email_verified} />
        </div>
      </div>
    </div>
  );
}

function Section({ id, title, hint, actions, children, d }: {
  id: string; title: string; hint?: string; actions?: ReactNode; children: ReactNode; d: number;
}) {
  return (
    <section id={id} aria-labelledby={`h-${id}`} className="card pad-sm rise" style={{ ...delay(d), scrollMarginTop: 96 }}>
      <div className="row-between" style={{ gap: 10 }}>
        <h2 id={`h-${id}`} style={{ fontSize: 17 }}>{title}</h2>
        {actions}
      </div>
      {hint && <p className="hint" style={{ marginBottom: 8 }}>{hint}</p>}
      {children}
    </section>
  );
}

function QueryState({ q, empty, children }: {
  q: { isPending: boolean; error: unknown; refetch: () => unknown; data?: unknown[] }; empty: string; children: ReactNode;
}) {
  if (q.isPending) return <Loading lines={2} />;
  if (q.error) return <ErrorBox error={q.error} onRetry={() => q.refetch()} />;
  if (!q.data?.length) return <p className="muted small" style={{ padding: "8px 0" }}>{empty}</p>;
  return <>{children}</>;
}

function Notifications() {
  const q = useNotifications();
  const readAll = useMeAction(() => meApi.markAllRead());
  const unread = q.data?.filter((n) => !n.read).length ?? 0;
  return (
    <Section id="thong-bao" title="Thông báo" d={.05} actions={unread > 0 && (
      <button type="button" className="btn-ghost sm pill" onClick={() => readAll.mutate(undefined)}>Đánh dấu đã đọc hết</button>
    )}>
      <QueryState q={q} empty="Chưa có thông báo nào. Theo dõi sự kiện hoặc đăng ký chủ đề để nhận tin.">
        <ul className="rows" style={{ marginTop: 8 }}>
          {q.data?.map((n) => (
            <li key={n.id} className={n.read ? undefined : "unread"} style={{ display: "flex", gap: 12 }}>
              <span aria-hidden="true" style={{ width: 9, height: 9, marginTop: 8, borderRadius: "50%", flex: "none",
                background: n.read ? "transparent" : "var(--accent-2)" }} />
              <div style={{ minWidth: 0 }}>
                <div className="small muted">{n.kind} · {fmtShort(n.at)}{!n.read && <span className="sr-only"> · chưa đọc</span>}</div>
                {n.event_id ? <Link to={eventHref(n.event_id)} style={{ fontWeight: n.read ? 400 : 600 }}>{n.text}</Link>
                  : <span style={{ fontWeight: n.read ? 400 : 600 }}>{n.text}</span>}
              </div>
            </li>
          ))}
        </ul>
      </QueryState>
    </Section>
  );
}

function Follows() {
  const q = useFollows();
  const unfollow = useMeAction((id: string) => meApi.unfollow(id));
  const notify = useMeAction((v: { id: string; on: boolean }) => meApi.setFollowNotify(v.id, v.on));
  return (
    <Section id="theo-doi" title="Đang theo dõi" hint="Bạn được báo khi sự kiện có thêm nhiều bài mới." d={.1}>
      <QueryState q={q} empty="Bạn chưa theo dõi sự kiện nào. Mở một sự kiện và bấm “Theo dõi diễn biến”.">
        <ul className="rows">
          {q.data?.map((f) => (
            <li key={f.event_id} className="inline" style={{ gap: 12 }}>
              <div style={{ flex: "1 1 320px", minWidth: 0 }}>
                <Link to={eventHref(f.event_id)} style={{ fontWeight: 600 }}>{f.ten}</Link>
                <div className="small muted">{[f.chuyen_muc, `${f.size} bài`, `${f.n_sources} báo`, `theo dõi từ ${fmtShort(f.at)}`]
                  .filter(Boolean).join(" · ")}</div>
              </div>
              <label className="check" style={{ alignItems: "center" }}>
                <input type="checkbox" checked={f.notify} onChange={(e) => notify.mutate({ id: f.event_id, on: e.target.checked })} />
                Báo cho tôi
              </label>
              <button type="button" className="btn-ghost sm pill" onClick={() => unfollow.mutate(f.event_id)}
                      aria-label={`Bỏ theo dõi: ${f.ten}`}>Bỏ theo dõi</button>
            </li>
          ))}
        </ul>
      </QueryState>
    </Section>
  );
}

function Saved() {
  const q = useBookmarks();
  const remove = useMeAction((id: string) => meApi.unbookmark(id));
  return (
    <Section id="da-luu" title="Đã lưu" d={.15}>
      <QueryState q={q} empty="Chưa lưu sự kiện nào. Bấm “Lưu” ở trang sự kiện để đọc lại sau.">
        <ul className="rows">
          {q.data?.map((b) => (
            <li key={b.event_id} className="inline" style={{ gap: 12 }}>
              <div style={{ flex: "1 1 320px", minWidth: 0 }}>
                <Link to={eventHref(b.event_id)} style={{ fontWeight: 600 }}>{b.ten}</Link>
                <div className="small muted">
                  {[b.chuyen_muc, `${b.size} bài`, `lưu ngày ${fmtShort(b.at).slice(0, 5)}`, b.note && `Ghi chú: ${b.note}`].filter(Boolean).join(" · ")}
                </div>
              </div>
              <button type="button" className="btn-ghost sm pill" onClick={() => remove.mutate(b.event_id)}
                      aria-label={`Bỏ lưu: ${b.ten}`}>Bỏ lưu</button>
            </li>
          ))}
        </ul>
      </QueryState>
    </Section>
  );
}

function Topics() {
  const q = useSubscriptions();
  const [value, setValue] = useState("");
  const [kind, setKind] = useState<"keyword" | "category">("keyword");
  const add = useMeAction((v: { kind: "keyword" | "category"; value: string }) => meApi.subscribe(v.kind, v.value));
  const remove = useMeAction((id: string) => meApi.unsubscribe(id));
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (value.trim()) add.mutate({ kind, value }, { onSuccess: () => setValue("") });
  };
  return (
    <Section id="chu-de" title="Chủ đề đăng ký" hint="Có sự kiện mới khớp chủ đề, bạn sẽ nhận thông báo. Tối đa 50 chủ đề." d={.2}>
      <QueryState q={q} empty="Chưa đăng ký chủ đề nào.">
        <div className="chips">
          {q.data?.map((s) => (
            <span key={s.id} className="tag" style={{ fontSize: 14, fontWeight: 400, padding: "4px 4px 4px 12px" }}>
              {s.kind === "keyword" ? "Từ khoá" : "Chuyên mục"}: {s.value}
              <button type="button" className="icon-btn" style={{ width: 32, height: 32 }} aria-label={`Bỏ chủ đề ${s.value}`}
                      onClick={() => remove.mutate(s.id)}>✕</button>
            </span>
          ))}
        </div>
      </QueryState>
      <form onSubmit={submit} className="inline" style={{ marginTop: 12 }}>
        <label htmlFor="topic-kind" className="sr-only">Loại chủ đề</label>
        <select id="topic-kind" className="field" value={kind} onChange={(e) => setKind(e.target.value as "keyword" | "category")}>
          <option value="keyword">Từ khoá</option>
          <option value="category">Chuyên mục</option>
        </select>
        <label htmlFor="topic" className="sr-only">Thêm chủ đề</label>
        <input id="topic" className="field" style={{ flex: "1 1 240px", borderRadius: 999 }} placeholder="Thêm từ khoá, người, địa danh…"
               value={value} onChange={(e) => setValue(e.target.value)} />
        <button type="submit" className="btn pill solid" disabled={!value.trim() || add.isPending}>Thêm</button>
      </form>
      {add.error && <p className="field-error" role="alert">{errText(add.error)}</p>}
    </Section>
  );
}

function SettingsCard() {
  const q = useSettings();
  const run = useRunInfo();
  // Cập nhật lạc quan: ô đổi ngay theo `pending`; lỗi thì bỏ `pending` (về giá trị máy chủ) và báo.
  const [pending, setPending] = useState<Partial<Settings>>({});
  const save = useMeAction((patch: Partial<Settings>) => meApi.updateSettings(patch));
  const sources = run.data?.nguon_bao.length ? run.data.nguon_bao : DEFAULT_SOURCES;
  const s = q.data ? { ...q.data, ...pending } : undefined;
  const set = (patch: Partial<Settings>) => {
    setPending((p) => ({ ...p, ...patch }));
    save.mutate(patch, { onError: () => setPending({}) });
  };
  useEffect(() => {                         // máy chủ đã có giá trị mới → bỏ phần chờ tương ứng
    if (!q.data) return;
    setPending((p) => {
      const next = { ...p };
      for (const k of Object.keys(p) as (keyof Settings)[]) {
        if (JSON.stringify(q.data![k]) === JSON.stringify(p[k])) delete next[k];
      }
      return Object.keys(next).length === Object.keys(p).length ? p : next;
    });
  }, [q.data]);
  return (
    <Section id="cai-dat" title="Cài đặt" d={.25} actions={
      save.isError ? <span className="small" role="alert" style={{ color: "var(--danger)" }}>Không lưu được, đã hoàn lại</span>
        : save.isSuccess && <span className="small" role="status" style={{ color: "var(--ok)" }}>Đã lưu</span>}>
      {q.isPending && <Loading lines={3} />}
      {q.error && <ErrorBox error={q.error} onRetry={() => q.refetch()} />}
      {s && (
        <div className="stack" style={{ gap: 14, marginTop: 8 }}>
          <label className="check" style={{ alignItems: "center" }}>
            <input type="checkbox" checked={s.push} onChange={(e) => set({ push: e.target.checked })} />
            Nhận thông báo trên trình duyệt và điện thoại
          </label>
          <fieldset className="inline" style={{ gap: "8px 18px" }}>
            <legend>Bản tin qua email</legend>
            {([["off", "Tắt"], ["daily", "Hằng ngày"], ["weekly", "Hằng tuần"]] as const).map(([v, l]) => (
              <label key={v} className="check" style={{ alignItems: "center" }}>
                <input type="radio" name="digest" value={v} checked={s.digest === v} onChange={() => set({ digest: v })} />{l}
              </label>
            ))}
          </fieldset>
          <div className="inline" style={{ gap: 10 }}>
            <span style={{ fontWeight: 600 }} id="quiet-label">Giờ yên lặng</span>
            <label htmlFor="quiet-from" className="small muted">từ</label>
            <input id="quiet-from" className="field" type="time" value={s.quiet_from} aria-describedby="quiet-label"
                   onChange={(e) => set({ quiet_from: e.target.value })} />
            <label htmlFor="quiet-to" className="small muted">đến</label>
            <input id="quiet-to" className="field" type="time" value={s.quiet_to} aria-describedby="quiet-label"
                   onChange={(e) => set({ quiet_to: e.target.value })} />
          </div>
          <fieldset className="inline" style={{ gap: "8px 16px" }}>
            <legend>Ẩn báo</legend>
            {sources.map((src) => (
              <label key={src} className="check" style={{ alignItems: "center" }}>
                <input type="checkbox" checked={s.hidden_sources.includes(src)}
                       onChange={(e) => set({ hidden_sources: e.target.checked
                         ? [...s.hidden_sources, src] : s.hidden_sources.filter((x) => x !== src) })} />
                {sourceName(src)}
              </label>
            ))}
          </fieldset>
        </div>
      )}
    </Section>
  );
}

function Security({ email, verified }: { email: string; verified: boolean }) {
  const sessions = useSessions();
  const revoke = useMeAction((id: string) => meApi.revokeSession(id));
  const logoutAll = useLogout(true);
  const del = useDeleteAccount();
  const change = useChangePassword();
  const navigate = useNavigate();
  const [pwOpen, setPwOpen] = useState(false);
  const [confirm, setConfirm] = useState<null | "all" | "delete">(null);
  const allBtn = useRef<HTMLButtonElement>(null);
  const delBtn = useRef<HTMLButtonElement>(null);
  const [oldPw, setOldPw] = useState("");
  const [newPw, setNewPw] = useState("");

  return (
    <Section id="bao-mat" title="Bảo mật" d={.3}>
      <p style={{ fontSize: 14, margin: "4px 0 10px" }}>
        Email <b>{email}</b> ·{" "}
        {verified ? <span style={{ color: "var(--ok)", fontWeight: 600 }}>đã xác minh</span>
          : <span style={{ color: "var(--warn)", fontWeight: 600 }}>chưa xác minh</span>}
      </p>
      <h3 style={{ fontSize: 15, margin: "12px 0 6px" }}>Thiết bị đang đăng nhập</h3>
      <QueryState q={sessions} empty="Không có phiên nào.">
        <ul className="rows">
          {sessions.data?.map((s) => (
            <li key={s.id} className="row-between" style={{ gap: 10 }}>
              <span>{s.device}{s.current && <> · <b style={{ color: "var(--accent)" }}>thiết bị này</b></>}</span>
              <span className="inline" style={{ gap: 10 }}>
                <span className="small muted">Hoạt động {timeAgo(s.last_seen)}</span>
                {!s.current && (
                  <button type="button" className="btn-ghost sm pill" onClick={() => revoke.mutate(s.id)}
                          aria-label={`Đăng xuất phiên ${s.device}`}>Đăng xuất</button>
                )}
              </span>
            </li>
          ))}
        </ul>
      </QueryState>
      <div className="inline" style={{ gap: 10, marginTop: 14 }}>
        <button type="button" className="btn-ghost pill" aria-expanded={pwOpen} aria-controls="doi-mat-khau"
                onClick={() => setPwOpen(!pwOpen)}>Đổi mật khẩu</button>
        <button ref={allBtn} type="button" className="btn-ghost pill" aria-expanded={confirm === "all"}
                onClick={() => setConfirm("all")}>Đăng xuất mọi thiết bị</button>
        <button ref={delBtn} type="button" className="btn-ghost pill danger-solid" aria-expanded={confirm === "delete"}
                onClick={() => setConfirm("delete")}>Xoá tài khoản</button>
      </div>
      {pwOpen && (
        <form id="doi-mat-khau" className="stack drop" style={{ marginTop: 12, maxWidth: 420 }}
              onSubmit={(e) => { e.preventDefault(); change.mutate({ old: oldPw, next: newPw }, { onSuccess: () => { setOldPw(""); setNewPw(""); } }); }}>
          <div className="field-group">
            <label htmlFor="pw-old">Mật khẩu hiện tại</label>
            <input id="pw-old" className="field" type="password" autoComplete="current-password" value={oldPw} onChange={(e) => setOldPw(e.target.value)} />
          </div>
          <div className="field-group">
            <label htmlFor="pw-new">Mật khẩu mới</label>
            <input id="pw-new" className="field" type="password" autoComplete="new-password" value={newPw} onChange={(e) => setNewPw(e.target.value)}
                   aria-describedby="pw-new-hint" />
            <span id="pw-new-hint" className="field-hint">Ít nhất 8 ký tự. Các thiết bị khác sẽ bị đăng xuất.</span>
          </div>
          {change.error && <p className="form-error" role="alert">{errText(change.error)}</p>}
          {change.isSuccess && <p className="form-ok" role="status">Đã đổi mật khẩu.</p>}
          <button type="submit" className="btn pill" style={{ alignSelf: "flex-start" }} disabled={!oldPw || !newPw || change.isPending}>
            Lưu mật khẩu mới</button>
        </form>
      )}
      {confirm && (
        <ConfirmBox title={confirm === "all" ? "Đăng xuất khỏi mọi thiết bị, kể cả thiết bị này?" : "Xoá tài khoản của bạn?"}
                    confirmLabel={confirm === "all" ? "Đăng xuất hết" : "Xoá tài khoản"}
                    returnFocus={confirm === "all" ? allBtn : delBtn} busy={logoutAll.isPending || del.isPending}
                    onCancel={() => setConfirm(null)}
                    onConfirm={() => (confirm === "all" ? logoutAll : del).mutateAsync().then(() => navigate("/"), () => undefined)}>
          {confirm === "delete" ? "Dữ liệu cá nhân được giữ 30 ngày để bạn khôi phục, sau đó xoá hẳn." : undefined}
        </ConfirmBox>
      )}
      <p className="hint" style={{ marginTop: 10 }}>Xoá tài khoản: dữ liệu cá nhân được giữ 30 ngày để bạn khôi phục, sau đó xoá hẳn.</p>
    </Section>
  );
}
