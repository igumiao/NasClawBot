import { useCallback, useEffect, useReducer, useRef } from "react";
import { chatApi } from "../api/chatApi";
import { chatInitialState, chatReducer, createSessionId } from "../state/chatState";

type UseAgentChatSessionOptions = {
  activeSessionId: string | null;
  onActiveSessionChange: (sessionId: string | null) => void;
  onDownloadSubmitted?: (receipt: Record<string, unknown>) => void;
  onSessionActivity?: (sessionId: string) => void;
};

type HttpErrorLike = Error & {
  status?: number;
  detail?: unknown;
};

function errorDetail(error: unknown): string {
  if (error instanceof Error && error.message) {
    return error.message;
  }
  return "请求失败，请稍后重试。";
}

function isNotFoundError(error: unknown): boolean {
  return error instanceof Error && (error as HttpErrorLike).status === 404;
}

function isExpiredApprovalError(error: unknown): boolean {
  if (!(error instanceof Error)) return false;
  const httpError = error as HttpErrorLike;
  const detail = typeof httpError.detail === "string" ? httpError.detail : "";
  return httpError.status === 409 && /expired|过期/i.test(`${detail} ${httpError.message}`);
}

export function useAgentChatSession({
  activeSessionId,
  onActiveSessionChange,
  onDownloadSubmitted,
  onSessionActivity
}: UseAgentChatSessionOptions) {
  const [state, dispatch] = useReducer(
    chatReducer,
    activeSessionId ?? createSessionId(),
    chatInitialState
  );
  const stateRef = useRef(state);
  const selectionEffectRan = useRef(false);
  const restoreSequence = useRef(0);
  const sessionVersion = useRef(0);

  stateRef.current = state;

  const inputBlocked = state.isSubmitting || state.isRestoring || state.pendingApproval !== null;

  useEffect(() => {
    const isInitialRun = !selectionEffectRan.current;
    selectionEffectRan.current = true;

    if (!activeSessionId) {
      restoreSequence.current += 1;
      if (!isInitialRun) {
        sessionVersion.current += 1;
        dispatch({ type: "session_selected", sessionId: createSessionId() });
      }
      return;
    }

    if (!isInitialRun && activeSessionId === stateRef.current.sessionId) {
      return;
    }

    const sequence = restoreSequence.current + 1;
    restoreSequence.current = sequence;
    sessionVersion.current += 1;

    dispatch({ type: "session_selected", sessionId: activeSessionId });
    dispatch({ type: "session_restore_started" });

    void chatApi.fetchAgentSession(activeSessionId)
      .then((response) => {
        if (restoreSequence.current !== sequence) return;
        dispatch({ type: "session_restored", response });
      })
      .catch((error: unknown) => {
        if (restoreSequence.current !== sequence) {
          return;
        }
        if (isNotFoundError(error)) {
          dispatch({ type: "session_restore_finished" });
          return;
        }
        dispatch({
          type: "request_failed",
          title: "会话恢复失败",
          detail: errorDetail(error)
        });
      });
  }, [activeSessionId]);

  useEffect(() => {
    const approval = state.pendingApproval;
    if (!approval || state.isSubmitting) return;

    const expiresAt = Date.parse(approval.expires_at);
    if (!Number.isFinite(expiresAt)) return;
    const remaining = expiresAt - Date.now();
    if (remaining <= 0) {
      dispatch({ type: "approval_expired", approvalId: approval.approval_id });
      return;
    }

    const timer = globalThis.setTimeout(() => {
      dispatch({ type: "approval_expired", approvalId: approval.approval_id });
    }, Math.min(remaining, 2_147_483_647));
    return () => globalThis.clearTimeout(timer);
  }, [state.pendingApproval, state.isSubmitting]);

  const sendAgentMessage = useCallback(async (message: string) => {
    const currentState = stateRef.current;
    const text = message.trim();
    const blocked = currentState.isSubmitting || currentState.isRestoring || currentState.pendingApproval !== null;
    if (!text || blocked) return;

    if (!activeSessionId) {
      onActiveSessionChange(currentState.sessionId);
    }

    dispatch({ type: "user_submitted", text });
    const requestSessionId = currentState.sessionId;
    const requestVersion = sessionVersion.current;
    try {
      const response = await chatApi.sendAgentMessage(requestSessionId, text);
      if (sessionVersion.current !== requestVersion || stateRef.current.sessionId !== requestSessionId) {
        return;
      }
      dispatch({ type: "chat_response_received", response });
      onSessionActivity?.(requestSessionId);
    } catch (error) {
      if (sessionVersion.current !== requestVersion || stateRef.current.sessionId !== requestSessionId) {
        return;
      }
      dispatch({
        type: "request_failed",
        title: "发送失败",
        detail: errorDetail(error)
      });
    }
  }, [activeSessionId, onActiveSessionChange, onSessionActivity]);

  const requestDownload = useCallback(async (torrentId: string) => {
    await sendAgentMessage(`请下载 M-Team torrent id ${torrentId}`);
  }, [sendAgentMessage]);

  const decideApproval = useCallback(async (action: "approve" | "approve_and_grant_session" | "deny") => {
    const currentState = stateRef.current;
    const approval = currentState.pendingApproval;
    if (!approval || currentState.isSubmitting) return;

    dispatch({ type: "approval_started" });
    const requestSessionId = currentState.sessionId;
    const requestVersion = sessionVersion.current;
    try {
      const response = action === "deny"
        ? await chatApi.denyAgentCall(requestSessionId, approval.approval_id)
        : await chatApi.approveAgentCall(
          requestSessionId,
          approval.approval_id,
          action === "approve_and_grant_session" ? "approve_and_grant_session" : "approve_once",
        );
      if (sessionVersion.current !== requestVersion || stateRef.current.sessionId !== requestSessionId) {
        return;
      }
      dispatch({ type: "approval_response_received", response });
      onSessionActivity?.(requestSessionId);
      if (response.receipt) onDownloadSubmitted?.(response.receipt);
    } catch (error) {
      if (sessionVersion.current !== requestVersion || stateRef.current.sessionId !== requestSessionId) {
        return;
      }
      if (isExpiredApprovalError(error)) {
        dispatch({
          type: "approval_expired",
          approvalId: approval.approval_id,
          detail: "这次下载确认已过期，请重新发起下载请求。"
        });
        return;
      }
      const status = error instanceof Error ? (error as HttpErrorLike).status : undefined;
      dispatch({
        type: "request_failed",
        title: action === "deny" ? "拒绝失败" : "批准失败",
        detail: errorDetail(error),
        clearApproval: status === 409
      });
    }
  }, [onDownloadSubmitted, onSessionActivity]);

  return {
    state,
    inputBlocked,
    sendAgentMessage,
    requestDownload,
    decideApproval
  };
}
