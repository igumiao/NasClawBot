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
});
