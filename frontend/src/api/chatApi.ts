import type {
  AgentApprovalResponse,
  AgentSessionDetailResponse,
  ChatResponse,
  DownloadResponse
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

  addDownload(
    torrentId: string,
    qbCategory = "mteam",
    signal?: AbortSignal,
  ): Promise<DownloadResponse> {
    return postJson<DownloadResponse>(
      "/download",
      {
        torrent_id: torrentId,
        qb_category: qbCategory
      },
      signal,
    );
  }
};
