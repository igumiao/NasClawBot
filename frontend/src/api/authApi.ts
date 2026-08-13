import { readJson } from "./http";

export type AuthSession = {
  enabled: boolean;
  authenticated: boolean;
  expires_at: string | null;
};

export const authApi = {
  async getSession(signal?: AbortSignal): Promise<AuthSession> {
    const response = await fetch("/auth/session", { signal });
    return readJson<AuthSession>(response);
  },

  async login(code: string, signal?: AbortSignal): Promise<AuthSession> {
    const response = await fetch("/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code }),
      signal,
    });
    return readJson<AuthSession>(response);
  },

  async logout(): Promise<void> {
    const response = await fetch("/auth/logout", { method: "POST" });
    if (!response.ok) {
      await readJson<unknown>(response);
    }
  },
};
