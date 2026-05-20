type HttpError = Error & {
  status?: number;
  statusText?: string;
  detail?: unknown;
};

export async function readJson<T>(response: Response): Promise<T> {
  let body: unknown;
  try {
    body = await response.json();
  } catch (error) {
    if (response.ok) {
      throw error;
    }
  }

  if (!response.ok) {
    const statusText = response.statusText || `HTTP ${response.status}`;
    const detail =
      body && typeof body === "object" && "detail" in body
        ? (body as { detail: unknown }).detail
        : undefined;
    const message = typeof detail === "string" && detail ? `${statusText}: ${detail}` : statusText;
    const error = new Error(message) as HttpError;
    error.status = response.status;
    error.statusText = response.statusText;
    error.detail = detail;
    throw error;
  }
  return body as T;
}

export async function postJson<T>(url: string, body: unknown, signal?: AbortSignal): Promise<T> {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal
  });
  return readJson<T>(response);
}
