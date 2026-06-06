export const ACTIVE_AGENT_SESSION_KEY = "nasclawbot-active-agent-session";

export function readStoredAgentSessionId(): string | null {
  try {
    return globalThis.sessionStorage?.getItem(ACTIVE_AGENT_SESSION_KEY) || null;
  } catch {
    return null;
  }
}

export function persistAgentSessionId(sessionId: string | null): void {
  try {
    if (sessionId) {
      globalThis.sessionStorage?.setItem(ACTIVE_AGENT_SESSION_KEY, sessionId);
      return;
    }
    globalThis.sessionStorage?.removeItem(ACTIVE_AGENT_SESSION_KEY);
  } catch {
    // The chat still works when browser storage is unavailable.
  }
}
