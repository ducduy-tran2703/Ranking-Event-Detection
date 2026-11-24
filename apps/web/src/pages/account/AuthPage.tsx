import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import {
  useCurrentUser, useForgotPassword, useLogin, useLogout, useRegister, useResetPassword, useVerifyEmail,
} from "../../api/accountQueries";
import { AUTH_MOCK, AuthError, GENERIC_LOGIN_ERROR, passwordProblem, type Role } from "../../api/auth";
import { DEMO_ACCOUNTS, DEMO_PASSWORD } from "../../api/mockdb";
import { IconBell, IconCheck, IconMail } from "../../components/Icons";
import { safeNext } from "../../lib/routes";
import { useTitle } from "../../lib/useTitle";

export type AuthMode = "login" | "register" | "forgot" | "reset" | "verify";
const TITLES: Record<AuthMode, string> = {
  login: "Đăng nhập", register: "Tạo tài khoản", forgot: "Quên mật khẩu", reset: "Đặt lại mật khẩu", verify: "Xác minh email",
};
const errText = (e: unknown) => (e instanceof AuthError ? e.message : "Có lỗi, thử lại sau.");

/** /login, /register, /forgot-password, /reset-password?token=, /verify-email?token= (thiết kế Login). */
export function AuthPage({ mode }: { mode: AuthMode }) {
  useTitle(TITLES[mode]);
  const [params] = useSearchParams();
  const next = params.get("next");
  const tabs = mode === "login" || mode === "register";
  const q = next ? `?next=${encodeURIComponent(next)}` : "";
  return (
    <div className="auth-wrap">
      <div className="auth-col">
        {tabs && (
          <nav className="pill-tabs" aria-label="Tài khoản">
            <Link to={`/login${q}`} className={mode === "login" ? "active" : undefined} aria-current={mode === "login" ? "page" : undefined}>
              Đăng nhập</Link>
            <Link to={`/register${q}`} className={mode === "register" ? "active" : undefined}
                  aria-current={mode === "register" ? "page" : undefined}>Tạo tài khoản</Link>
          </nav>
        )}
        <div className="auth-card">
          {mode === "login" && <LoginForm next={next} />}
          {mode === "register" && <RegisterForm next={next} />}
          {mode === "forgot" && <ForgotForm />}
          {mode === "reset" && <ResetForm token={params.get("token") ?? ""} />}
          {mode === "verify" && <Verify token={params.get("token") ?? ""} />}
        </div>
        <p className="demo-box" role="note">
          Bản demo chưa gửi email thật: link xác minh và link đặt lại mật khẩu được ghi vào log máy chủ và trang Quản trị
          {AUTH_MOCK ? " (bản xem trước: Quản trị › Thư hệ thống)." : "."}
        </p>
      </div>
      <section aria-labelledby="h-why" className="auth-promo rise">
        <h2 id="h-why">Theo dõi sự kiện, không bỏ lỡ diễn biến</h2>
        <ul>
          <li><IconCheck />Lưu sự kiện để đọc lại</li>
          <li><IconCheck />Nhận thông báo khi sự kiện có thêm bài mới</li>
          <li><IconCheck />Đăng ký chủ đề: người, địa danh, chuyên mục</li>
        </ul>
        <div className="float-note" aria-hidden="true">
          <span style={{ width: 36, height: 36, background: "var(--soft-2)", color: "var(--accent)",
                         display: "grid", placeItems: "center", flex: "none" }}><IconBell /></span>
          <span><b>Sự kiện bạn theo dõi · vừa xong</b>Có thêm bài mới về sự kiện bạn đang theo dõi</span>
        </div>
      </section>

    </div>
  );
}

function AlreadyIn({ next }: { next: string | null }) {
  const { data: user } = useCurrentUser();
  const logout = useLogout();
  if (!user) return null;
  return (
    <div className="form-ok" role="status">
      Bạn đang đăng nhập bằng <b>{user.email}</b>.{" "}
      <Link to={safeNext(next)}>Tiếp tục</Link> ·{" "}
      <button type="button" className="link-btn" style={{ padding: 0 }} onClick={() => logout.mutate()}>Đăng xuất</button>
    </div>
  );
}

function LoginForm({ next }: { next: string | null }) {
  const navigate = useNavigate();
  const login = useLogin();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [remember, setRemember] = useState(true);
  const pwRef = useRef<HTMLInputElement>(null);
  const submit = (e: FormEvent) => {
    e.preventDefault();
    login.mutate({ email, password, remember }, { onSuccess: () => navigate(safeNext(next), { replace: true }) });
  };
  const fill = (em: string) => { setEmail(em); setPassword(DEMO_PASSWORD); pwRef.current?.focus(); };
  return (
    <form className="fade" onSubmit={submit} noValidate aria-labelledby="h-login">
      <h1 id="h-login">Chào mừng trở lại</h1>
      <AlreadyIn next={next} />
      {login.error && (
        <p role="alert" className="form-error fade" data-testid="login-error">
          {login.error instanceof AuthError && login.error.code !== "server" ? GENERIC_LOGIN_ERROR : errText(login.error)}
        </p>
      )}
      <div className="field-group">
        <label htmlFor="login-email">Email</label>
        <input id="login-email" className="field" type="email" autoComplete="email" placeholder="ban@example.com" required
               value={email} onChange={(e) => setEmail(e.target.value)} />
      </div>
      <div className="field-group">
        <div className="row-between" style={{ alignItems: "baseline" }}>
          <label htmlFor="login-password">Mật khẩu</label>
          <Link to="/forgot-password" className="small" style={{ fontWeight: 600, padding: 4 }}>Quên mật khẩu?</Link>
        </div>
        <input id="login-password" ref={pwRef} className="field" type="password" autoComplete="current-password" required
               value={password} onChange={(e) => setPassword(e.target.value)} />
      </div>
      <label className="check">
        <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} />
        Giữ đăng nhập trên thiết bị này (30 ngày)
      </label>
      <button type="submit" className="btn" disabled={login.isPending || !email || !password}>
        {login.isPending ? "Đang đăng nhập…" : "Đăng nhập"}
      </button>
      {AUTH_MOCK && (
        <div className="demo-box" data-testid="demo-accounts">
          <b>Tài khoản mẫu của bản xem trước</b> (mật khẩu <code>{DEMO_PASSWORD}</code>):
          <ul>
            {DEMO_ACCOUNTS.map((a) => (
              <li key={a.email}>
                <code>{a.email}</code> — vai trò <b>{a.role}</b>{" "}
                <button type="button" className="link-btn" onClick={() => fill(a.email)}
                        aria-label={`Điền sẵn tài khoản ${a.email}`}>Điền sẵn</button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </form>
  );
}

function RegisterForm({ next }: { next: string | null }) {
  const reg = useRegister();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [agree, setAgree] = useState(false);
  const [role, setRole] = useState<Role>("user");
  const [touched, setTouched] = useState(false);
  const pwProblem = password ? passwordProblem(password) : null;
  const submit = (e: FormEvent) => {
    e.preventDefault();
    setTouched(true);
    if (!agree || pwProblem || !name.trim() || !email.trim()) return;
    reg.mutate({ display_name: name, email, password, role: AUTH_MOCK ? role : undefined });
  };
  if (reg.isSuccess) {
    // Câu chữ trung tính, không cho biết email đã có tài khoản hay chưa (máy chủ luôn trả 204, không cookie). Đăng ký không
    // đăng nhập: luôn mời đăng nhập (giữ ?next=).
    return (
      <div className="done fade" role="status">
        <span className="mail-icon" aria-hidden="true"><IconMail /></span>
        <h1>Kiểm tra email của bạn</h1>
        <p>Nếu email này chưa được dùng cho tài khoản nào, bạn sẽ nhận thư xác minh trong vài phút (link có hiệu lực 24 giờ).
          Nếu email đã có tài khoản, hãy đăng nhập hoặc dùng “Quên mật khẩu”.</p>
        <p>Tài khoản dùng được ngay: hãy đăng nhập bằng email và mật khẩu vừa tạo (chưa xác minh email vẫn đăng nhập được).</p>
        <Link to={`/login${next ? `?next=${encodeURIComponent(next)}` : ""}`} className="btn">Đăng nhập</Link>
      </div>
    );
  }
  return (
    <form className="fade" onSubmit={submit} noValidate aria-labelledby="h-register">
      <h1 id="h-register">Tạo tài khoản</h1>
      {reg.error && <p role="alert" className="form-error">{errText(reg.error)}</p>}
      <div className="field-group">
        <label htmlFor="reg-name">Tên hiển thị</label>
        <input id="reg-name" className="field" autoComplete="name" required value={name} onChange={(e) => setName(e.target.value)}
               aria-invalid={touched && !name.trim()} />
      </div>
      <div className="field-group">
        <label htmlFor="reg-email">Email</label>
        <input id="reg-email" className="field" type="email" autoComplete="email" required value={email}
               onChange={(e) => setEmail(e.target.value)} aria-invalid={touched && !email.trim()} />
      </div>
      <div className="field-group">
        <label htmlFor="reg-password">Mật khẩu</label>
        <input id="reg-password" className="field" type="password" autoComplete="new-password" required value={password}
               onChange={(e) => setPassword(e.target.value)} aria-describedby="reg-password-hint" aria-invalid={!!pwProblem} />
        <span id="reg-password-hint" className={pwProblem ? "field-error" : "field-hint"}>
          {pwProblem ?? "Ít nhất 8 ký tự, không dùng mật khẩu phổ biến như 12345678."}
        </span>
      </div>
      {AUTH_MOCK && (
        <div className="field-group">
          <label htmlFor="reg-role">Vai trò (chỉ có ở bản xem trước)</label>
          <select id="reg-role" className="field" value={role} onChange={(e) => setRole(e.target.value as Role)}>
            <option value="user">Người dùng</option>
            <option value="editor">Biên tập viên</option>
            <option value="admin">Quản trị viên</option>
          </select>
        </div>
      )}
      <label className="check">
        <input type="checkbox" checked={agree} onChange={(e) => setAgree(e.target.checked)} aria-describedby="reg-agree-err" />
        Tôi đồng ý với điều khoản sử dụng và cách xử lý dữ liệu cá nhân
      </label>
      {touched && !agree && <span id="reg-agree-err" className="field-error" role="alert">Cần đồng ý điều khoản để tạo tài khoản.</span>}
      <button type="submit" className="btn" disabled={reg.isPending}>{reg.isPending ? "Đang tạo…" : "Tạo tài khoản"}</button>
    </form>
  );
}

function ForgotForm() {
  const forgot = useForgotPassword();
  const [email, setEmail] = useState("");
  if (forgot.isSuccess) {
    return (
      <div className="done fade" role="status">
        <h1>Đã gửi yêu cầu</h1>
        <p>Nếu email này có tài khoản, bạn sẽ nhận được link đặt lại mật khẩu trong vài phút. Đặt mật khẩu mới sẽ đăng xuất mọi thiết bị khác.</p>
        <Link to="/login" className="btn-ghost">Quay lại đăng nhập</Link>
      </div>
    );
  }
  return (
    <form className="fade" onSubmit={(e) => { e.preventDefault(); forgot.mutate(email); }} aria-labelledby="h-forgot">
      <h1 id="h-forgot">Quên mật khẩu</h1>
      <p style={{ fontSize: 14.5, color: "var(--body-2)" }}>Nhập email đã đăng ký. Chúng tôi gửi link đặt lại mật khẩu, có hiệu lực 1 giờ.</p>
      {forgot.error && <p role="alert" className="form-error">{errText(forgot.error)}</p>}
      <div className="field-group">
        <label htmlFor="forgot-email">Email</label>
        <input id="forgot-email" className="field" type="email" autoComplete="email" required value={email}
               onChange={(e) => setEmail(e.target.value)} />
      </div>
      <button type="submit" className="btn" disabled={forgot.isPending || !email}>
        {forgot.isPending ? "Đang gửi…" : "Gửi link đặt lại"}
      </button>
      <Link to="/login" className="link-btn" style={{ textAlign: "center", color: "var(--muted)" }}>← Quay lại đăng nhập</Link>
    </form>
  );
}

function ResetForm({ token }: { token: string }) {
  const reset = useResetPassword();
  const [pw, setPw] = useState("");
  const [pw2, setPw2] = useState("");
  const problem = pw ? passwordProblem(pw) : null;
  const mismatch = pw2 && pw !== pw2;
  if (!token) {
    return <div className="done"><h1>Thiếu mã đặt lại</h1><p>Link không đầy đủ. Hãy mở lại link trong email, hoặc <Link to="/forgot-password">yêu cầu link mới</Link>.</p></div>;
  }
  if (reset.isSuccess) {
    return (
      <div className="done fade" role="status">
        <h1>Đã đặt mật khẩu mới</h1>
        <p>Mọi thiết bị đã bị đăng xuất. Đăng nhập lại bằng mật khẩu mới.</p>
        <Link to="/login" className="btn">Đăng nhập</Link>
      </div>
    );
  }
  return (
    <form className="fade" onSubmit={(e) => { e.preventDefault(); if (!problem && !mismatch) reset.mutate({ token, password: pw }); }}
          aria-labelledby="h-reset">
      <h1 id="h-reset">Đặt lại mật khẩu</h1>
      {reset.error && <p role="alert" className="form-error">{errText(reset.error)}</p>}
      <div className="field-group">
        <label htmlFor="reset-pw">Mật khẩu mới</label>
        <input id="reset-pw" className="field" type="password" autoComplete="new-password" value={pw} onChange={(e) => setPw(e.target.value)}
               aria-describedby="reset-pw-hint" aria-invalid={!!problem} />
        <span id="reset-pw-hint" className={problem ? "field-error" : "field-hint"}>{problem ?? "Ít nhất 8 ký tự."}</span>
      </div>
      <div className="field-group">
        <label htmlFor="reset-pw2">Nhập lại mật khẩu mới</label>
        <input id="reset-pw2" className="field" type="password" autoComplete="new-password" value={pw2} onChange={(e) => setPw2(e.target.value)}
               aria-invalid={!!mismatch} aria-describedby="reset-pw2-hint" />
        {mismatch && <span id="reset-pw2-hint" className="field-error">Hai mật khẩu chưa khớp.</span>}
      </div>
      <button type="submit" className="btn" disabled={reset.isPending || !pw || !!problem || !!mismatch}>
        {reset.isPending ? "Đang lưu…" : "Đặt mật khẩu mới"}
      </button>
    </form>
  );
}

function Verify({ token }: { token: string }) {
  const verify = useVerifyEmail();
  const started = useRef(false);
  useEffect(() => {
    if (token && !started.current) { started.current = true; verify.mutate(token); }
  }, [token, verify]);
  return (
    <div className="done" role="status" aria-live="polite">
      <h1>Xác minh email</h1>
      {!token && <p>Link không đầy đủ. Hãy mở lại link trong email.</p>}
      {verify.isPending && <p>Đang xác minh…</p>}
      {verify.isSuccess && <><p className="form-ok">Email đã được xác minh. Cảm ơn bạn!</p><Link to="/me" className="btn">Vào trang của tôi</Link></>}
      {verify.error && <p className="form-error">{errText(verify.error)}</p>}
    </div>
  );
}
