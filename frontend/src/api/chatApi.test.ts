import { afterEach, describe, expect, it, vi } from "vitest";
import { chatApi } from "./chatApi";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("chatApi", () => {
  it("posts a chat message to the Agent endpoint with the current session", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          session_id: "session-1",
          status: "completed",
          message: "找到 1 个搜索结果。",
          results: [
            {
              id: "r1",
              title: "Dune",
              media_type: "movie",
              year: null,
              seeders: 10,
              leechers: 2,
              discount: "FREE",
              imdb: "tt1160419",
              douban: "3001114",
              resolution: "2160p",
              size: "60 GB",
              size_bytes: null,
              source: "mteam"
            }
          ],
          tool_calls: [],
          pending_approvals: [],
          error: null
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );

    const result = await chatApi.sendMessage("session-1", "Dune tonight");

    expect(fetchMock).toHaveBeenCalledWith(
      "/chat/agent",
      expect.objectContaining({
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: "session-1", message: "Dune tonight" })
      }),
    );
    expect(result.results[0]?.title).toBe("Dune");
  });

  it("exposes sendAgentMessage as the explicit Agent API method", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          session_id: "session-1",
          status: "completed",
          message: "ok",
          results: [],
          tool_calls: [],
          pending_approvals: [],
          error: null
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );

    await chatApi.sendAgentMessage("session-1", "hello");

    expect(fetchMock).toHaveBeenCalledWith(
      "/chat/agent",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ session_id: "session-1", message: "hello" })
      }),
    );
  });

  it("approves an Agent tool call and encodes route parameters", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          session_id: "session/one",
          approval_id: "approval?one",
          status: "approved",
          message: "approved",
          receipt: { status: "submitted_paused" },
          error: null
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );

    const result = await chatApi.approveAgentCall("session/one", "approval?one");

    expect(fetchMock).toHaveBeenCalledWith(
      "/chat/agent/sessions/session%2Fone/approvals/approval%3Fone/approve",
      expect.objectContaining({
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ decision: "approve_once" })
      }),
    );
    expect(result.status).toBe("approved");
  });

  it("denies an Agent tool call and encodes route parameters", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          session_id: "session one",
          approval_id: "approval/one",
          status: "denied",
          message: "denied",
          receipt: null,
          error: null
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );

    await chatApi.denyAgentCall("session one", "approval/one");

    expect(fetchMock).toHaveBeenCalledWith(
      "/chat/agent/sessions/session%20one/approvals/approval%2Fone/deny",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({})
      }),
    );
  });

  it("fetches an Agent session and encodes the session id", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          session_id: "session/one",
          created_at: "2026-06-05T10:00:00",
          saved_at: "2026-06-05T10:01:00",
          messages: [
            {
              role: "user",
              content: "Dune",
              timestamp: "2026-06-05T10:00:00",
              metadata: {}
            }
          ],
          archives: [],
          metadata: { pending_approvals: [] }
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );

    const result = await chatApi.fetchAgentSession("session/one");

    expect(fetchMock).toHaveBeenCalledWith(
      "/chat/agent/sessions/session%2Fone",
      expect.objectContaining({ signal: undefined }),
    );
    expect(result.messages[0]?.content).toBe("Dune");
  });

  it("lists Agent sessions", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          sessions: [
            {
              session_id: "session-1",
              created_at: "2026-06-05T10:00:00",
              saved_at: "2026-06-05T10:10:00",
              message_count: 4,
              archive_count: 0,
              metadata: { title: "媒体库 Agent 设计" }
            }
          ]
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );

    const result = await chatApi.listAgentSessions();

    expect(fetchMock).toHaveBeenCalledWith(
      "/chat/agent/sessions",
      expect.objectContaining({ signal: undefined }),
    );
    expect(result.sessions[0]?.metadata.title).toBe("媒体库 Agent 设计");
  });

  it("updates an Agent session title and encodes the session id", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          session_id: "session/one",
          created_at: "2026-06-05T10:00:00",
          saved_at: "2026-06-05T10:01:00",
          messages: [],
          archives: [],
          metadata: { title: "新标题" }
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );

    await chatApi.updateAgentSession("session/one", { title: "新标题" });

    expect(fetchMock).toHaveBeenCalledWith(
      "/chat/agent/sessions/session%2Fone",
      expect.objectContaining({
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: "新标题" })
      }),
    );
  });

  it("deletes an Agent session and accepts the 204 response", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(null, { status: 204 }),
    );

    await chatApi.deleteAgentSession("session/one");

    expect(fetchMock).toHaveBeenCalledWith(
      "/chat/agent/sessions/session%2Fone",
      expect.objectContaining({ method: "DELETE" }),
    );
  });

  it("posts an explicit download request", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          status: "completed",
          receipt: { status: "submitted_paused", qb_hash: "abc" },
          error: null
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );

    await chatApi.addDownload("r1");

    expect(fetchMock).toHaveBeenCalledWith(
      "/download",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ torrent_id: "r1", qb_category: "mteam" })
      }),
    );
  });
});
