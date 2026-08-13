import { useCallback, useEffect, useState } from "react";
import { AUTH_REQUIRED_EVENT } from "../api/apiFetch";
import { authApi, type AuthSession } from "../api/authApi";
import { ExperienceLogin } from "../components/auth/ExperienceLogin";
import { AppShell } from "./AppShell";
import "./theme.css";

type AuthState = "checking" | "authenticated" | "unauthenticated";

export function App() {
  const [authState, setAuthState] = useState<AuthState>("checking");
  const [authEnabled, setAuthEnabled] = useState(false);
  const [expiresAt, setExpiresAt] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const applySession = useCallback((session: AuthSession) => {
    setAuthEnabled(session.enabled);
    setExpiresAt(session.expires_at);
    setAuthState(session.authenticated ? "authenticated" : "unauthenticated");
  }, []);

  const checkSession = useCallback(async (signal?: AbortSignal) => {
    try {
      applySession(await authApi.getSession(signal));
    } catch (requestError) {
      if (signal?.aborted) return;
      setAuthState("unauthenticated");
      setError("暂时无法连接服务，请稍后重试。");
    }
  }, [applySession]);

  useEffect(() => {
    const controller = new AbortController();
    void checkSession(controller.signal);
    return () => controller.abort();
  }, [checkSession]);

  useEffect(() => {
    const requireLogin = () => {
      setAuthState("unauthenticated");
      setExpiresAt(null);
      setError("体验登录已失效，请重新输入体验代码。");
    };
    globalThis.addEventListener(AUTH_REQUIRED_EVENT, requireLogin);
    return () => globalThis.removeEventListener(AUTH_REQUIRED_EVENT, requireLogin);
  }, []);

  useEffect(() => {
    if (authState !== "authenticated" || !expiresAt) return;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const checkExpiry = () => {
      const remaining = new Date(expiresAt).getTime() - Date.now();
      if (remaining <= 0) {
        setAuthState("unauthenticated");
        setExpiresAt(null);
        return;
      }
      // Browser timers overflow above roughly 24.8 days. Re-check long local
      // sessions daily instead of scheduling the entire 180-day interval.
      timer = globalThis.setTimeout(checkExpiry, Math.min(remaining, 86_400_000));
    };
    checkExpiry();
    return () => {
      if (timer !== undefined) globalThis.clearTimeout(timer);
    };
  }, [authState, expiresAt]);

  useEffect(() => {
    const handleVisibility = () => {
      if (document.visibilityState === "visible" && authState === "authenticated") {
        void checkSession();
      }
    };
    document.addEventListener("visibilitychange", handleVisibility);
    return () => document.removeEventListener("visibilitychange", handleVisibility);
  }, [authState, checkSession]);

  const handleLogin = useCallback(async (code: string) => {
    setIsSubmitting(true);
    setError(null);
    try {
      applySession(await authApi.login(code));
    } catch (requestError) {
      const status = (requestError as { status?: number }).status;
      if (status === 429) {
        setError("尝试次数过多，请稍后再试。");
      } else if (status === 401 || status === 422) {
        setError("体验代码不正确，请重新输入。");
      } else {
        setError("暂时无法验证体验代码，请稍后重试。");
      }
    } finally {
      setIsSubmitting(false);
    }
  }, [applySession]);

  const handleLogout = useCallback(async () => {
    try {
      await authApi.logout();
    } finally {
      setAuthState("unauthenticated");
      setExpiresAt(null);
      setError(null);
    }
  }, []);

  if (authState === "checking") {
    return (
      <main className="experience-login-shell" aria-label="正在检查体验登录">
        <div className="experience-auth-loading">
          <span className="experience-auth-loading-mark" />
          <span>正在连接 NasClawBot…</span>
        </div>
      </main>
    );
  }

  if (authState === "unauthenticated") {
    return <ExperienceLogin isSubmitting={isSubmitting} error={error} onSubmit={handleLogin} />;
  }

  return <AppShell showLogout={authEnabled} onLogout={handleLogout} />;
}
