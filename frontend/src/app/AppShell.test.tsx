import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { App } from "./App";

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
    render(<App />);

    await user.click(screen.getByRole("tab", { name: "Downloads" }));
    expect(screen.getByText("下载任务")).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "Settings" }));
    expect(screen.getByText("运行状态")).toBeInTheDocument();
    expect(screen.getByText("只读状态页，连接状态和运行信息会显示在这里。")).toBeInTheDocument();
  });

  it("prevents default composer submission while chat integration is pending", () => {
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
