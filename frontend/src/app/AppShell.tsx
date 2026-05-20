import { useState } from "react";
import { ChatPanel } from "../components/chat/ChatPanel";
import { DownloadsPanel } from "../components/downloads/DownloadsPanel";
import { ConversationSidebar } from "../components/layout/ConversationSidebar";
import { WorkspaceTabs } from "../components/layout/WorkspaceTabs";
import { SettingsPanel } from "../components/settings/SettingsPanel";
import type { WorkspaceTab } from "../state/uiState";

export function AppShell() {
  const [activeTab, setActiveTab] = useState<WorkspaceTab>("chat");

  return (
    <div className="app-shell">
      <ConversationSidebar />
      <main className="workspace-shell">
        <header className="workspace-topbar">
          <WorkspaceTabs activeTab={activeTab} onTabChange={setActiveTab} />
          <div className="backend-status">
            <span className="online-dot" aria-hidden="true" />
            Backend online
          </div>
        </header>
        {activeTab === "chat" && <ChatPanel />}
        {activeTab === "downloads" && <DownloadsPanel />}
        {activeTab === "settings" && <SettingsPanel />}
      </main>
    </div>
  );
}
