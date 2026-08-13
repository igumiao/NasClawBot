import { afterEach, expect, it, vi } from "vitest";
import { apiFetch, AUTH_REQUIRED_EVENT } from "./apiFetch";

afterEach(() => {
  vi.restoreAllMocks();
});

it("announces when a protected API request returns 401", async () => {
  const listener = vi.fn();
  globalThis.addEventListener(AUTH_REQUIRED_EVENT, listener);
  vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(null, { status: 401 }));

  try {
    const response = await apiFetch("/protected");
    expect(response.status).toBe(401);
    expect(listener).toHaveBeenCalledOnce();
  } finally {
    globalThis.removeEventListener(AUTH_REQUIRED_EVENT, listener);
  }
});
