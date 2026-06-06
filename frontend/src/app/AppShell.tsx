import { useEffect, useState } from "react";
import { ChatPanel } from "../components/chat/ChatPanel";
import { DownloadsPanel } from "../components/downloads/DownloadsPanel";
import { ConversationSidebar } from "../components/layout/ConversationSidebar";
import { WorkspaceTabs } from "../components/layout/WorkspaceTabs";
import { SettingsPanel } from "../components/settings/SettingsPanel";
import type { WorkspaceTab } from "../state/uiState";

function panelStyle(active: boolean): React.CSSProperties {
  return { display: active ? undefined : "none", height: "100%" };
}

type BackendState = "checking" | "online" | "offline";

export function AppShell() {
  const [activeTab, setActiveTab] = useState<WorkspaceTab>("chat");
  const [downloadRefreshSignal, setDownloadRefreshSignal] = useState(0);
  const [backendState, setBackendState] = useState<BackendState>("checking");

  useEffect(() => {
    let cancelled = false;

    async function check() {
      try {
        const response = await fetch("/health", { signal: AbortSignal.timeout(5000) });
        if (!cancelled) setBackendState(response.ok ? "online" : "offline");
      } catch {
        if (!cancelled) setBackendState("offline");
      }
    }

    check();
    const interval = setInterval(check, 30_000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  const statusLabel =
    backendState === "online" ? "Backend online" :
    backendState === "offline" ? "Backend offline" :
    "Checking...";

  const dotClass =
    backendState === "online" ? "online-dot" :
    backendState === "offline" ? "offline-dot" :
    "online-dot checking-dot";

  return (
    <div className="app-shell">
      <ConversationSidebar />
      <main className="workspace-shell">
        <header className="workspace-topbar">
          <WorkspaceTabs activeTab={activeTab} onTabChange={setActiveTab} />
          <div className="backend-status">
            <span className={dotClass} aria-hidden="true" />
            <span className="backend-status-text">{statusLabel}</span>
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
