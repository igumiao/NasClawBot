import { useState } from "react";
import { ChatPanel } from "../components/chat/ChatPanel";
import { DownloadsPanel } from "../components/downloads/DownloadsPanel";
import { ConversationSidebar } from "../components/layout/ConversationSidebar";
import { getWorkspacePanelId, getWorkspaceTabId, WorkspaceTabs } from "../components/layout/WorkspaceTabs";
import { SettingsPanel } from "../components/settings/SettingsPanel";
import type { WorkspaceTab } from "../state/uiState";

export function AppShell() {
  const [activeTab, setActiveTab] = useState<WorkspaceTab>("chat");
  const [downloadRefreshSignal, setDownloadRefreshSignal] = useState(0);
  const activePanelProps = {
    id: getWorkspacePanelId(activeTab),
    labelledBy: getWorkspaceTabId(activeTab)
  };

  return (
    <div className="app-shell">
      <ConversationSidebar />
      <main className="workspace-shell">
        <header className="workspace-topbar">
          <WorkspaceTabs activeTab={activeTab} onTabChange={setActiveTab} />
          <div className="backend-status">
            <span className="online-dot" aria-hidden="true" />
            <span className="backend-status-text">Backend online</span>
          </div>
        </header>
        {activeTab === "chat" && (
          <ChatPanel
            {...activePanelProps}
            onDownloadSubmitted={() => setDownloadRefreshSignal((value) => value + 1)}
          />
        )}
        {activeTab === "downloads" && (
          <DownloadsPanel {...activePanelProps} refreshSignal={downloadRefreshSignal} />
        )}
        {activeTab === "settings" && <SettingsPanel {...activePanelProps} />}
      </main>
    </div>
  );
}
