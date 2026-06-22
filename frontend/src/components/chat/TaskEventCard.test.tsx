import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { TaskEventCard } from "./TaskEventCard";

describe("TaskEventCard", () => {
  const baseEvent = {
    event_id: "e1",
    task_id: "t1",
    source_session_id: "s1",
    kind: "organize_completed",
    severity: "success" as const,
    title: "整理完成",
    summary: "文件已整理到 电影/某某",
    created_at: "2026-06-22T10:05:00",
    acknowledged_at: null,
  };

  it("renders the event title and summary", () => {
    render(<TaskEventCard event={baseEvent} onAcknowledge={vi.fn()} />);

    expect(screen.getByRole("heading", { name: "整理完成" })).toBeInTheDocument();
    expect(screen.getByText("文件已整理到 电影/某某")).toBeInTheDocument();
  });

  it("renders the event kind", () => {
    render(<TaskEventCard event={baseEvent} onAcknowledge={vi.fn()} />);

    expect(screen.getByText("organize_completed")).toBeInTheDocument();
  });

  it("renders success severity icon", () => {
    render(<TaskEventCard event={baseEvent} onAcknowledge={vi.fn()} />);

    // The success icon contains the checkmark character.
    expect(screen.getByText("✓")).toBeInTheDocument();
  });

  it("renders different severity icons", () => {
    const { rerender } = render(
      <TaskEventCard event={{ ...baseEvent, severity: "info" }} onAcknowledge={vi.fn()} />,
    );
    expect(screen.getByText("ℹ")).toBeInTheDocument();

    rerender(
      <TaskEventCard event={{ ...baseEvent, severity: "warning" }} onAcknowledge={vi.fn()} />,
    );
    expect(screen.getByText("⚠")).toBeInTheDocument();

    rerender(
      <TaskEventCard event={{ ...baseEvent, severity: "error" }} onAcknowledge={vi.fn()} />,
    );
    expect(screen.getByText("✗")).toBeInTheDocument();
  });

  it("renders unknown severity as info fallback", () => {
    render(
      <TaskEventCard
        event={{ ...baseEvent, severity: "unknown" as string }}
        onAcknowledge={vi.fn()}
      />,
    );
    expect(screen.getByText("ℹ")).toBeInTheDocument();
  });

  it("calls onAcknowledge when dismiss button is clicked", async () => {
    const onAcknowledge = vi.fn();
    render(<TaskEventCard event={baseEvent} onAcknowledge={onAcknowledge} />);

    await userEvent.click(screen.getByLabelText("忽略事件"));

    expect(onAcknowledge).toHaveBeenCalledWith("e1");
  });

  it("renders a time element with the ISO date", () => {
    render(<TaskEventCard event={baseEvent} onAcknowledge={vi.fn()} />);

    const time = screen.getByRole("status").querySelector("time");
    expect(time).toHaveAttribute("datetime", "2026-06-22T10:05:00");
  });
});
