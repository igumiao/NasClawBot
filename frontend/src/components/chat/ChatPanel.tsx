import { type FormEvent, type KeyboardEvent, useCallback, useEffect, useRef, useState } from "react";
import { useAgentChatSession } from "../../hooks/useAgentChatSession";
import { useTaskEvents } from "../../state/taskEventsState";
import { ApprovalCard } from "./ApprovalCard";
import { ErrorCard } from "./ErrorCard";
import type { ContextUsage, SessionUsage } from "../../types/api";
import { MarkdownContent } from "./MarkdownContent";
import { ReceiptCard } from "./ReceiptCard";
import { SearchResultCard } from "./SearchResultCard";
import { TaskEventCard } from "./TaskEventCard";
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

  const { events: taskEvents, acknowledge: acknowledgeEvent, acknowledgeAll: acknowledgeAllEvents } = useTaskEvents(
    activeSessionId,
  );

  useEffect(() => {
    endRef.current?.scrollIntoView?.({ block: "end", behavior: "smooth" });
  }, [state.messages.length]);

  useEffect(() => {
    setDraft("");
  }, [activeSessionId]);

  // Auto-grow the textarea as content wraps, capped by CSS max-height
  useEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;
    textarea.style.height = "auto";
    textarea.style.height = `${textarea.scrollHeight}px`;
  }, [draft]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const message = draft.trim();
    if (!message || inputBlocked) return;
    setDraft("");
    await sendAgentMessage(message);
  }

  const handleKeyDown = useCallback((event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key !== "Enter") return;

    if (event.ctrlKey || event.metaKey || event.shiftKey) {
      // Ctrl+Enter / Cmd+Enter / Shift+Enter: insert newline at cursor
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

  async function handleApproval(action: "approve" | "approve_and_grant_session" | "deny") {
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
            {taskEvents != null && taskEvents.length > 0 && (
              <div className="task-events-section" role="feed" aria-label="后台任务事件">
                <div className="task-events-header">
                  <span className="task-events-heading">后台任务</span>
                  {taskEvents.length > 1 && (
                    <button
                      className="task-events-dismiss-all"
                      onClick={acknowledgeAllEvents}
                      aria-label="忽略所有事件"
                    >
                      全部忽略
                    </button>
                  )}
                </div>
                {taskEvents.map((event) => (
                  <TaskEventCard
                    key={event.event_id}
                    event={event}
                    onAcknowledge={acknowledgeEvent}
                  />
                ))}
              </div>
            )}
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
                case "reasoning":
                  return (
                    <details key={message.id} className="chat-reasoning">
                      <summary className="chat-reasoning-summary">
                        {message.text.slice(0, 80)}{message.text.length > 80 ? "…" : ""}
                      </summary>
                      <div className="chat-reasoning-body">
                        <MarkdownContent content={message.text} />
                        {message.reasoningContent ? (
                          <details className="chat-reasoning-chain">
                            <summary>思考链 (thinking)</summary>
                            <pre>{message.reasoningContent}</pre>
                          </details>
                        ) : null}
                      </div>
                    </details>
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
                      onApproveWithGrant={() => void handleApproval("approve_and_grant_session")}
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
      {state.contextUsage && (
        <ContextBar usage={state.contextUsage} sessionUsage={state.sessionUsage} />
      )}
      <form className="composer-shell" onSubmit={handleSubmit}>
        <textarea
          ref={textareaRef}
          aria-label="媒体需求"
          placeholder={state.pendingApproval ? "请先批准或拒绝当前下载请求" : "输入媒体需求，Enter 发送，Ctrl/Shift+Enter 换行"}
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

function ContextBar({ usage, sessionUsage }: { usage: ContextUsage; sessionUsage: SessionUsage | null }) {
  const pct = calculateContextPct(usage);
  const cacheHitRate = calculateCacheHitRate(usage);
  const sessionCacheHitRate = sessionUsage ? calculateSessionCacheHitRate(sessionUsage) : null;
  const color = pct > 70 ? "var(--color-danger, #ef4444)"
    : pct > 50 ? "var(--color-warning, #f59e0b)"
    : "var(--color-success, #22c55e)";

  const hoverTitle = [
    `${usage.prompt_tokens.toLocaleString()} / ${usage.context_window.toLocaleString()} tokens`,
    cacheHitRate != null ? `上次请求缓存 ${cacheHitRate}%` : null,
    sessionCacheHitRate != null ? `本会话累计缓存 ${sessionCacheHitRate}%` : null,
    sessionUsage ? `模型调用 ${sessionUsage.model_calls.toLocaleString()} 次` : null,
  ].filter(Boolean).join(" · ");

  return (
    <div className="context-bar" tabIndex={0} aria-label={hoverTitle}>
      <div className="context-bar-track">
        <div
          className="context-bar-fill"
          style={{ width: `${Math.min(pct, 100)}%`, backgroundColor: color }}
        />
      </div>
      <span className="context-bar-label" style={{ color }}>{pct}%</span>
      <span className="context-bar-metric">
        上次 {cacheHitRate != null ? `${cacheHitRate}%` : "--"}
      </span>
      <span className="context-bar-metric">
        累计 {sessionCacheHitRate != null ? `${sessionCacheHitRate}%` : "--"}
      </span>
      <span className="context-bar-tooltip" role="tooltip">{hoverTitle}</span>
    </div>
  );
}

function calculateContextPct(usage: ContextUsage) {
  if (usage.context_window <= 0) return 0;
  return Math.round((usage.prompt_tokens / usage.context_window) * 1000) / 10;
}

function calculateCacheHitRate(usage: ContextUsage) {
  const total = usage.cache_hit_tokens + usage.cache_miss_tokens;
  if (total <= 0) return null;
  return Math.round((usage.cache_hit_tokens / total) * 1000) / 10;
}

function calculateSessionCacheHitRate(usage: SessionUsage) {
  const total = usage.total_cache_hit_tokens + usage.total_cache_miss_tokens;
  if (total <= 0) return null;
  return Math.round((usage.total_cache_hit_tokens / total) * 1000) / 10;
}
