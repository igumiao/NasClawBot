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
    decision: "approve_once" | "approve_and_grant_session" = "approve_once",
    signal?: AbortSignal,
  ): Promise<AgentApprovalResponse> {
    return postJson<AgentApprovalResponse>(approvalUrl(sessionId, approvalId, "approve"), { decision }, signal);
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

// ── Memory Curator API ────────────────────────────────────────

export interface MemoryInboxEntry {
  index: number;
  timestamp: string;
  text: string;
}

export interface MemoryInboxResponse {
  entries: MemoryInboxEntry[];
  entry_count: number;
}

export interface CurationSuggestion {
  inbox_index: number | null;
  preview: string;
  action: "keep" | "discard" | "modify" | "delete";
  destination: "user_profile" | "knowledge" | null;
  section: string | null;
  edited_text: string | null;
  existing_text: string | null;
  new_text: string | null;
  reason: string | null;
}

export interface CurationResponse {
  suggestions: CurationSuggestion[];
  inbox_entry_count: number;
  sections: {
    user_profile: string[];
    knowledge: string[];
  };
}

export interface CuratorApplyDecision {
  action: "keep" | "discard" | "modify" | "delete";
  inbox_index?: number | null;
  destination?: "user_profile" | "knowledge";
  section?: string;
  text?: string;
  existing_text?: string;
  new_text?: string;
}

export interface CuratorApplyResponse {
  applied: number;
  discarded: number;
  modified: number;
  deleted: number;
  remaining: number;
}

export async function fetchInbox(): Promise<MemoryInboxResponse> {
  const res = await fetch("/memory/inbox");
  if (!res.ok) throw new Error("Failed to fetch inbox");
  return res.json();
}

export async function fetchCuration(): Promise<CurationResponse> {
  const res = await fetch("/memory/curate", { method: "POST" });
  if (!res.ok) throw new Error("Failed to run curation");
  return res.json();
}

export async function applyCuration(
  inboxEntryCount: number,
  decisions: CuratorApplyDecision[]
): Promise<CuratorApplyResponse> {
  const res = await fetch("/memory/curate/apply", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ inbox_entry_count: inboxEntryCount, decisions }),
  });
  if (!res.ok) throw new Error("Failed to apply curation");
  return res.json();
}
