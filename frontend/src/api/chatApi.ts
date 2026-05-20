import type { ChatResponse, ConfirmationPayload, ConfirmResponse } from "../types/api";
import { postJson } from "./http";

export const chatApi = {
  sendMessage(sessionId: string, message: string, signal?: AbortSignal): Promise<ChatResponse> {
    return postJson<ChatResponse>("/chat", { session_id: sessionId, message }, signal);
  },

  confirmDownload(
    sessionId: string,
    confirmationPayload: ConfirmationPayload,
    selectedResultId: string | null,
    signal?: AbortSignal,
  ): Promise<ConfirmResponse> {
    return postJson<ConfirmResponse>(
      "/confirm",
      {
        session_id: sessionId,
        action: "approve",
        selected_result_id: selectedResultId,
        confirmation_payload: confirmationPayload
      },
      signal,
    );
  },

  cancel(sessionId: string, signal?: AbortSignal): Promise<ConfirmResponse> {
    return postJson<ConfirmResponse>("/confirm", { session_id: sessionId, action: "cancel" }, signal);
  }
};
