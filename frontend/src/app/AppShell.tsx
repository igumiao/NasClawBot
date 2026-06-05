import { useState } from "react";
import { ChatPanel } from "../components/chat/ChatPanel";
import { DownloadsPanel } from "../components/downloads/DownloadsPanel";
import { ConversationSidebar } from "../components/layout/ConversationSidebar";
import { WorkspaceTabs } from "../components/layout/WorkspaceTabs";
import { SettingsPanel } from "../components/settings/SettingsPanel";
import type { WorkspaceTab } from "../state/uiState";

function panelStyle(active: boolean): React.CSSProperties {
  return { display: active ? undefined : "none" };
}

export function AppShell() {
  const [activeTab, setActiveTab] = useState<WorkspaceTab>("chat");
  const [downloadRefreshSignal, setDownloadRefreshSignal] = useState(0);

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
        <div style={panelStyle(activeTab === "chat")}>
          <ChatPanel
            id="workspace-panel-chat"
            labelledBy="workspace-tab-chat"
            onDownloadSubmitted={() => setDownloadRefreshSignal((value) => value + 1)}
          />
        </div>
        <div style={panelStyle(activeTab === "downloads")}>
          <DownloadsPanel
            id="workspace-panel-downloads"
            labelledBy="workspace-tab-downloads"
            refreshSignal={downloadRefreshSignal}
          />
        </div>
        <div style={panelStyle(activeTab === "settings")}>
          <SettingsPanel
            id="workspace-panel-settings"
            labelledBy="workspace-tab-settings"
          />
        </div>
      </main>
    </div>
  );
}
