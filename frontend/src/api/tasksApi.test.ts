import { afterEach, describe, expect, it, vi } from "vitest";
import { tasksApi } from "./tasksApi";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("tasksApi", () => {
  describe("listTasks", () => {
    it("fetches tasks with no params", async () => {
      const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
        new Response(
          JSON.stringify({
            tasks: [
              {
                task_id: "t1",
                kind: "download_watch",
                status: "running",
                source_session_id: "s1",
                parent_task_id: null,
                attempts: 1,
                created_at: "2026-06-22T10:00:00",
                updated_at: "2026-06-22T10:01:00",
                started_at: "2026-06-22T10:00:30",
                completed_at: null,
              },
            ],
            total_count: 1,
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      );

      const result = await tasksApi.listTasks();

      expect(fetchMock).toHaveBeenCalledWith("/tasks", expect.objectContaining({ signal: undefined }));
      expect(result.tasks[0]?.task_id).toBe("t1");
      expect(result.total_count).toBe(1);
    });

    it("encodes query parameters", async () => {
      const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
        new Response(
          JSON.stringify({ tasks: [], total_count: 0 }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      );

      await tasksApi.listTasks({ source_session_id: "s1", status: "running", kind: "download_watch", limit: 10 });

      expect(fetchMock).toHaveBeenCalledWith(
        "/tasks?source_session_id=s1&status=running&kind=download_watch&limit=10",
        expect.anything(),
      );
    });
  });

  describe("getTaskDetail", () => {
    it("fetches a single task detail with encoded id", async () => {
      const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
        new Response(
          JSON.stringify({
            task: {
              task_id: "t/1",
              kind: "organize_download",
              status: "succeeded",
              source_session_id: "s1",
              parent_task_id: null,
              child_task_ids: [],
              attempts: 1,
              max_attempts: 20,
              created_at: "2026-06-22T10:00:00",
              updated_at: "2026-06-22T10:05:00",
              started_at: "2026-06-22T10:01:00",
              completed_at: "2026-06-22T10:04:00",
              latest_run: {
                run_id: "r1",
                attempt: 1,
                status: "succeeded",
                started_at: "2026-06-22T10:01:00",
                completed_at: "2026-06-22T10:04:00",
              },
            },
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      );

      const result = await tasksApi.getTaskDetail("t/1");

      expect(fetchMock).toHaveBeenCalledWith(
        "/tasks/t%2F1",
        expect.anything(),
      );
      expect(result.task.task_id).toBe("t/1");
      expect(result.task.latest_run?.status).toBe("succeeded");
    });
  });

  describe("cancelTask", () => {
    it("posts to cancel endpoint", async () => {
      const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
        new Response(
          JSON.stringify({
            task_id: "t1",
            status: "cancelled",
            previous_status: "running",
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      );

      const result = await tasksApi.cancelTask("t1");

      expect(fetchMock).toHaveBeenCalledWith(
        "/tasks/t1/cancel",
        expect.objectContaining({ method: "POST", body: JSON.stringify({}) }),
      );
      expect(result.status).toBe("cancelled");
    });
  });

  describe("listTaskEvents", () => {
    it("fetches unacknowledged events for a session", async () => {
      const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
        new Response(
          JSON.stringify({
            events: [
              {
                event_id: "e1",
                task_id: "t1",
                source_session_id: "s1",
                kind: "organize_completed",
                severity: "success",
                title: "整理完成",
                summary: "文件已整理到 电影/某某",
                created_at: "2026-06-22T10:05:00",
                acknowledged_at: null,
              },
            ],
            total_count: 1,
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      );

      const result = await tasksApi.listTaskEvents({
        source_session_id: "s1",
        acknowledged: false,
        limit: 50,
      });

      expect(fetchMock).toHaveBeenCalledWith(
        "/task-events?source_session_id=s1&acknowledged=false&limit=50",
        expect.anything(),
      );
      expect(result.events[0]?.event_id).toBe("e1");
      expect(result.total_count).toBe(1);
    });
  });

  describe("acknowledgeEvent", () => {
    it("posts to acknowledge endpoint with encoded id", async () => {
      const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
        new Response(
          JSON.stringify({ event_id: "e/1", status: "acknowledged" }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      );

      const result = await tasksApi.acknowledgeEvent("e/1");

      expect(fetchMock).toHaveBeenCalledWith(
        "/task-events/e%2F1/acknowledge",
        expect.objectContaining({ method: "POST", body: JSON.stringify({}) }),
      );
      expect(result.status).toBe("acknowledged");
    });
  });
});
