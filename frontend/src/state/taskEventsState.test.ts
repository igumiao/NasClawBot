import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useTaskEvents } from "./taskEventsState";

afterEach(() => {
  vi.restoreAllMocks();
});

const mockEvent = {
  event_id: "e1",
  task_id: "t1",
  source_session_id: "s1",
  kind: "organize_completed",
  severity: "success",
  title: "整理完成",
  summary: "文件已整理到 电影/某某",
  created_at: "2026-06-22T10:05:00",
  acknowledged_at: null,
};

const mockEvent2 = {
  event_id: "e2",
  task_id: "t2",
  source_session_id: "s1",
  kind: "download_completed",
  severity: "info",
  title: "下载完成",
  summary: "某某已下载完成",
  created_at: "2026-06-22T10:06:00",
  acknowledged_at: null,
};

function jsonResponse(data: unknown) {
  return new Response(JSON.stringify(data), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

describe("useTaskEvents", () => {
  it("returns empty events when sessionId is null", () => {
    const { result } = renderHook(() => useTaskEvents(null));

    expect(result.current.events).toEqual([]);
    expect(result.current.loading).toBe(false);
  });

  it("fetches events for the given session on mount", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      jsonResponse({ events: [mockEvent], total_count: 1 }),
    );

    const { result } = renderHook(() => useTaskEvents("s1"));

    await waitFor(() => {
      expect(result.current.events).toHaveLength(1);
    });

    expect(result.current.events[0]?.event_id).toBe("e1");
    expect(result.current.loading).toBe(false);
  });

  it("clears events when sessionId changes to null", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      jsonResponse({ events: [mockEvent], total_count: 1 }),
    );

    const { result, rerender } = renderHook(({ id }) => useTaskEvents(id), {
      initialProps: { id: "s1" as string | null },
    });

    await waitFor(() => {
      expect(result.current.events).toHaveLength(1);
    });

    rerender({ id: null });

    expect(result.current.events).toEqual([]);
  });

  it("acknowledge removes the event from the list", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        jsonResponse({ events: [mockEvent], total_count: 1 }),
      )
      .mockResolvedValue(
        jsonResponse({ event_id: "e1", status: "acknowledged" }),
      );

    const { result } = renderHook(() => useTaskEvents("s1"));

    await waitFor(() => {
      expect(result.current.events).toHaveLength(1);
    });

    await act(async () => {
      await result.current.acknowledge("e1");
    });

    expect(result.current.events).toHaveLength(0);
  });

  it("acknowledgeAll removes all events", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        jsonResponse({ events: [mockEvent, mockEvent2], total_count: 2 }),
      )
      .mockResolvedValue(
        jsonResponse({ event_id: "e1", status: "acknowledged" }),
      );

    const { result } = renderHook(() => useTaskEvents("s1"));

    await waitFor(() => {
      expect(result.current.events).toHaveLength(2);
    });

    await act(async () => {
      await result.current.acknowledgeAll();
    });

    expect(result.current.events).toHaveLength(0);
  });
});
