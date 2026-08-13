import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AUTH_REQUIRED_EVENT } from "../api/apiFetch";
import { App } from "./App";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function unauthenticatedSession() {
  return { enabled: true, authenticated: false, expires_at: null };
}

function authenticatedSession() {
  return {
    enabled: true,
    authenticated: true,
    expires_at: new Date(Date.now() + 3_600_000).toISOString(),
  };
}

function workspaceResponse(url: string): Response {
  if (url === "/chat/agent/sessions") return jsonResponse({ sessions: [] });
  if (url === "/health") return jsonResponse({ status: "ok" });
  if (url.startsWith("/task-events")) return jsonResponse({ events: [] });
  throw new Error(`Unexpected workspace fetch: ${url}`);
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("experience authentication gate", () => {
  it("shows the five-digit login form when no session exists", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(jsonResponse(unauthenticatedSession()));

    render(<App />);

    expect(await screen.findByRole("heading", { name: "体验 NasClawBot" })).toBeInTheDocument();
    expect(screen.getByLabelText("体验代码")).toHaveAttribute("maxlength", "5");
    expect(screen.getByRole("button", { name: "进入体验" })).toBeDisabled();
  });

  it("submits a sanitized code and enters the workspace", async () => {
    const user = userEvent.setup();
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      if (url === "/auth/session") return Promise.resolve(jsonResponse(unauthenticatedSession()));
      if (url === "/auth/login") {
        expect(init?.body).toBe(JSON.stringify({ code: "12345" }));
        return Promise.resolve(jsonResponse(authenticatedSession()));
      }
      return Promise.resolve(workspaceResponse(url));
    });

    render(<App />);
    const input = await screen.findByLabelText("体验代码");
    await user.type(input, "12a3456");
    expect(input).toHaveValue("12345");
    await user.click(screen.getByRole("button", { name: "进入体验" }));

    expect(await screen.findByText("NasClawBot")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "退出体验" })).toBeInTheDocument();
    expect(fetchSpy).toHaveBeenCalledWith(
      "/auth/login",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("shows a useful error for an invalid code", async () => {
    const user = userEvent.setup();
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      if (String(input) === "/auth/session") {
        return Promise.resolve(jsonResponse(unauthenticatedSession()));
      }
      return Promise.resolve(jsonResponse({ detail: "Invalid experience code." }, 401));
    });

    render(<App />);
    await user.type(await screen.findByLabelText("体验代码"), "00000");
    await user.click(screen.getByRole("button", { name: "进入体验" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("体验代码不正确");
  });

  it("returns to login when a protected request reports an expired session", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url === "/auth/session") return Promise.resolve(jsonResponse(authenticatedSession()));
      return Promise.resolve(workspaceResponse(url));
    });

    render(<App />);
    expect(await screen.findByText("NasClawBot")).toBeInTheDocument();

    globalThis.dispatchEvent(new Event(AUTH_REQUIRED_EVENT));

    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "体验 NasClawBot" })).toBeInTheDocument();
    });
    expect(screen.getByRole("alert")).toHaveTextContent("登录已失效");
  });

  it("logs out from the workspace header", async () => {
    const user = userEvent.setup();
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url === "/auth/session") return Promise.resolve(jsonResponse(authenticatedSession()));
      if (url === "/auth/logout") return Promise.resolve(new Response(null, { status: 204 }));
      return Promise.resolve(workspaceResponse(url));
    });

    render(<App />);
    await user.click(await screen.findByRole("button", { name: "退出体验" }));

    expect(await screen.findByRole("heading", { name: "体验 NasClawBot" })).toBeInTheDocument();
    expect(fetchSpy).toHaveBeenCalledWith("/auth/logout", { method: "POST" });
  });
});
