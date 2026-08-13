export const AUTH_REQUIRED_EVENT = "nasclawbot:auth-required";

export async function apiFetch(
  input: RequestInfo | URL,
  init?: RequestInit,
): Promise<Response> {
  const response = await fetch(input, init);
  if (response.status === 401) {
    globalThis.dispatchEvent?.(new Event(AUTH_REQUIRED_EVENT));
  }
  return response;
}
