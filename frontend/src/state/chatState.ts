import type {
  AgentApprovalResponse,
  AgentSessionDetailResponse,
  AgentSessionMessage,
  AgentToolCall,
  ChatResponse,
  PendingApproval,
  ResourceCandidate
} from "../types/api";

export type ApprovalCardStatus = "pending" | "approved" | "denied" | "failed" | "expired";

export type ChatMessage =
  | { id: string; kind: "user"; text: string }
  | { id: string; kind: "assistant"; text: string }
  | { id: string; kind: "tool_activity"; toolCall: AgentToolCall }
  | { id: string; kind: "search_results"; results: ResourceCandidate[] }
  | { id: string; kind: "approval"; approval: PendingApproval; status: ApprovalCardStatus }
  | { id: string; kind: "receipt"; receipt: Record<string, unknown> }
  | { id: string; kind: "error"; title: string; detail: string };

export type ChatState = {
  sessionId: string;
  messages: ChatMessage[];
  pendingApproval: PendingApproval | null;
  isSubmitting: boolean;
  isRestoring: boolean;
  lastError: string | null;
};

export type ChatAction =
  | { type: "user_submitted"; text: string }
  | { type: "chat_response_received"; response: ChatResponse }
  | { type: "approval_started" }
  | { type: "approval_response_received"; response: AgentApprovalResponse }
  | { type: "approval_expired"; approvalId: string; detail?: string }
  | { type: "session_restore_started" }
  | { type: "session_restored"; response: AgentSessionDetailResponse }
  | { type: "session_restore_finished" }
  | { type: "request_failed"; title: string; detail: string; clearApproval?: boolean };

export function createSessionId(): string {
  return `nasclaw-${uniqueToken()}`;
}

export function chatInitialState(sessionId = createSessionId()): ChatState {
  return {
    sessionId,
    messages: [],
    pendingApproval: null,
    isSubmitting: false,
    isRestoring: false,
    lastError: null
  };
}

function id(prefix: string): string {
  return `${prefix}-${uniqueToken()}`;
}

function uniqueToken(): string {
  if (typeof globalThis.crypto?.randomUUID === "function") {
    return globalThis.crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function chatAssistantText(response: ChatResponse): string {
  if (response.error) return response.error;
  if (response.message) return response.message;
  return response.status || "请求完成。";
}

function approvalAssistantText(response: AgentApprovalResponse): string {
  if (response.error) return response.error;
  if (response.message) return response.message;
  return response.status || "审批请求已处理。";
}

function approvalStatus(status: string): ApprovalCardStatus {
  switch (status) {
    case "approved":
    case "denied":
    case "failed":
    case "expired":
      return status;
    default:
      return "failed";
  }
}

function updateApprovalMessage(
  messages: ChatMessage[],
  approvalId: string,
  status: ApprovalCardStatus,
): ChatMessage[] {
  return messages.map((message) =>
    message.kind === "approval" && message.approval.approval_id === approvalId
      ? { ...message, status }
      : message
  );
}

function appendChatResponse(messages: ChatMessage[], response: ChatResponse): ChatMessage[] {
  const next: ChatMessage[] = [
    ...messages,
    { id: id("assistant"), kind: "assistant", text: chatAssistantText(response) }
  ];

  for (const toolCall of response.tool_calls) {
    next.push({ id: id("tool"), kind: "tool_activity", toolCall });
  }

  if (response.results.length > 0) {
    next.push({ id: id("results"), kind: "search_results", results: response.results.slice(0, 5) });
  }

  for (const approval of response.pending_approvals) {
    next.push({ id: id("approval"), kind: "approval", approval, status: "pending" });
  }

  return next;
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function parseToolArguments(raw: unknown): Record<string, unknown> {
  if (typeof raw !== "string") {
    return asRecord(raw) ?? {};
  }
  try {
    return asRecord(JSON.parse(raw)) ?? {};
  } catch {
    return {};
  }
}

function restoredToolCalls(message: AgentSessionMessage): AgentToolCall[] {
  const metadata = asRecord(message.metadata);
  const rawCalls = metadata?.tool_calls;
  if (!Array.isArray(rawCalls)) return [];

  return rawCalls.flatMap((rawCall) => {
    const call = asRecord(rawCall);
    const fn = asRecord(call?.function);
    const tool = typeof fn?.name === "string" ? fn.name : "";
    if (!tool) return [];
    return [{
      tool,
      tool_call_id: typeof call?.id === "string" ? call.id : "",
      arguments: parseToolArguments(fn?.arguments),
      status: "restored",
      stats: {},
      truncated: false,
      observation_stats: {},
      gate_result: null,
      gate_reason: null,
      approval_id: null
    }];
  });
}

function parseToolPayload(content: string): Record<string, unknown> | null {
  try {
    return asRecord(JSON.parse(content));
  } catch {
    return null;
  }
}

function restoredToolOutput(message: AgentSessionMessage): ChatMessage[] {
  if (message.role !== "tool") return [];
  const metadata = asRecord(message.metadata);
  const toolName = typeof metadata?.tool_name === "string" ? metadata.tool_name : "";
  const payload = parseToolPayload(message.content);
  const data = asRecord(payload?.data);

  if (toolName === "mteam_search" && Array.isArray(data?.candidates)) {
    return [{
      id: id("results"),
      kind: "search_results",
      results: (data.candidates as ResourceCandidate[]).slice(0, 5)
    }];
  }

  if (toolName === "qb_add_torrent") {
    const receipt = asRecord(data?.receipt);
    if (receipt) {
      return [{ id: id("receipt"), kind: "receipt", receipt }];
    }
  }

  return [];
}

function restoredTurnMessages(turn: AgentSessionMessage[]): ChatMessage[] {
  const messages: ChatMessage[] = [];

  for (const message of turn) {
    if (message.role === "assistant" && message.content.trim()) {
      messages.push({ id: id("assistant"), kind: "assistant", text: message.content });
    }
  }
  for (const message of turn) {
    if (message.role !== "assistant") continue;
    for (const toolCall of restoredToolCalls(message)) {
      messages.push({ id: id("tool"), kind: "tool_activity", toolCall });
    }
  }
  for (const message of turn) {
    messages.push(...restoredToolOutput(message));
  }

  return messages;
}

function restoreMessages(response: AgentSessionDetailResponse): ChatMessage[] {
  const messages: ChatMessage[] = [];
  let turn: AgentSessionMessage[] = [];

  const flushTurn = () => {
    messages.push(...restoredTurnMessages(turn));
    turn = [];
  };

  for (const message of response.messages) {
    if (message.role === "user" && message.content.trim()) {
      flushTurn();
      messages.push({ id: id("user"), kind: "user", text: message.content });
      continue;
    }
    if (message.role === "assistant" || message.role === "tool") {
      turn.push(message);
    }
  }
  flushTurn();

  const metadata = asRecord(response.metadata);
  const pendingApprovals = Array.isArray(metadata?.pending_approvals)
    ? metadata.pending_approvals as PendingApproval[]
    : [];
  for (const approval of pendingApprovals) {
    messages.push({ id: id("approval"), kind: "approval", approval, status: "pending" });
  }

  return messages;
}

function pendingApprovalFromSession(response: AgentSessionDetailResponse): PendingApproval | null {
  const metadata = asRecord(response.metadata);
  const approvals = Array.isArray(metadata?.pending_approvals)
    ? metadata.pending_approvals as PendingApproval[]
    : [];
  return approvals.find((approval) => approval.status === "pending") ?? null;
}

export function chatReducer(state: ChatState, action: ChatAction): ChatState {
  switch (action.type) {
    case "user_submitted":
      return {
        ...state,
        isSubmitting: true,
        lastError: null,
        messages: [...state.messages, { id: id("user"), kind: "user", text: action.text }]
      };
    case "chat_response_received":
      return {
        ...state,
        messages: appendChatResponse(state.messages, action.response),
        pendingApproval: action.response.pending_approvals[0] ?? null,
        isSubmitting: false,
        lastError: action.response.error
      };
    case "approval_started":
      return { ...state, isSubmitting: true, lastError: null };
    case "approval_response_received": {
      const messages = updateApprovalMessage(
        state.messages,
        action.response.approval_id,
        approvalStatus(action.response.status)
      );
      messages.push({
        id: id("assistant"),
        kind: "assistant",
        text: approvalAssistantText(action.response)
      });
      if (action.response.receipt) {
        messages.push({ id: id("receipt"), kind: "receipt", receipt: action.response.receipt });
      }
      return {
        ...state,
        messages,
        pendingApproval: null,
        isSubmitting: false,
        lastError: action.response.error
      };
    }
    case "approval_expired": {
      const messages = updateApprovalMessage(state.messages, action.approvalId, "expired");
      if (action.detail) {
        messages.push({
          id: id("error"),
          kind: "error",
          title: "审批已过期",
          detail: action.detail
        });
      }
      return {
        ...state,
        messages,
        pendingApproval: null,
        isSubmitting: false,
        lastError: action.detail ?? null
      };
    }
    case "session_restore_started":
      return { ...state, isRestoring: true, lastError: null };
    case "session_restored":
      return {
        ...state,
        sessionId: action.response.session_id,
        messages: restoreMessages(action.response),
        pendingApproval: pendingApprovalFromSession(action.response),
        isRestoring: false,
        lastError: null
      };
    case "session_restore_finished":
      return { ...state, isRestoring: false };
    case "request_failed":
      return {
        ...state,
        isSubmitting: false,
        isRestoring: false,
        pendingApproval: action.clearApproval ? null : state.pendingApproval,
        lastError: action.detail,
        messages: [...state.messages, { id: id("error"), kind: "error", title: action.title, detail: action.detail }]
      };
    default:
      return state;
  }
}
