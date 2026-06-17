import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" }
  });
}

function agentSessionDetail(sessionId: string) {
  return {
    session_id: sessionId,
    created_at: "2026-06-05T10:00:00",
    saved_at: "2026-06-05T10:01:00",
    messages: [
      { role: "user", content: "stored question", timestamp: "2026-06-05T10:00:00", metadata: {} },
      { role: "assistant", content: "stored answer", timestamp: "2026-06-05T10:01:00", metadata: {} }
    ],
    archives: [],
    metadata: { pending_approvals: [] }
  };
}

function agentSessionList() {
  return {
    sessions: [
      {
        session_id: "session-a",
        created_at: "2026-06-05T10:00:00",
        saved_at: "2026-06-05T10:10:00",
        message_count: 4,
        archive_count: 0,
        metadata: { title: "媒体库 Agent 设计" }
      },
      {
        session_id: "session-b",
        created_at: "2026-06-05T09:00:00",
        saved_at: "2026-06-05T09:10:00",
        message_count: 2,
        archive_count: 0,
        metadata: { title: "NAS 下载系统规划" }
      }
    ]
  };
}

function agentSessionListWithTitle(title: string) {
  return {
    sessions: [
      {
        session_id: "session-a",
        created_at: "2026-06-05T10:00:00",
        saved_at: "2026-06-05T10:10:00",
        message_count: 4,
        archive_count: 0,
        metadata: { title }
      }
    ]
  };
}

afterEach(() => {
  vi.restoreAllMocks();
  sessionStorage.clear();
  localStorage.clear();
});

describe("AppShell", () => {
  it("renders the conversation sidebar and chat tab by default", () => {
    render(<App />);

    expect(screen.getByText("NasClawBot")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "新会话" })).toBeEnabled();
    expect(screen.getByRole("tab", { name: "Chat" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByText("输入媒体需求")).toBeInTheDocument();
  });

  it("restores the active Agent session from sessionStorage", async () => {
    sessionStorage.setItem("nasclawbot-active-agent-session", "session/restore");
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url === "/chat/agent/sessions/session%2Frestore") {
        return Promise.resolve(jsonResponse(agentSessionDetail("session/restore")));
      }
      if (url === "/chat/agent/sessions") {
        return Promise.resolve(jsonResponse(agentSessionList()));
      }
      if (url === "/health") {
        return Promise.resolve(jsonResponse({ status: "ok" }));
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });

    render(<App />);

    expect(await screen.findByText("stored answer")).toBeInTheDocument();
    expect(screen.getByText("stored question")).toBeInTheDocument();
  });

  it("clears the persisted active session when starting a new conversation", async () => {
    const user = userEvent.setup();
    sessionStorage.setItem("nasclawbot-active-agent-session", "session/restore");
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url === "/chat/agent/sessions/session%2Frestore") {
        return Promise.resolve(jsonResponse(agentSessionDetail("session/restore")));
      }
      if (url === "/chat/agent/sessions") {
        return Promise.resolve(jsonResponse(agentSessionList()));
      }
      if (url === "/health") {
        return Promise.resolve(jsonResponse({ status: "ok" }));
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });

    render(<App />);

    await user.click(screen.getByRole("button", { name: "新会话" }));

    await waitFor(() => {
      expect(sessionStorage.getItem("nasclawbot-active-agent-session")).toBeNull();
    });
    expect(screen.getByText("输入媒体需求")).toBeInTheDocument();
  });

  it("renders the historical session list and switches sessions from the sidebar", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url === "/chat/agent/sessions") {
        return Promise.resolve(jsonResponse(agentSessionList()));
      }
      if (url === "/chat/agent/sessions/session-b") {
        return Promise.resolve(jsonResponse({
          ...agentSessionDetail("session-b"),
          messages: [
            { role: "user", content: "下载规划", timestamp: "2026-06-05T09:00:00", metadata: {} },
            { role: "assistant", content: "NAS 下载规划详情。", timestamp: "2026-06-05T09:01:00", metadata: {} }
          ]
        }));
      }
      if (url === "/health") {
        return Promise.resolve(jsonResponse({ status: "ok" }));
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });

    render(<App />);

    expect(await screen.findByRole("button", { name: "媒体库 Agent 设计" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "NAS 下载系统规划" }));

    expect(await screen.findByText("NAS 下载规划详情。")).toBeInTheDocument();
    expect(sessionStorage.getItem("nasclawbot-active-agent-session")).toBe("session-b");
    expect(fetchMock).toHaveBeenCalledWith(
      "/chat/agent/sessions/session-b",
      expect.objectContaining({ signal: undefined }),
    );
  });

  it("persists the collapsed sidebar state in localStorage", async () => {
    const user = userEvent.setup();
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url === "/chat/agent/sessions") {
        return Promise.resolve(jsonResponse({ sessions: [] }));
      }
      if (url === "/health") {
        return Promise.resolve(jsonResponse({ status: "ok" }));
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });

    render(<App />);

    await user.click(screen.getByRole("button", { name: "收起侧边栏" }));

    expect(localStorage.getItem("nasclawbot-sidebar-collapsed")).toBe("true");
    expect(screen.getByRole("button", { name: "展开侧边栏" })).toBeInTheDocument();
  });

  it("renames a historical session from the sidebar menu", async () => {
    const user = userEvent.setup();
    let currentTitle = "媒体库 Agent 设计";
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      if (url === "/chat/agent/sessions" && !init?.method) {
        return Promise.resolve(jsonResponse(agentSessionListWithTitle(currentTitle)));
      }
      if (url === "/chat/agent/sessions/session-a" && init?.method === "PATCH") {
        currentTitle = JSON.parse(String(init.body)).title;
        return Promise.resolve(jsonResponse({
          ...agentSessionDetail("session-a"),
          metadata: { title: currentTitle }
        }));
      }
      if (url === "/health") {
        return Promise.resolve(jsonResponse({ status: "ok" }));
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });

    render(<App />);

    expect(await screen.findByRole("button", { name: "媒体库 Agent 设计" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "更多操作：媒体库 Agent 设计" }));
    await user.click(screen.getByRole("menuitem", { name: "重命名" }));

    const input = screen.getByRole("textbox", { name: "重命名会话" });
    await user.clear(input);
    await user.type(input, "Pi Agent 框架分析");
    await user.keyboard("{Enter}");

    expect(await screen.findByRole("button", { name: "Pi Agent 框架分析" })).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      "/chat/agent/sessions/session-a",
      expect.objectContaining({
        method: "PATCH",
        body: JSON.stringify({ title: "Pi Agent 框架分析" })
      }),
    );
  });

  it("deletes the current session after confirmation and returns to a new conversation", async () => {
    const user = userEvent.setup();
    sessionStorage.setItem("nasclawbot-active-agent-session", "session-a");
    let deleted = false;
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      if (url === "/chat/agent/sessions" && !init?.method) {
        return Promise.resolve(jsonResponse(deleted ? { sessions: [] } : agentSessionListWithTitle("媒体库 Agent 设计")));
      }
      if (url === "/chat/agent/sessions/session-a" && !init?.method) {
        return Promise.resolve(jsonResponse({
          ...agentSessionDetail("session-a"),
          messages: [
            { role: "user", content: "媒体库", timestamp: "2026-06-05T10:00:00", metadata: {} },
            { role: "assistant", content: "媒体库 Agent 设计详情。", timestamp: "2026-06-05T10:01:00", metadata: {} }
          ]
        }));
      }
      if (url === "/chat/agent/sessions/session-a" && init?.method === "DELETE") {
        deleted = true;
        return Promise.resolve(new Response(null, { status: 204 }));
      }
      if (url === "/health") {
        return Promise.resolve(jsonResponse({ status: "ok" }));
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });

    render(<App />);

    expect(await screen.findByText("媒体库 Agent 设计详情。")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "更多操作：媒体库 Agent 设计" }));
    await user.click(screen.getByRole("menuitem", { name: "删除" }));

    const dialog = screen.getByRole("dialog", { name: "确认删除该会话？" });
    expect(within(dialog).getByText("此操作不可恢复。")).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "删除" }));

    await waitFor(() => {
      expect(sessionStorage.getItem("nasclawbot-active-agent-session")).toBeNull();
    });
    expect(screen.getByText("输入媒体需求")).toBeInTheDocument();
    expect(screen.queryByText("媒体库 Agent 设计详情。")).not.toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      "/chat/agent/sessions/session-a",
      expect.objectContaining({ method: "DELETE" }),
    );
  });

  it("switches to downloads and settings tabs", async () => {
    const user = userEvent.setup();
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);

      if (url === "/qb/torrents") {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              items: [
                {
                  hash: "hash-1",
                  name: "Dune 2160p",
                  category: "movies",
                  tags: ["uhd"],
                  state: "downloading",
                  progress: 0.62,
                  download_speed: 1024,
                  upload_speed: 64,
                  eta: 1200,
                  save_path: "/downloads/dune",
                  size: 10,
                  total_size: 20
                }
              ]
            }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          ),
        );
      }

      if (url === "/qb/torrents/hash-1") {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              hash: "hash-1",
              name: "Dune 2160p",
              category: "movies",
              tags: ["uhd"],
              state: "downloading",
              progress: 0.62,
              download_speed: 1024,
              upload_speed: 64,
              eta: 1200,
              save_path: "/downloads/dune",
              size: 10,
              total_size: 20,
              comment: "",
              total_uploaded: 5,
              share_ratio: 1.25,
              creation_date: 1
            }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          ),
        );
      }

      if (url === "/chat/agent/sessions") {
        return Promise.resolve(jsonResponse({ sessions: [] }));
      }

      if (url === "/health") {
        return Promise.resolve(
          new Response(JSON.stringify({ status: "ok" }), {
            status: 200,
            headers: { "Content-Type": "application/json" }
          }),
        );
      }

      if (url === "/health/services") {
        return Promise.resolve(
          new Response(JSON.stringify({
            status: "ok",
            services: [
              { service: "tmdb", status: "ok", latency_ms: 45.2, message: "TMDB API 响应正常" },
              { service: "tavily", status: "unconfigured", latency_ms: 0.0, message: "Tavily 未配置" },
              { service: "mteam", status: "ok", latency_ms: 234.1, message: "M-Team API 响应正常" },
              { service: "qbittorrent", status: "ok", latency_ms: 12.3, message: "qBittorrent API 响应正常" },
            ],
          }), {
            status: 200,
            headers: { "Content-Type": "application/json" }
          }),
        );
      }

      throw new Error(`Unexpected fetch: ${url}`);
    });

    render(<App />);

    await user.click(screen.getByRole("tab", { name: "Downloads" }));
    expect(await screen.findByText("下载任务")).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "状态" }));
    expect(screen.getByText("服务健康检查")).toBeInTheDocument();
    expect(screen.getByText("点击卡片检查各外部服务的连通性和凭据状态。")).toBeInTheDocument();
    expect(screen.getAllByText("未测试")).toHaveLength(4);
  });

  it("prevents default composer submission for empty chat input", () => {
    render(<App />);

    const sendButton = screen.getByRole("button", { name: "发送" });
    const composer = sendButton.closest("form");
    expect(composer).not.toBeNull();

    const submitEvent = new Event("submit", { bubbles: true, cancelable: true });
    const wasNotPrevented = composer?.dispatchEvent(submitEvent);

    expect(wasNotPrevented).toBe(false);
    expect(submitEvent.defaultPrevented).toBe(true);
  });

  it("links tabs to the active tab panel with stable ARIA ids", () => {
    render(<App />);

    const chatTab = screen.getByRole("tab", { name: "Chat" });
    const chatPanel = screen.getByRole("tabpanel", { name: "Chat" });

    expect(chatTab).toHaveAttribute("id", "workspace-tab-chat");
    expect(chatTab).toHaveAttribute("aria-controls", "workspace-panel-chat");
    expect(chatPanel).toHaveAttribute("id", "workspace-panel-chat");
    expect(chatPanel).toHaveAttribute("aria-labelledby", "workspace-tab-chat");
  });

  it("moves to the next tab with ArrowRight", async () => {
    const user = userEvent.setup();
    render(<App />);

    const chatTab = screen.getByRole("tab", { name: "Chat" });
    chatTab.focus();

    await user.keyboard("{ArrowRight}");

    const downloadsTab = screen.getByRole("tab", { name: "Downloads" });
    expect(downloadsTab).toHaveFocus();
    expect(downloadsTab).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tabpanel", { name: "Downloads" })).toBeInTheDocument();
  });
});
