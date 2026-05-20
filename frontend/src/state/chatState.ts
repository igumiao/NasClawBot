import type { ChatResponse, ConfirmationPayload, ConfirmResponse } from "../types/api";

export type ChatMessage =
  | { id: string; kind: "user"; text: string }
  | { id: string; kind: "assistant"; text: string }
  | { id: string; kind: "candidate"; payload: ConfirmationPayload }
  | { id: string; kind: "receipt"; receipt: Record<string, unknown> }
  | { id: string; kind: "error"; title: string; detail: string };

export type ChatState = {
  sessionId: string;
  messages: ChatMessage[];
  pendingConfirmation: ConfirmationPayload | null;
  selectedResultId: string | null;
  isSubmitting: boolean;
  lastError: string | null;
};

type ChatAction =
  | { type: "user_submitted"; text: string }
  | { type: "chat_response_received"; response: ChatResponse }
  | { type: "confirm_response_received"; response: ConfirmResponse }
  | { type: "selected_result_changed"; selectedResultId: string }
  | { type: "request_failed"; title: string; detail: string }
  | { type: "request_started" };

export function createSessionId(): string {
  return `nasclaw-${Date.now()}`;
}

export function chatInitialState(sessionId = createSessionId()): ChatState {
  return {
    sessionId,
    messages: [],
    pendingConfirmation: null,
    selectedResultId: null,
    isSubmitting: false,
    lastError: null
  };
}

function id(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function assistantText(response: ChatResponse | ConfirmResponse): string {
  if (response.error) return response.error;
  if (response.confirmation_payload) return response.confirmation_payload.summary || "找到候选结果，请确认。";
  if (response.receipt) return "下载请求已提交，qB 任务保持暂停。";
  return response.status || "请求完成。";
}

export function chatReducer(state: ChatState, action: ChatAction): ChatState {
  switch (action.type) {
    case "request_started":
      return { ...state, isSubmitting: true, lastError: null };
    case "user_submitted":
      return {
        ...state,
        isSubmitting: true,
        lastError: null,
        messages: [...state.messages, { id: id("user"), kind: "user", text: action.text }]
      };
    case "chat_response_received": {
      const messages: ChatMessage[] = [
        ...state.messages,
        { id: id("assistant"), kind: "assistant", text: assistantText(action.response) }
      ];
      if (action.response.confirmation_payload) {
        messages.push({ id: id("candidate"), kind: "candidate", payload: action.response.confirmation_payload });
      }
      return {
        ...state,
        messages,
        pendingConfirmation: action.response.confirmation_payload,
        selectedResultId:
          action.response.confirmation_payload?.recommended_result_id ??
          action.response.confirmation_payload?.results[0]?.id ??
          null,
        isSubmitting: false,
        lastError: action.response.error
      };
    }
    case "confirm_response_received": {
      const messages: ChatMessage[] = [
        ...state.messages,
        { id: id("assistant"), kind: "assistant", text: assistantText(action.response) }
      ];
      if (action.response.receipt) {
        messages.push({ id: id("receipt"), kind: "receipt", receipt: action.response.receipt });
      }
      return {
        ...state,
        messages,
        pendingConfirmation: action.response.confirmation_payload,
        isSubmitting: false,
        lastError: action.response.error
      };
    }
    case "selected_result_changed":
      return { ...state, selectedResultId: action.selectedResultId };
    case "request_failed":
      return {
        ...state,
        isSubmitting: false,
        lastError: action.detail,
        messages: [...state.messages, { id: id("error"), kind: "error", title: action.title, detail: action.detail }]
      };
    default:
      return state;
  }
}
