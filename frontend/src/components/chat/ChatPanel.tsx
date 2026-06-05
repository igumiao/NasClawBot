import { type FormEvent, useEffect, useReducer, useRef, useState } from "react";
import { chatApi } from "../../api/chatApi";
import { chatInitialState, chatReducer, createSessionId } from "../../state/chatState";
import { ApprovalCard } from "./ApprovalCard";
import { ErrorCard } from "./ErrorCard";
import { ReceiptCard } from "./ReceiptCard";
import { SearchResultCard } from "./SearchResultCard";
import { ToolActivityCard } from "./ToolActivityCard";

type ChatPanelProps = {
  id: string;
  labelledBy: string;
  onDownloadSubmitted?: (receipt: Record<string, unknown>) => void;
};

const ACTIVE_AGENT_SESSION_KEY = "nasclawbot-active-agent-session";

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

function storedSessionId(): string | null {
  try {
    return globalThis.sessionStorage?.getItem(ACTIVE_AGENT_SESSION_KEY) || null;
  } catch {
    return null;
  }
}

function persistSessionId(sessionId: string): void {
  try {
    globalThis.sessionStorage?.setItem(ACTIVE_AGENT_SESSION_KEY, sessionId);
  } catch {
    // The chat still works when browser storage is unavailable.
  }
}

export function ChatPanel({ id, labelledBy, onDownloadSubmitted }: ChatPanelProps) {
  const [draft, setDraft] = useState("");
  const initialStoredSession = useRef(storedSessionId());
  const restoreStarted = useRef(false);
  const endRef = useRef<HTMLDivElement>(null);
  const [state, dispatch] = useReducer(
    chatReducer,
    initialStoredSession.current ?? createSessionId(),
    chatInitialState
  );

  const inputBlocked = state.isSubmitting || state.isRestoring || state.pendingApproval !== null;

  useEffect(() => {
    persistSessionId(state.sessionId);
  }, [state.sessionId]);

  useEffect(() => {
    if (!initialStoredSession.current || restoreStarted.current) return;
    restoreStarted.current = true;
    dispatch({ type: "session_restore_started" });

    void chatApi.fetchAgentSession(initialStoredSession.current)
      .then((response) => dispatch({ type: "session_restored", response }))
      .catch((error: unknown) => {
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
  }, []);

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

  useEffect(() => {
    endRef.current?.scrollIntoView?.({ block: "end", behavior: "smooth" });
  }, [state.messages.length]);

  async function sendAgentMessage(message: string) {
    if (!message || inputBlocked) return;

    dispatch({ type: "user_submitted", text: message });
    try {
      const response = await chatApi.sendAgentMessage(state.sessionId, message);
      dispatch({ type: "chat_response_received", response });
    } catch (error) {
      dispatch({
        type: "request_failed",
        title: "发送失败",
        detail: errorDetail(error)
      });
    }
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const message = draft.trim();
    if (!message || inputBlocked) return;
    setDraft("");
    await sendAgentMessage(message);
  }

  async function handleDownloadRequest(torrentId: string) {
    await sendAgentMessage(`请下载 M-Team torrent id ${torrentId}`);
  }

  async function handleApproval(action: "approve" | "deny") {
    const approval = state.pendingApproval;
    if (!approval || state.isSubmitting) return;

    dispatch({ type: "approval_started" });
    try {
      const response = action === "approve"
        ? await chatApi.approveAgentCall(state.sessionId, approval.approval_id)
        : await chatApi.denyAgentCall(state.sessionId, approval.approval_id);
      dispatch({ type: "approval_response_received", response });
      if (response.receipt) onDownloadSubmitted?.(response.receipt);
    } catch (error) {
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
        title: action === "approve" ? "批准失败" : "拒绝失败",
        detail: errorDetail(error),
        clearApproval: status === 409
      });
    }
  }

  return (
    <section className="chat-panel" id={id} role="tabpanel" aria-labelledby={labelledBy}>
      <div className="chat-thread">
        {state.messages.length === 0 ? (
          <div className="chat-empty">
            <h1>今天想看什么？</h1>
            <p>{state.isRestoring ? "正在恢复 Agent 会话..." : "输入媒体需求"}</p>
          </div>
        ) : (
          <div className="chat-message-list">
            {state.messages.map((message) => {
              switch (message.kind) {
                case "user":
                  return (
                    <div key={message.id} className="chat-bubble-row" data-kind="user">
                      <div className="chat-bubble" data-kind="user">
                        {message.text}
                      </div>
                    </div>
                  );
                case "assistant":
                  return (
                    <div key={message.id} className="chat-bubble-row" data-kind="assistant">
                      <div className="chat-bubble" data-kind="assistant">
                        {message.text}
                      </div>
                    </div>
                  );
                case "tool_activity":
                  return <ToolActivityCard key={message.id} toolCall={message.toolCall} />;
                case "search_results":
                  return (
                    <SearchResultCard
                      key={message.id}
                      results={message.results}
                      isSubmitting={inputBlocked}
                      onDownload={handleDownloadRequest}
                    />
                  );
                case "approval":
                  return (
                    <ApprovalCard
                      key={message.id}
                      approval={message.approval}
                      status={message.status}
                      isSubmitting={state.isSubmitting}
                      onApprove={() => void handleApproval("approve")}
                      onDeny={() => void handleApproval("deny")}
                    />
                  );
                case "receipt":
                  return <ReceiptCard key={message.id} receipt={message.receipt} />;
                case "error":
                  return <ErrorCard key={message.id} title={message.title} detail={message.detail} />;
                default:
                  return null;
              }
            })}
            <div ref={endRef} />
          </div>
        )}
      </div>
      <form className="composer-shell" onSubmit={handleSubmit}>
        <textarea
          aria-label="媒体需求"
          placeholder={state.pendingApproval ? "请先批准或拒绝当前下载请求" : "输入媒体需求，例如：找做种最多的 Dune 2 电影"}
          value={draft}
          disabled={inputBlocked}
          onChange={(event) => setDraft(event.target.value)}
        />
        <button type="submit" aria-label="发送" disabled={inputBlocked || draft.trim().length === 0}>
          ↑
        </button>
      </form>
    </section>
  );
}
