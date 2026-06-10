import { type FormEvent, type KeyboardEvent, useCallback, useEffect, useRef, useState } from "react";
import { useAgentChatSession } from "../../hooks/useAgentChatSession";
import { ApprovalCard } from "./ApprovalCard";
import { ErrorCard } from "./ErrorCard";
import { MarkdownContent } from "./MarkdownContent";
import { ReceiptCard } from "./ReceiptCard";
import { SearchResultCard } from "./SearchResultCard";
import { ToolActivityCard } from "./ToolActivityCard";

type ChatPanelProps = {
  id: string;
  labelledBy: string;
  activeSessionId: string | null;
  onActiveSessionChange: (sessionId: string | null) => void;
  onDownloadSubmitted?: (receipt: Record<string, unknown>) => void;
  onSessionActivity?: (sessionId: string) => void;
};

export function ChatPanel({
  id,
  labelledBy,
  activeSessionId,
  onActiveSessionChange,
  onDownloadSubmitted,
  onSessionActivity
}: ChatPanelProps) {
  const [draft, setDraft] = useState("");
  const endRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const { state, inputBlocked, sendAgentMessage, requestDownload, decideApproval } = useAgentChatSession({
    activeSessionId,
    onActiveSessionChange,
    onDownloadSubmitted,
    onSessionActivity
  });

  useEffect(() => {
    endRef.current?.scrollIntoView?.({ block: "end", behavior: "smooth" });
  }, [state.messages.length]);

  useEffect(() => {
    setDraft("");
  }, [activeSessionId]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const message = draft.trim();
    if (!message || inputBlocked) return;
    setDraft("");
    await sendAgentMessage(message);
  }

  const handleKeyDown = useCallback((event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key !== "Enter") return;

    if (event.ctrlKey || event.metaKey) {
      // Ctrl+Enter / Cmd+Enter: insert newline at cursor
      event.preventDefault();
      const textarea = event.currentTarget;
      const { selectionStart, selectionEnd } = textarea;
      setDraft((prev) => {
        const next = prev.slice(0, selectionStart) + "\n" + prev.slice(selectionEnd);
        // Restore cursor after the inserted newline on next tick
        requestAnimationFrame(() => {
          textarea.selectionStart = textarea.selectionEnd = selectionStart + 1;
        });
        return next;
      });
    } else {
      // Enter (no modifier): send message
      event.preventDefault();
      const form = event.currentTarget.form;
      if (form) form.requestSubmit();
    }
  }, []);

  async function handleDownloadRequest(torrentId: string) {
    await requestDownload(torrentId);
  }

  async function handleApproval(action: "approve" | "deny") {
    await decideApproval(action);
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
                        <MarkdownContent content={message.text} />
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
          ref={textareaRef}
          aria-label="媒体需求"
          placeholder={state.pendingApproval ? "请先批准或拒绝当前下载请求" : "输入媒体需求，Enter 发送，Ctrl+Enter 换行"}
          value={draft}
          disabled={inputBlocked}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={handleKeyDown}
        />
        <button type="submit" aria-label="发送" disabled={inputBlocked || draft.trim().length === 0}>
          ↑
        </button>
      </form>
    </section>
  );
}
