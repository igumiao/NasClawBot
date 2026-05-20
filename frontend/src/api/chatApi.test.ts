import { afterEach, describe, expect, it, vi } from "vitest";
import { chatApi } from "./chatApi";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("chatApi", () => {
  it("posts a chat message with the current session", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          session_id: "session-1",
          status: "awaiting_confirmation",
          confirmation_payload: {
            summary: "Review candidates",
            recommended_result_id: "r1",
            results: [{ id: "r1", title: "Dune", seeders: 10, resolution: "2160p", size: "60 GB" }],
            selected_result_id: null,
            qb_category: "movies",
            execution_result: null,
            receipt: null
          },
          receipt: null,
          error: null
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );

    const result = await chatApi.sendMessage("session-1", "Dune tonight");

    expect(fetchMock).toHaveBeenCalledWith(
      "/chat",
      expect.objectContaining({
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: "session-1", message: "Dune tonight" })
      }),
    );
    expect(result.confirmation_payload?.results[0]?.title).toBe("Dune");
  });

  it("posts approval with selected result and payload", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          session_id: "session-1",
          status: "submitted_paused",
          confirmation_payload: null,
          receipt: { status: "submitted_paused", qb_hash: "abc" },
          error: null,
          messages: []
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );

    await chatApi.confirmDownload("session-1", {
      summary: "Review",
      recommended_result_id: "r1",
      results: [{ id: "r1", title: "Dune", seeders: 10, resolution: "2160p", size: "60 GB" }],
      selected_result_id: null,
      qb_category: "movies",
      execution_result: null,
      receipt: null
    }, "r1");

    expect(fetchMock).toHaveBeenCalledWith(
      "/confirm",
      expect.objectContaining({
        method: "POST",
        body: expect.stringContaining('"action":"approve"')
      }),
    );
  });
});
