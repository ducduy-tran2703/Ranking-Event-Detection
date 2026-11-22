import { useState, type FormEvent, type ReactNode } from "react";
import { Link } from "react-router";
import { useCurrentUser } from "../../api/accountQueries";
import {
  adminApi, useAdminAction, useAdminFeedback, useAdminOutbox, useAdminTokens, useAdminUsers,
} from "../../api/adminQueries";
import { AUTH_MOCK, type Role } from "../../api/auth";
import { resetMock } from "../../api/mockdb";
import { useRunInfo } from "../../api/queries";
import { ErrorBox, Loading } from "../../components/Status";
import { fmtShort } from "../../lib/format";
import { eventHref } from "../../lib/routes";
import { DEFAULT_SOURCES, sourceName } from "../../lib/sources";
import { useTitle } from "../../lib/useTitle";

const MOCK_LABEL = AUTH_MOCK ? "Giả lập · dữ liệu của trình duyệt này" : null;
const KIND_LABEL: Record<string, string> = {
  wrong_name: "Tên sai", stray_article: "Có bài lạc", duplicate: "Trùng sự kiện", other: "Lý do khác",
};
const ROLES: Role[] = ["user", "editor", "admin"];

function Panel({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  useTitle(`${title} · Quản trị`);
  return (
    <section aria-labelledby={id} className="card pad-sm fade">
      <h1 className="sr-only">Quản trị — {title}</h1>
      <div className="row-between" style={{ alignItems: "baseline", gap: 8 }}>
        <h2 id={id} style={{ fontSize: 16 }}>{title}</h2>
        {MOCK_LABEL && <span className="tag warn" data-testid="mock-label">{MOCK_LABEL}</span>}
      </div>
      <div style={{ marginTop: 10 }}>{children}</div>
    </section>
  );
}

function State({ q, empty, children }: { q: { isPending: boolean; error: unknown; refetch: () => unknown; data?: unknown[] };
  empty: ReactNode; children: ReactNode }) {
  if (q.isPending) return <Loading lines={3} />;
  if (q.error) return <ErrorBox error={q.error} onRetry={() => q.refetch()}
                                hint={AUTH_MOCK ? undefined
                                  : "Máy chủ cần Postgres (DATABASE_URL) đã chạy make db-migrate, và tài khoản có vai trò quản trị."} />;
  if (!q.data?.length) return <div className="empty">{empty}</div>;
  return <>{children}</>;
}

export function FeedbackTab() {
  const q = useAdminFeedback();
  const act = useAdminAction((v: { id: string; status: "resolved" | "rejected" }) => adminApi.resolveFeedback(v.id, v.status));
  return (
    <Panel id="h-fb" title="Báo sai đang chờ">
      <State q={q} empty={<><strong>Chưa có báo sai nào.</strong><span>Mở một sự kiện, bấm “Báo sai” và gửi — báo sai sẽ hiện ở đây.</span></>}>
        <ul className="rows">
          {q.data?.map((r) => (
            <li key={r.id} className="inline" style={{ gap: "10px 16px", alignItems: "flex-start" }}>
              <div style={{ flex: "1 1 420px", minWidth: 0 }}>
                <div className="small muted"><b style={{ color: "var(--accent)" }}>{KIND_LABEL[r.kind] ?? r.kind}</b> · {r.who} · {fmtShort(r.at)}
                  {r.status !== "open" && <> · <span className={`tag ${r.status === "resolved" ? "ok" : "grey"}`}>
                    {r.status === "resolved" ? "Đã xử lý" : "Không sai"}</span></>}</div>
                <Link to={eventHref(r.event_id)} style={{ fontWeight: 600 }}>{r.event_name}</Link>
                {r.note && <p className="small" style={{ marginTop: 4, color: "var(--body-2)" }}>“{r.note}”</p>}
              </div>
              {r.status === "open" && (
                <div className="inline">
                  <button type="button" className="btn sm pill solid" onClick={() => act.mutate({ id: r.id, status: "resolved" })}>Đã xử lý</button>
                  <button type="button" className="btn-ghost sm" onClick={() => act.mutate({ id: r.id, status: "rejected" })}>Không sai</button>
                </div>
              )}
            </li>
          ))}
        </ul>
      </State>
      <p className="hint" style={{ marginTop: 8 }}>Báo sai đã duyệt được lưu làm nhãn người cho phần đánh giá gom cụm và đặt tên.</p>
    </Panel>
  );
}

export function MailTab() {
  const q = useAdminOutbox();
  return (
    <Panel id="h-mail" title="Thư hệ thống (bản demo không gửi thật)">
      <State q={q} empty={<><strong>Chưa có thư nào.</strong><span>Tạo tài khoản hoặc dùng “Quên mật khẩu” để sinh thư xác minh / đặt lại.</span></>}>
        <div className="table-wrap" tabIndex={0} aria-label="Bảng thư hệ thống (cuộn ngang được)">
          <table style={{ minWidth: 680 }}>
            <thead><tr><th scope="col">Lúc</th><th scope="col">Tới</th><th scope="col">Loại thư</th><th scope="col">Link</th></tr></thead>
            <tbody>
              {q.data?.map((m) => {
                const expired = Date.parse(m.expires_at) < Date.now();
                const href = `/${m.kind === "verify" ? "verify-email" : "reset-password"}?token=${m.token}`;
                return (
                  <tr key={m.id}>
                    <td className="tnum">{fmtShort(m.at)}</td>
                    <td>{m.to}</td>
                    <td>{m.kind === "verify" ? "Xác minh email" : "Đặt lại mật khẩu"}</td>
                    <td>{m.used ? <span className="muted">Đã dùng</span> : expired ? <span className="muted">Hết hạn</span>
                      : <Link to={href} style={{ fontWeight: 700 }}>Mở link (hết hạn {fmtShort(m.expires_at)})</Link>}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </State>
    </Panel>
  );
}

export function UsersTab() {
  const q = useAdminUsers();
  const { data: me } = useCurrentUser();
  const setRole = useAdminAction((v: { id: string; role: Role }) => adminApi.setRole(v.id, v.role));
  const unlock = useAdminAction((id: string) => adminApi.unlock(id));
  const [confirmReset, setConfirmReset] = useState(false);
  return (
    <Panel id="h-users" title="Người dùng">
      <State q={q} empty="Chưa có người dùng.">
        <div className="table-wrap" tabIndex={0} aria-label="Bảng người dùng (cuộn ngang được)">
          <table style={{ minWidth: 680 }}>
            <thead><tr><th scope="col">Tên</th><th scope="col">Email</th><th scope="col">Vai trò</th><th scope="col">Trạng thái</th>
              <th scope="col"><span className="sr-only">Thao tác</span></th></tr></thead>
            <tbody>
              {q.data?.map((u) => (
                <tr key={u.id}>
                  <td>{u.display_name}</td>
                  <td>{u.email}</td>
                  <td>
                    <label className="sr-only" htmlFor={`role-${u.id}`}>Vai trò của {u.email}</label>
                    <select id={`role-${u.id}`} className="field" style={{ minHeight: 36, padding: "4px 10px", fontSize: 14 }}
                            value={u.role} disabled={u.id === me?.id} onChange={(e) => setRole.mutate({ id: u.id, role: e.target.value as Role })}>
                      {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
                    </select>
                  </td>
                  <td style={{ color: u.locked_until ? "var(--danger)" : "var(--ok)" }}>
                    {u.locked_until ? `Khoá tạm tới ${fmtShort(u.locked_until).slice(6)} (sai mật khẩu 5 lần)`
                      : u.email_verified ? "Đang hoạt động" : "Chưa xác minh email"}
                  </td>
                  <td>{u.locked_until && <button type="button" className="btn-ghost sm" onClick={() => unlock.mutate(u.id)}>Mở khoá</button>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </State>
      {AUTH_MOCK && (
        <div className="inline" style={{ marginTop: 12 }}>
          {!confirmReset ? (
            <button type="button" className="btn-ghost sm pill danger" onClick={() => setConfirmReset(true)}>Đặt lại dữ liệu giả lập</button>
          ) : (
            <>
              <span className="small">Xoá mọi tài khoản, báo sai, thư, khoá giả lập trên trình duyệt này và đăng xuất?</span>
              <button type="button" className="btn-ghost sm pill danger-solid" onClick={() => { resetMock(); window.location.assign("/"); }}>Xoá hết</button>
              <button type="button" className="btn-ghost sm" onClick={() => setConfirmReset(false)}>Huỷ</button>
            </>
          )}
        </div>
      )}
    </Panel>
  );
}

export function KeysTab() {
  const q = useAdminTokens();
  const run = useRunInfo();
  const sources = run.data?.nguon_bao.length ? run.data.nguon_bao : DEFAULT_SOURCES;
  const [label, setLabel] = useState("");
  const [source, setSource] = useState(sources[0]);
  const [shown, setShown] = useState<string | null>(null);
  const create = useAdminAction((v: { label: string; source: string }) => adminApi.createToken(v.label, v.source));
  const revoke = useAdminAction((id: string) => adminApi.revokeToken(id));
  const submit = (e: FormEvent) => {
    e.preventDefault();
    create.mutate({ label, source }, { onSuccess: (t) => { setShown(t); setLabel(""); } });
  };
  return (
    <Panel id="h-keys" title="Khoá API cho crawler ở máy khác">
      <p className="small" style={{ color: "var(--body-2)" }}>
        Mỗi khoá chỉ được gửi bài của một báo, qua API (phạm vi <code>ingest:write</code>). Khoá chỉ hiện đầy đủ một lần lúc tạo;
        mất thì thu hồi và tạo khoá mới.
      </p>
      {shown && (
        <div className="form-ok" role="status" style={{ marginTop: 10 }}>
          Khoá mới (chỉ hiện lần này): <code data-testid="new-token">{shown}</code>{" "}
          <button type="button" className="link-btn" onClick={() => setShown(null)}>Đã chép, ẩn đi</button>
        </div>
      )}
      <form className="filters" style={{ marginTop: 12 }} onSubmit={submit}>
        <label>Tên khoá<input value={label} onChange={(e) => setLabel(e.target.value)} placeholder="Máy cào Tuổi Trẻ" /></label>
        <label>Báo
          <select value={source} onChange={(e) => setSource(e.target.value)}>
            {sources.map((s) => <option key={s} value={s}>{sourceName(s)}</option>)}
          </select>
        </label>
        <button type="submit" className="btn sm pill solid" disabled={create.isPending}>Tạo khoá</button>
      </form>
      {create.error && <p className="form-error" role="alert" style={{ marginTop: 8 }}>{create.error.message}</p>}
      <div style={{ marginTop: 12 }}>
        <State q={q} empty="Chưa có khoá nào.">
          <ul className="rows">
            {q.data?.map((t) => (
              <li key={t.id} className="row-between">
                <span><b>{t.label}</b> · {sourceName(t.source)} · <code>{t.prefix}…</code> · tạo {fmtShort(t.created_at)}</span>
                {t.revoked ? <span className="tag grey">Đã thu hồi</span>
                  : <button type="button" className="btn-ghost sm pill danger" onClick={() => revoke.mutate(t.id)}
                            aria-label={`Thu hồi khoá ${t.label}`}>Thu hồi</button>}
              </li>
            ))}
          </ul>
        </State>
      </div>
    </Panel>
  );
}
