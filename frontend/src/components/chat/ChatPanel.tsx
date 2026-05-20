import { type FormEvent, useReducer, useRef, useState } from "react";
import { chatApi } from "../../api/chatApi";
import { chatInitialState, chatReducer } from "../../state/chatState";
import type { ConfirmationPayload } from "../../types/api";
import { CandidateCard } from "./CandidateCard";
import { ErrorCard } from "./ErrorCard";
import { ReceiptCard } from "./ReceiptCard";

type ChatPanelProps = {
  id: string;
  labelledBy: string;
  onDownloadSubmitted?: (receipt: Record<string, unknown>) => void;
};

function errorDetail(error: unknown): string {
  if (error instanceof Error && error.message) {
    return error.message;
  }
  return "请求失败，请稍后重试。";
}

function selectedResultForPayload(payload: ConfirmationPayload): string | null {
  return payload.selected_result_id ?? payload.recommended_result_id ?? payload.results[0]?.id ?? null;
}

export function ChatPanel({ id, labelledBy, onDownloadSubmitted }: ChatPanelProps) {
  const [draft, setDraft] = useState("");
  const [state, dispatch] = useReducer(chatReducer, undefined, () => chatInitialState());
  const composerRef = useRef<HTMLTextAreaElement>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const message = draft.trim();
    if (!message || state.isSubmitting) {
      return;
    }

    setDraft("");
    dispatch({ type: "user_submitted", text: message });

    try {
      const response = await chatApi.sendMessage(state.sessionId, message);
      dispatch({ type: "chat_response_received", response });
    } catch (error) {
      dispatch({
        type: "request_failed",
        title: "发送失败",
        detail: errorDetail(error)
      });
    }
  }

  async function handleApprove() {
    if (state.isSubmitting || !state.pendingConfirmation) {
      return;
    }

    dispatch({ type: "request_started" });

    try {
      const response = await chatApi.confirmDownload(
        state.sessionId,
        state.pendingConfirmation,
        state.selectedResultId,
      );
      dispatch({ type: "confirm_response_received", response });
      if (response.receipt) {
        onDownloadSubmitted?.(response.receipt);
      }
    } catch (error) {
      dispatch({
        type: "request_failed",
        title: "确认失败",
        detail: errorDetail(error)
      });
    }
  }

  async function handleCancel() {
    if (state.isSubmitting || !state.pendingConfirmation) {
      return;
    }

    dispatch({ type: "request_started" });

    try {
      const response = await chatApi.cancel(state.sessionId);
      dispatch({ type: "confirm_response_received", response });
    } catch (error) {
      dispatch({
        type: "request_failed",
        title: "取消失败",
        detail: errorDetail(error)
      });
    }
  }

  function handleRewrite() {
    composerRef.current?.focus();
  }

  return (
    <section className="chat-panel" id={id} role="tabpanel" aria-labelledby={labelledBy}>
      <div className="chat-thread">
        {state.messages.length === 0 ? (
          <div className="chat-empty">
            <h1>今天想看什么？</h1>
            <p>输入媒体需求</p>
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
                case "candidate":
                  const isActiveConfirmation = state.pendingConfirmation === message.payload;
                  return (
                    <CandidateCard
                      key={message.id}
                      payload={message.payload}
                      selectedResultId={
                        isActiveConfirmation ? state.selectedResultId : selectedResultForPayload(message.payload)
                      }
                      isSubmitting={state.isSubmitting && isActiveConfirmation}
                      isDisabled={!isActiveConfirmation}
                      onSelect={(selectedResultId) => {
                        if (isActiveConfirmation) {
                          dispatch({ type: "selected_result_changed", selectedResultId });
                        }
                      }}
                      onApprove={handleApprove}
                      onCancel={handleCancel}
                      onRewrite={handleRewrite}
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
          </div>
        )}
      </div>
      <form className="composer-shell" onSubmit={handleSubmit}>
        <textarea
          ref={composerRef}
          aria-label="媒体需求"
          placeholder="输入媒体需求，例如：我想看一部 4K 科幻电影..."
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
        />
        <button type="submit" aria-label="发送" disabled={state.isSubmitting || draft.trim().length === 0}>
          ↑
        </button>
      </form>
    </section>
  );
}
