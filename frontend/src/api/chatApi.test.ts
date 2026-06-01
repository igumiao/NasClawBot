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
          status: "completed",
          message: "找到 1 个搜索结果。",
          results: [
            {
              id: "r1",
              title: "Dune",
              media_type: "movie",
              year: null,
              seeders: 10,
              resolution: "2160p",
              size: "60 GB",
              size_bytes: null,
              source: "mteam"
            }
          ],
          tool_calls: [],
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
    expect(result.results[0]?.title).toBe("Dune");
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
