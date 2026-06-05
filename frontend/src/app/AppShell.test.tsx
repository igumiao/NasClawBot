import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";

afterEach(() => {
  vi.restoreAllMocks();
  sessionStorage.clear();
});

describe("AppShell", () => {
  it("renders the conversation sidebar and chat tab by default", () => {
    render(<App />);

    expect(screen.getByText("NasClawBot")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "新会话" })).toBeDisabled();
    expect(screen.getByRole("tab", { name: "Chat" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByText("输入媒体需求")).toBeInTheDocument();
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

      if (url === "/health") {
        return Promise.resolve(
          new Response(JSON.stringify({ status: "ok" }), {
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

    await user.click(screen.getByRole("tab", { name: "Settings" }));
    expect(screen.getByText("运行状态")).toBeInTheDocument();
    expect(screen.getByText("只读面板。密钥由环境统一管理，这里只展示当前会话和后端状态。")).toBeInTheDocument();
    expect(await screen.findByText("ok")).toBeInTheDocument();
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
