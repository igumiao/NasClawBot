import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ChatPanel } from "./ChatPanel";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("ChatPanel", () => {
  it("submits a message and renders returned search results", async () => {
    const user = userEvent.setup();

    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          session_id: "session-1",
          status: "completed",
          message: "找到 1 个搜索结果。",
          results: [
            {
              id: "r1",
              title: "Dune 4K",
              media_type: "movie",
              year: null,
              seeders: 88,
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

    render(
      <ChatPanel
        id="workspace-panel-chat"
        labelledBy="workspace-tab-chat"
        onDownloadSubmitted={() => undefined}
      />,
    );

    await user.type(screen.getByRole("textbox", { name: "媒体需求" }), "我想看沙丘");
    await user.click(screen.getByRole("button", { name: "发送" }));

    expect(await screen.findByText("Dune 4K")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "加入 qB" })).toBeInTheDocument();
  });

  it("adds a selected result through the download endpoint", async () => {
    const user = userEvent.setup();
    const onDownloadSubmitted = vi.fn();

    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            session_id: "session-1",
            status: "completed",
            message: "找到 1 个搜索结果。",
            results: [
              {
                id: "r1",
                title: "Dune 4K",
                media_type: "movie",
                year: null,
                seeders: 88,
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
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            status: "completed",
            receipt: { external_id: "r1", status: "submitted_paused" },
            error: null
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
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
    await user.click(await screen.findByRole("button", { name: "加入 qB" }));

    expect(fetchMock).toHaveBeenLastCalledWith(
      "/download",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ torrent_id: "r1", qb_category: "mteam" })
      }),
    );
    expect(onDownloadSubmitted).toHaveBeenCalledWith({ external_id: "r1", status: "submitted_paused" });
    expect(await screen.findByText("下载请求已提交，qB 任务保持暂停。")).toBeInTheDocument();
  });
});
