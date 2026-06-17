import { type KeyboardEvent, useEffect, useRef, useState } from "react";
import { History, MoreHorizontal, PanelLeftClose, PanelLeftOpen, Plus, Trash2 } from "lucide-react";
import type { AgentSessionSummary } from "../../types/api";

type ConversationSidebarProps = {
  activeSessionId: string | null;
  sessions: AgentSessionSummary[];
  isLoading: boolean;
  collapsed: boolean;
  onNewConversation: () => void;
  onSelectSession: (sessionId: string) => void;
  onToggleCollapsed: () => void;
  onRenameSession: (sessionId: string, title: string) => Promise<void>;
  onDeleteSession: (sessionId: string) => Promise<void>;
};

function sessionTitle(session: AgentSessionSummary): string {
  const rawTitle = session.metadata.title;
  if (typeof rawTitle === "string" && rawTitle.trim()) {
    return rawTitle.trim();
  }

  const savedAt = new Date(session.saved_at);
  if (!Number.isNaN(savedAt.getTime())) {
    return `Agent 会话 ${savedAt.toLocaleDateString(undefined, { month: "2-digit", day: "2-digit" })} ${savedAt.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}`;
  }
  return `Agent 会话 ${session.session_id.slice(0, 8)}`;
}

export function ConversationSidebar({
  activeSessionId,
  sessions,
  isLoading,
  collapsed,
  onNewConversation,
  onSelectSession,
  onToggleCollapsed,
  onRenameSession,
  onDeleteSession
}: ConversationSidebarProps) {
  const [menuSessionId, setMenuSessionId] = useState<string | null>(null);
  const [editingSessionId, setEditingSessionId] = useState<string | null>(null);
  const [renameDraft, setRenameDraft] = useState("");
  const [deleteSession, setDeleteSession] = useState<AgentSessionSummary | null>(null);
  const [isMutating, setIsMutating] = useState(false);
  const renameInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (editingSessionId) {
      renameInputRef.current?.focus();
      renameInputRef.current?.select();
    }
  }, [editingSessionId]);

  function beginRename(session: AgentSessionSummary): void {
    setMenuSessionId(null);
    setEditingSessionId(session.session_id);
    setRenameDraft(sessionTitle(session));
  }

  async function commitRename(session: AgentSessionSummary): Promise<void> {
    const title = renameDraft.trim();
    setEditingSessionId(null);
    if (!title || title === sessionTitle(session)) return;

    setIsMutating(true);
    try {
      await onRenameSession(session.session_id, title);
    } finally {
      setIsMutating(false);
    }
  }

  function cancelRename(): void {
    setEditingSessionId(null);
    setRenameDraft("");
  }

  function handleRenameKeyDown(event: KeyboardEvent<HTMLInputElement>, session: AgentSessionSummary): void {
    if (event.key === "Enter") {
      event.preventDefault();
      void commitRename(session);
    }
    if (event.key === "Escape") {
      event.preventDefault();
      cancelRename();
    }
  }

  async function confirmDelete(): Promise<void> {
    if (!deleteSession) return;
    const sessionId = deleteSession.session_id;
    setIsMutating(true);
    try {
      await onDeleteSession(sessionId);
      setDeleteSession(null);
    } finally {
      setIsMutating(false);
    }
  }

  return (
    <aside className="conversation-sidebar" data-collapsed={collapsed} aria-label="会话列表">
      <div className="brand-row">
        {collapsed ? (
          <button
            className="brand-mark brand-mark-button"
            type="button"
            aria-label="展开侧边栏"
            title="展开侧边栏"
            onClick={onToggleCollapsed}
          >
            <img className="brand-mark-label" src="/brand-logo.png" alt="NasClawBot" />
            <PanelLeftOpen className="brand-mark-hover-icon" size={17} aria-hidden="true" />
          </button>
        ) : (
          <div className="brand-mark">
            <img src="/brand-logo.png" alt="NasClawBot" />
          </div>
        )}
        <div className="brand-copy">
          <div className="brand-title">NasClawBot</div>
          <div className="brand-subtitle">Media assistant</div>
        </div>
        {!collapsed ? (
          <button
            className="sidebar-icon-button sidebar-collapse-button"
            type="button"
            aria-label="收起侧边栏"
            title="收起侧边栏"
            onClick={onToggleCollapsed}
          >
            <PanelLeftClose size={17} />
          </button>
        ) : null}
      </div>
      <div className="sidebar-section">
        <button className="new-chat-button" type="button" title="新会话" onClick={onNewConversation}>
          <Plus size={16} aria-hidden="true" />
          <span className="sidebar-text">新会话</span>
        </button>
      </div>
      <div className="sidebar-section">
        <div className="sidebar-label">
          <History size={14} aria-hidden="true" />
          <span className="sidebar-text">历史</span>
        </div>
        {isLoading ? (
          <p className="sidebar-empty">正在加载历史对话...</p>
        ) : sessions.length === 0 ? (
          <div className="sidebar-empty-state">
            <p>暂无历史对话</p>
            <p>开始一个新的对话吧</p>
          </div>
        ) : (
          <div className="conversation-list" aria-label="历史对话">
            {sessions.map((session) => {
              const title = sessionTitle(session);
              const isActive = session.session_id === activeSessionId;
              const isEditing = session.session_id === editingSessionId;
              const isMenuOpen = session.session_id === menuSessionId;

              return (
                <div
                  key={session.session_id}
                  className="conversation-item"
                  data-active={isActive}
                  data-menu-open={isMenuOpen}
                >
                  {isEditing ? (
                    <input
                      ref={renameInputRef}
                      className="conversation-rename-input"
                      aria-label="重命名会话"
                      value={renameDraft}
                      disabled={isMutating}
                      onChange={(event) => setRenameDraft(event.target.value)}
                      onKeyDown={(event) => handleRenameKeyDown(event, session)}
                      onBlur={() => void commitRename(session)}
                    />
                  ) : (
                    <>
                      <button
                        className="conversation-item-main"
                        type="button"
                        aria-current={isActive ? "page" : undefined}
                        title={title}
                        onClick={() => onSelectSession(session.session_id)}
                      >
                        <span className="conversation-item-title">{title}</span>
                      </button>
                      <button
                        className="conversation-item-menu-button"
                        type="button"
                        aria-label={`更多操作：${title}`}
                        title="更多操作"
                        onClick={() => setMenuSessionId((current) => current === session.session_id ? null : session.session_id)}
                      >
                        <MoreHorizontal size={16} aria-hidden="true" />
                      </button>
                      {isMenuOpen ? (
                        <div className="conversation-menu" role="menu">
                          <button type="button" role="menuitem" onClick={() => beginRename(session)}>
                            重命名
                          </button>
                          <button
                            className="danger"
                            type="button"
                            role="menuitem"
                            onClick={() => {
                              setMenuSessionId(null);
                              setDeleteSession(session);
                            }}
                          >
                            删除
                          </button>
                        </div>
                      ) : null}
                    </>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
      {deleteSession ? (
        <div className="dialog-backdrop" role="presentation">
          <div className="confirm-dialog" role="dialog" aria-modal="true" aria-labelledby="delete-session-title">
            <div className="confirm-dialog-icon" aria-hidden="true">
              <Trash2 size={18} />
            </div>
            <div className="confirm-dialog-body">
              <h2 id="delete-session-title">确认删除该会话？</h2>
              <p>此操作不可恢复。</p>
            </div>
            <div className="confirm-dialog-actions">
              <button
                className="secondary-button"
                type="button"
                disabled={isMutating}
                onClick={() => setDeleteSession(null)}
              >
                取消
              </button>
              <button
                className="primary-button danger"
                type="button"
                disabled={isMutating}
                onClick={() => void confirmDelete()}
              >
                删除
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </aside>
  );
}
