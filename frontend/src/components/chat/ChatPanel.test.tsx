import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ChatPanel } from "./ChatPanel";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("ChatPanel", () => {
  it("submits a message and renders returned candidates", async () => {
    const user = userEvent.setup();

    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          session_id: "session-1",
          status: "awaiting_confirmation",
          confirmation_payload: {
            summary: "已找到结果，请确认。",
            recommended_result_id: "r1",
            results: [{ id: "r1", title: "Dune 4K", seeders: 88, resolution: "2160p", size: "60 GB" }],
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
  });

  it("disables stale candidate cards after a newer search response arrives", async () => {
    const user = userEvent.setup();

    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            session_id: "session-1",
            status: "awaiting_confirmation",
            confirmation_payload: {
              summary: "第一组结果",
              recommended_result_id: "old",
              results: [{ id: "old", title: "Dune Old", seeders: 12, resolution: "1080p", size: "12 GB" }],
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
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            session_id: "session-1",
            status: "awaiting_confirmation",
            confirmation_payload: {
              summary: "第二组结果",
              recommended_result_id: "new",
              results: [{ id: "new", title: "Dune New", seeders: 88, resolution: "2160p", size: "60 GB" }],
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

    render(
      <ChatPanel
        id="workspace-panel-chat"
        labelledBy="workspace-tab-chat"
        onDownloadSubmitted={() => undefined}
      />,
    );

    await user.type(screen.getByRole("textbox", { name: "媒体需求" }), "第一版");
    await user.click(screen.getByRole("button", { name: "发送" }));
    const oldRadio = await screen.findByRole("radio", { name: "Dune Old" });

    await user.type(screen.getByRole("textbox", { name: "媒体需求" }), "第二版");
    await user.click(screen.getByRole("button", { name: "发送" }));
    const newRadio = await screen.findByRole("radio", { name: "Dune New" });

    const oldCard = oldRadio.closest("section");
    const newCard = newRadio.closest("section");

    expect(oldCard).not.toBeNull();
    expect(newCard).not.toBeNull();
    expect(oldRadio).toBeDisabled();
    expect(newRadio).not.toBeDisabled();
    expect(within(oldCard as HTMLElement).getByRole("button", { name: "确认加入 qB" })).toBeDisabled();
    expect(within(newCard as HTMLElement).getByRole("button", { name: "确认加入 qB" })).not.toBeDisabled();
  });
});
