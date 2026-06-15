import { afterEach, describe, expect, it, vi } from "vitest";
import type { ChatResponse, PendingApproval } from "../types/api";
import { chatInitialState, chatReducer, createSessionId } from "./chatState";

const searchResult = {
  id: "r1",
  title: "Dune",
  media_type: "movie",
  year: null,
  seeders: 10,
  leechers: 2,
  discount: "FREE",
  imdb: "tt1160419",
  douban: null,
  resolution: "2160p",
  size: "60 GB",
  size_bytes: null,
  source: "mteam",
  small_description: null,
  subtitle_flags: [],
  labels_new: [],
};

const pendingApproval: PendingApproval = {
  approval_id: "approval-1",
  session_id: "session-1",
  tool_call_id: "call-download",
  tool_name: "qb_add_torrent",
  arguments: { torrent_id: "r1", qb_category: "movie" },
  status: "pending",
  reason: "Tool call requires user approval.",
  created_at: "2026-06-05T10:00:00",
  expires_at: "2026-06-05T10:30:00",
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

function agentResponse(overrides: Partial<ChatResponse> = {}): ChatResponse {
  return {
    session_id: "session-1",
    status: "completed",
    message: "找到 1 个搜索结果。",
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
      approval_id: null,
      results: [searchResult],
    }],
    pending_approvals: [],
    error: null,
    ...overrides
  };
}

describe("chatState", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("creates stable session ids with the app prefix", () => {
    expect(createSessionId()).toMatch(/^nasclaw-/);
  });

  it("uses random UUIDs with stable app prefixes when available", () => {
    vi.stubGlobal("crypto", { randomUUID: () => "uuid-123" });

    const state = chatReducer(chatInitialState(), {
      type: "user_submitted",
      text: "Dune tonight"
    });

    expect(state.sessionId).toBe("nasclaw-uuid-123");
    expect(state.messages[0].id).toBe("user-uuid-123");
  });

  it("inserts assistant, tool activity, search results, and approval in the required order", () => {
    const withUser = chatReducer(chatInitialState("session-1"), {
      type: "user_submitted",
      text: "Dune tonight"
    });
    const withResponse = chatReducer(withUser, {
      type: "chat_response_received",
      response: agentResponse({ pending_approvals: [pendingApproval] })
    });

    expect(withResponse.messages.map((message) => message.kind)).toEqual([
      "user",
      "assistant",
      "tool_activity",
      "search_results",
      "approval"
    ]);
    expect(withResponse.pendingApproval?.approval_id).toBe("approval-1");
  });

  it("reuses assistant and receipt messages for approval results", () => {
    const pending = chatReducer(chatInitialState("session-1"), {
      type: "chat_response_received",
      response: agentResponse({
        message: "工具调用需要确认。",
        results: [],
        tool_calls: [],
        pending_approvals: [pendingApproval]
      })
    });

    const approved = chatReducer(pending, {
      type: "approval_response_received",
      response: {
        session_id: "session-1",
        approval_id: "approval-1",
        status: "approved",
        message: "已提交到 qBittorrent，任务保持暂停。",
        receipt: { external_id: "r1" },
        error: null
      }
    });

    expect(approved.messages.map((message) => message.kind)).toEqual([
      "assistant",
      "approval",
      "assistant",
      "receipt"
    ]);
    expect(approved.messages[1]).toMatchObject({ kind: "approval", status: "approved" });
    expect(approved.pendingApproval).toBeNull();
  });

  it("appends the next pending approval from an approval response", () => {
    const nextApproval = {
      ...pendingApproval,
      approval_id: "approval-2",
      tool_call_id: "call-2",
      tool_name: "qb_control_torrent",
      arguments: { torrent_hash: "abc", action: "resume" }
    };
    const pending = chatReducer(chatInitialState("session-1"), {
      type: "chat_response_received",
      response: agentResponse({
        message: "工具调用需要确认。",
        results: [],
        tool_calls: [],
        pending_approvals: [pendingApproval]
      })
    });

    const approved = chatReducer(pending, {
      type: "approval_response_received",
      response: {
        session_id: "session-1",
        approval_id: "approval-1",
        status: "approved",
        message: "第一步已完成，下一步需要确认。",
        receipt: null,
        pending_approvals: [nextApproval],
        error: null
      }
    });

    expect(approved.messages.map((message) => message.kind)).toEqual([
      "assistant",
      "approval",
      "assistant",
      "approval"
    ]);
    expect(approved.messages[1]).toMatchObject({ kind: "approval", status: "approved" });
    expect(approved.messages[3]).toMatchObject({ kind: "approval", status: "pending" });
    expect(approved.pendingApproval?.approval_id).toBe("approval-2");
  });

  it("keeps an expired approval card visible while unblocking the session", () => {
    const pending = chatReducer(chatInitialState("session-1"), {
      type: "chat_response_received",
      response: agentResponse({
        message: "工具调用需要确认。",
        results: [],
        tool_calls: [],
        pending_approvals: [pendingApproval]
      })
    });

    const expired = chatReducer(pending, {
      type: "approval_expired",
      approvalId: "approval-1"
    });

    expect(expired.messages[1]).toMatchObject({ kind: "approval", status: "expired" });
    expect(expired.pendingApproval).toBeNull();
    expect(expired.isSubmitting).toBe(false);
  });

  it("restores visible messages, search results, and pending approval from a checkpoint", () => {
    const state = chatReducer(chatInitialState("session-1"), {
      type: "session_restored",
      response: {
        session_id: "session-1",
        created_at: "2026-06-05T10:00:00",
        saved_at: "2026-06-05T10:01:00",
        messages: [
          { role: "user", content: "Dune", timestamp: "2026-06-05T10:00:00", metadata: {} },
          {
            role: "assistant",
            content: "",
            timestamp: "2026-06-05T10:00:10",
            metadata: {
              tool_calls: [{
                id: "call-search",
                function: { name: "mteam_search", arguments: "{\"keyword\":\"Dune\"}" }
              }]
            }
          },
          {
            role: "tool",
            content: JSON.stringify({
              status: "success",
              data: {
                candidates: Array.from({ length: 6 }, (_, index) => ({
                  ...searchResult,
                  id: `r${index + 1}`
                }))
              }
            }),
            timestamp: "2026-06-05T10:00:20",
            metadata: { tool_name: "mteam_search", tool_call_id: "call-search" }
          },
          { role: "assistant", content: "找到了 Dune。", timestamp: "2026-06-05T10:00:30", metadata: {} }
        ],
        archives: [],
        metadata: { pending_approvals: [pendingApproval] }
      }
    });

    expect(state.messages.map((message) => message.kind)).toEqual([
      "user",
      "assistant",
      "tool_activity",
      "search_results",
      "approval"
    ]);
    expect(state.pendingApproval?.approval_id).toBe("approval-1");
    expect(state.messages.find((message) => message.kind === "search_results")).toMatchObject({
      kind: "search_results",
      results: expect.arrayContaining([
        expect.objectContaining({ id: "r1" }),
        expect.objectContaining({ id: "r5" })
      ])
    });
    expect(
      state.messages.find((message) => message.kind === "search_results" && message.results.length === 5)
    ).toBeDefined();
  });
});
