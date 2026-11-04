// Hook React Query cho khu tài khoản / của tôi / quản trị. Trang chỉ dùng các hook này (không gọi adapter trực tiếp).
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { authApi, type User } from "./auth";
import { meApi, type Snapshot } from "./me";
import type { Role } from "./mockdb";

const ME = ["auth", "me"] as const;

/** Người đang đăng nhập (null = khách). */
export function useCurrentUser() {
  return useQuery({ queryKey: ME, queryFn: () => authApi.me(), staleTime: 60_000, retry: false });
}

/** Sau đăng nhập/đăng xuất: đặt lại người dùng và bỏ mọi dữ liệu "của tôi"/quản trị cũ. */
function useAuthReset() {
  const qc = useQueryClient();
  return (user: User | null) => {
    qc.setQueryData(ME, user);
    qc.removeQueries({ queryKey: ["me"] });
    qc.removeQueries({ queryKey: ["admin"] });
  };
}

export function useLogin() {
  const reset = useAuthReset();
  return useMutation({
    mutationFn: (v: { email: string; password: string; remember: boolean }) => authApi.login(v.email, v.password, v.remember),
    onSuccess: (u) => reset(u),
  });
}

export function useRegister() {
  const qc = useQueryClient();
  const reset = useAuthReset();
  return useMutation({
    mutationFn: (v: { display_name: string; email: string; password: string; role?: Role }) => authApi.register(v),
    onSuccess: async () => reset(await qc.fetchQuery({ queryKey: ME, queryFn: () => authApi.me() })),
  });
}

export function useLogout(all = false) {
  const reset = useAuthReset();
  return useMutation({
    mutationFn: () => (all ? authApi.logoutAll() : authApi.logout()),
    onSuccess: () => reset(null),
  });
}

export const useForgotPassword = () => useMutation({ mutationFn: (email: string) => authApi.forgotPassword(email) });
export function useResetPassword() {
  const reset = useAuthReset();
  return useMutation({
    mutationFn: (v: { token: string; password: string }) => authApi.resetPassword(v.token, v.password),
    onSuccess: async () => reset(await authApi.me()),
  });
}
export function useVerifyEmail() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: (token: string) => authApi.verifyEmail(token), onSuccess: () => qc.invalidateQueries({ queryKey: ME }) });
}
export const useChangePassword = () =>
  useMutation({ mutationFn: (v: { old: string; next: string }) => authApi.changePassword(v.old, v.next) });

// ------------------------------------------------------------------ của tôi
const enabledFor = (user: User | null | undefined) => ({ enabled: !!user });

export function useNotifications() {
  const { data: user } = useCurrentUser();
  return useQuery({ queryKey: ["me", user?.id, "notifications"], queryFn: () => meApi.notifications(), ...enabledFor(user) });
}
export function useFollows() {
  const { data: user } = useCurrentUser();
  return useQuery({ queryKey: ["me", user?.id, "follows"], queryFn: () => meApi.follows(), ...enabledFor(user) });
}
export function useBookmarks() {
  const { data: user } = useCurrentUser();
  return useQuery({ queryKey: ["me", user?.id, "bookmarks"], queryFn: () => meApi.bookmarks(), ...enabledFor(user) });
}
export function useSubscriptions() {
  const { data: user } = useCurrentUser();
  return useQuery({ queryKey: ["me", user?.id, "subscriptions"], queryFn: () => meApi.subscriptions(), ...enabledFor(user) });
}
export function useSettings() {
  const { data: user } = useCurrentUser();
  return useQuery({ queryKey: ["me", user?.id, "settings"], queryFn: () => meApi.settings(), ...enabledFor(user) });
}
export function useSessions() {
  const { data: user } = useCurrentUser();
  return useQuery({ queryKey: ["me", user?.id, "sessions"], queryFn: () => meApi.sessions(), ...enabledFor(user) });
}

/** Mọi thao tác "của tôi": gọi adapter rồi làm mới nhóm dữ liệu "me". */
export function useMeAction<V>(fn: (v: V) => Promise<unknown>) {
  const qc = useQueryClient();
  return useMutation({ mutationFn: fn, onSettled: () => qc.invalidateQueries({ queryKey: ["me"] }) });
}

export const useToggleFollow = () =>
  useMeAction((v: { ev: Snapshot; on: boolean }) => (v.on ? meApi.follow(v.ev) : meApi.unfollow(v.ev.event_id)));
export const useToggleBookmark = () =>
  useMeAction((v: { ev: Snapshot; on: boolean }) => (v.on ? meApi.bookmark(v.ev) : meApi.unbookmark(v.ev.event_id)));

export function useDeleteAccount() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => meApi.deleteAccount(),
    onSuccess: () => { qc.setQueryData(ME, null); qc.removeQueries({ queryKey: ["me"] }); },
  });
}

export const useSubmitFeedback = () =>
  useMutation({
    mutationFn: (v: { eventId: string; kind: Parameters<typeof meApi.feedback>[1]["kind"]; note: string; event_name: string }) =>
      meApi.feedback(v.eventId, { kind: v.kind, note: v.note, event_name: v.event_name }),
  });

export { meApi };
