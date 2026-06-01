import type { ChatResponse, DownloadResponse, ResourceCandidate } from "../types/api";

export type ChatMessage =
  | { id: string; kind: "user"; text: string }
  | { id: string; kind: "assistant"; text: string }
  | { id: string; kind: "search_results"; results: ResourceCandidate[] }
  | { id: string; kind: "receipt"; receipt: Record<string, unknown> }
  | { id: string; kind: "error"; title: string; detail: string };

export type ChatState = {
  sessionId: string;
  messages: ChatMessage[];
  isSubmitting: boolean;
  lastError: string | null;
};

type ChatAction =
  | { type: "user_submitted"; text: string }
  | { type: "chat_response_received"; response: ChatResponse }
  | { type: "download_started" }
  | { type: "download_response_received"; response: DownloadResponse }
  | { type: "request_failed"; title: string; detail: string }
  | { type: "request_started" };

export function createSessionId(): string {
  return `nasclaw-${uniqueToken()}`;
}

export function chatInitialState(sessionId = createSessionId()): ChatState {
  return {
    sessionId,
    messages: [],
    isSubmitting: false,
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

function downloadAssistantText(response: DownloadResponse): string {
  if (response.error) return response.error;
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
        { id: id("assistant"), kind: "assistant", text: chatAssistantText(action.response) }
      ];
      if (action.response.results.length > 0) {
        messages.push({ id: id("results"), kind: "search_results", results: action.response.results });
      }
      return {
        ...state,
        messages,
        isSubmitting: false,
        lastError: action.response.error
      };
    }
    case "download_started":
      return { ...state, isSubmitting: true, lastError: null };
    case "download_response_received": {
      const messages: ChatMessage[] = [
        ...state.messages,
        { id: id("assistant"), kind: "assistant", text: downloadAssistantText(action.response) }
      ];
      if (action.response.receipt) {
        messages.push({ id: id("receipt"), kind: "receipt", receipt: action.response.receipt });
      }
      return {
        ...state,
        messages,
        isSubmitting: false,
        lastError: action.response.error
      };
    }
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
