import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ChatPanel } from "./ChatPanel";

const searchResult = {
  id: "r1",
  title: "Dune 4K",
  media_type: "movie",
  year: 2021,
  seeders: 88,
  leechers: 2,
  discount: "FREE",
  imdb: "tt1160419",
  douban: null,
  resolution: "2160p",
  size: "60 GB",
  size_bytes: null,
  source: "mteam"
};

const pendingApproval = {
  approval_id: "approval-1",
  session_id: "session-1",
  tool_call_id: "call-download",
  tool_name: "qb_add_torrent",
  arguments: { torrent_id: "r1", qb_category: "movie" },
  status: "pending",
  reason: "Tool call requires user approval.",
  created_at: "2099-06-05T10:00:00",
  expires_at: "2099-06-05T10:30:00",
  decided_at: null,
  decision: null,
  result: null,
  error: null,
  expired_at: null,
  risk: {
    level: "side_effect",
    summary: "Submit torrent to qBittorrent in paused state"
  }
};

function jsonResponse(body: unknown, status = 200, statusText = "") {
  return new Response(JSON.stringify(body), {
    status,
    statusText,
    headers: { "Content-Type": "application/json" }
  });
}

afterEach(() => {
  vi.restoreAllMocks();
  sessionStorage.clear();
});

describe("ChatPanel", () => {
  it("uses the Agent endpoint and renders assistant, tool activity, then search results", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      jsonResponse({
        session_id: "session-1",
        status: "completed",
        message: "推荐做种最多的 Dune 电影。",
        results: [searchResult],
        tool_calls: [{
          tool: "mteam_search",
          tool_call_id: "call-search",
          arguments: { keyword: "Dune", mode: "movie", sort_by: "most_seeded" },
          status: "success",
          stats: {},
          truncated: false,
          observation_stats: {},
          gate_result: "allow",
          gate_reason: null,
          approval_id: null
        }],
        pending_approvals: [],
        error: null
      }),
    );

    render(
      <ChatPanel
        id="workspace-panel-chat"
        labelledBy="workspace-tab-chat"
        onDownloadSubmitted={() => undefined}
      />,
    );

    await user.type(screen.getByRole("textbox", { name: "媒体需求" }), "找做种最多的 Dune 电影");
    await user.click(screen.getByRole("button", { name: "发送" }));

    expect(await screen.findByText("Dune 4K")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "mteam_search" })).toBeInTheDocument();
    expect(screen.getByText("most_seeded")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "请求下载" })).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      "/chat/agent",
      expect.objectContaining({
        method: "POST",
        body: expect.stringContaining("找做种最多的 Dune 电影")
      }),
    );
  });

  it("requests a download through the Agent, then approves it through the gated endpoint", async () => {
    const user = userEvent.setup();
    const onDownloadSubmitted = vi.fn();
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        jsonResponse({
          session_id: "session-1",
          status: "completed",
          message: "找到结果。",
          results: [searchResult],
          tool_calls: [],
          pending_approvals: [],
          error: null
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          session_id: "session-1",
          status: "awaiting_approval",
          message: "工具调用需要用户确认后才能执行: qb_add_torrent",
          results: [],
          tool_calls: [{
            tool: "qb_add_torrent",
            tool_call_id: "call-download",
            arguments: { torrent_id: "r1", qb_category: "movie" },
            status: "pending_approval",
            stats: {},
            truncated: false,
            observation_stats: {},
            gate_result: "ask_user",
            gate_reason: "Tool call requires user approval.",
            approval_id: "approval-1"
          }],
          pending_approvals: [pendingApproval],
          error: null
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          session_id: "session-1",
          approval_id: "approval-1",
          status: "approved",
          message: "已提交到 qBittorrent，任务保持暂停。",
          receipt: { external_id: "r1", status: "submitted_paused" },
          error: null
        }),
      );

    render(
      <ChatPanel
        id="workspace-panel-chat"
        labelledBy="workspace-tab-chat"
        onDownloadSubmitted={onDownloadSubmitted}
      />,
    );

    await user.type(screen.getByRole("textbox", { name: "媒体需求" }), "我想看沙丘");
    await user.click(screen.getByRole("button", { name: "发送" }));
    await user.click(await screen.findByRole("button", { name: "请求下载" }));

    expect(await screen.findByRole("button", { name: "批准并加入 qB" })).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "媒体需求" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "批准并加入 qB" }));

    expect(await screen.findByText("已提交到 qBittorrent，任务保持暂停。")).toBeInTheDocument();
    expect(onDownloadSubmitted).toHaveBeenCalledWith({ external_id: "r1", status: "submitted_paused" });
    expect(screen.getByRole("textbox", { name: "媒体需求" })).toBeEnabled();
    expect(fetchMock.mock.calls[1]?.[0]).toBe("/chat/agent");
    expect(JSON.parse(String(fetchMock.mock.calls[1]?.[1]?.body))).toEqual({
      session_id: expect.stringMatching(/^nasclaw-/),
      message: "请下载 M-Team torrent id r1"
    });
    expect(fetchMock).toHaveBeenLastCalledWith(
      expect.stringMatching(/\/chat\/agent\/sessions\/.+\/approvals\/approval-1\/approve/),
      expect.objectContaining({ method: "POST" }),
    );
    expect(fetchMock.mock.calls.some(([url]) => String(url) === "/download")).toBe(false);
  });

  it("marks a 409 expired approval and re-enables the composer", async () => {
    const user = userEvent.setup();
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        jsonResponse({
          session_id: "session-1",
          status: "awaiting_approval",
          message: "工具调用需要用户确认后才能执行: qb_add_torrent",
          results: [],
          tool_calls: [],
          pending_approvals: [pendingApproval],
          error: null
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({ detail: "Approval has expired" }, 409, "Conflict"),
      );

    render(<ChatPanel id="workspace-panel-chat" labelledBy="workspace-tab-chat" />);

    await user.type(screen.getByRole("textbox", { name: "媒体需求" }), "下载 r1");
    await user.click(screen.getByRole("button", { name: "发送" }));
    await user.click(await screen.findByRole("button", { name: "批准并加入 qB" }));

    expect(await screen.findByText("已过期")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "批准并加入 qB" })).not.toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "媒体需求" })).toBeEnabled();
  });

  it("restores the active Agent session after a page refresh", async () => {
    sessionStorage.setItem("nasclawbot-active-agent-session", "session/restore");
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      jsonResponse({
        session_id: "session/restore",
        created_at: "2026-06-05T10:00:00",
        saved_at: "2026-06-05T10:01:00",
        messages: [
          { role: "user", content: "Dune", timestamp: "2026-06-05T10:00:00", metadata: {} },
          { role: "assistant", content: "找到 Dune。", timestamp: "2026-06-05T10:01:00", metadata: {} }
        ],
        archives: [],
        metadata: { pending_approvals: [] }
      }),
    );

    render(<ChatPanel id="workspace-panel-chat" labelledBy="workspace-tab-chat" />);

    expect(await screen.findByText("找到 Dune。")).toBeInTheDocument();
    expect(screen.getByText("Dune")).toBeInTheDocument();
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/chat/agent/sessions/session%2Frestore",
        expect.objectContaining({ signal: undefined }),
      );
    });
  });
});
