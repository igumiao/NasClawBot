import type {
  TaskCancelResponse,
  TaskDetailResponse,
  TaskEventAcknowledgeResponse,
  TaskEventListResponse,
  TaskListResponse,
} from "../types/api";
import { apiFetch } from "./apiFetch";
import { postJson, readJson } from "./http";

export type ListTasksParams = {
  source_session_id?: string;
  status?: string;
  kind?: string;
  limit?: number;
};

export type ListTaskEventsParams = {
  source_session_id?: string;
  acknowledged?: boolean;
  after?: string;
  limit?: number;
};

function encodeQuery(params: Record<string, string | number | boolean | undefined>): string {
  const entries = Object.entries(params).filter(
    (entry): entry is [string, string | number | boolean] => entry[1] !== undefined,
  );
  if (entries.length === 0) return "";
  const search = new URLSearchParams();
  for (const [key, value] of entries) {
    search.set(key, String(value));
  }
  return `?${search.toString()}`;
}

export const tasksApi = {
  async listTasks(params: ListTasksParams = {}, signal?: AbortSignal): Promise<TaskListResponse> {
    const qs = encodeQuery(params);
    const response = await apiFetch(`/tasks${qs}`, { signal });
    return readJson<TaskListResponse>(response);
  },

  async getTaskDetail(taskId: string, signal?: AbortSignal): Promise<TaskDetailResponse> {
    const response = await apiFetch(`/tasks/${encodeURIComponent(taskId)}`, { signal });
    return readJson<TaskDetailResponse>(response);
  },

  cancelTask(taskId: string, signal?: AbortSignal): Promise<TaskCancelResponse> {
    return postJson<TaskCancelResponse>(`/tasks/${encodeURIComponent(taskId)}/cancel`, {}, signal);
  },

  async listTaskEvents(params: ListTaskEventsParams = {}, signal?: AbortSignal): Promise<TaskEventListResponse> {
    const qs = encodeQuery(params);
    const response = await apiFetch(`/task-events${qs}`, { signal });
    return readJson<TaskEventListResponse>(response);
  },

  acknowledgeEvent(eventId: string, signal?: AbortSignal): Promise<TaskEventAcknowledgeResponse> {
    return postJson<TaskEventAcknowledgeResponse>(
      `/task-events/${encodeURIComponent(eventId)}/acknowledge`,
      {},
      signal,
    );
  },
};
