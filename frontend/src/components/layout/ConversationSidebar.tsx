export function ConversationSidebar() {
  return (
    <aside className="conversation-sidebar" aria-label="会话列表">
      <div className="brand-row">
        <div className="brand-mark">N</div>
        <div>
          <div className="brand-title">NasClawBot</div>
          <div className="brand-subtitle">Media assistant</div>
        </div>
      </div>
      <div className="sidebar-section">
        <button className="new-chat-button" type="button" disabled>
          新会话
        </button>
      </div>
      <div className="sidebar-section">
        <div className="sidebar-label">当前</div>
        <div className="conversation-item" aria-current="true">
          <div className="conversation-item-title">
            临时搜索会话
            <span className="online-dot" aria-hidden="true" />
          </div>
          <div className="conversation-item-meta">会话历史后续支持</div>
        </div>
      </div>
      <div className="sidebar-section">
        <div className="sidebar-label">历史</div>
        <p className="sidebar-empty">还没有历史会话。这里先保留空间。</p>
      </div>
    </aside>
  );
}
