import type {
  AgentApprovalResponse,
  AgentSessionDetailResponse,
  AgentSessionListResponse,
  ChatResponse,
  DownloadResponse,
  SessionUpdateRequest
} from "../types/api";
import { postJson, readJson } from "./http";

function sendAgentMessage(
  sessionId: string,
  message: string,
  signal?: AbortSignal,
): Promise<ChatResponse> {
  return postJson<ChatResponse>("/chat/agent", { session_id: sessionId, message }, signal);
}

function approvalUrl(sessionId: string, approvalId: string, decision: "approve" | "deny"): string {
  return `/chat/agent/sessions/${encodeURIComponent(sessionId)}/approvals/${encodeURIComponent(approvalId)}/${decision}`;
}

export const chatApi = {
  sendAgentMessage,
  sendMessage: sendAgentMessage,

  approveAgentCall(
    sessionId: string,
    approvalId: string,
    signal?: AbortSignal,
  ): Promise<AgentApprovalResponse> {
    return postJson<AgentApprovalResponse>(approvalUrl(sessionId, approvalId, "approve"), {}, signal);
  },

  denyAgentCall(
    sessionId: string,
    approvalId: string,
    signal?: AbortSignal,
  ): Promise<AgentApprovalResponse> {
    return postJson<AgentApprovalResponse>(approvalUrl(sessionId, approvalId, "deny"), {}, signal);
  },

  async fetchAgentSession(
    sessionId: string,
    signal?: AbortSignal,
  ): Promise<AgentSessionDetailResponse> {
    const response = await fetch(`/chat/agent/sessions/${encodeURIComponent(sessionId)}`, { signal });
    return readJson<AgentSessionDetailResponse>(response);
  },

  async listAgentSessions(signal?: AbortSignal): Promise<AgentSessionListResponse> {
    const response = await fetch("/chat/agent/sessions", { signal });
    return readJson<AgentSessionListResponse>(response);
  },

  async updateAgentSession(
    sessionId: string,
    body: SessionUpdateRequest,
    signal?: AbortSignal,
  ): Promise<AgentSessionDetailResponse> {
    const response = await fetch(`/chat/agent/sessions/${encodeURIComponent(sessionId)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal
    });
    return readJson<AgentSessionDetailResponse>(response);
  },

  async deleteAgentSession(sessionId: string, signal?: AbortSignal): Promise<void> {
    const response = await fetch(`/chat/agent/sessions/${encodeURIComponent(sessionId)}`, {
      method: "DELETE",
      signal
    });
    if (response.ok) return;
    await readJson<unknown>(response);
  },

  addDownload(
    torrentId: string,
    qbCategory = "mteam",
    savePath?: string,
    signal?: AbortSignal,
  ): Promise<DownloadResponse> {
    const body: Record<string, unknown> = { torrent_id: torrentId, qb_category: qbCategory };
    if (savePath) body.save_path = savePath;
    return postJson<DownloadResponse>("/download", body, signal);
  }
};
