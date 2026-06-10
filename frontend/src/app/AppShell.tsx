import { useCallback, useEffect, useState } from "react";
import { chatApi } from "../api/chatApi";
import { ChatPanel } from "../components/chat/ChatPanel";
import { DownloadsPanel } from "../components/downloads/DownloadsPanel";
import { ConversationSidebar } from "../components/layout/ConversationSidebar";
import { WorkspaceTabs } from "../components/layout/WorkspaceTabs";
import { SettingsPanel } from "../components/settings/SettingsPanel";
import { FreeTorrentsPanel } from "../components/free-torrents/FreeTorrentsPanel";
import { persistAgentSessionId, readStoredAgentSessionId } from "../state/agentSessionStorage";
import type { AgentSessionSummary } from "../types/api";
import type { WorkspaceTab } from "../state/uiState";

function panelStyle(active: boolean): React.CSSProperties {
  return { display: active ? undefined : "none", height: "100%" };
}

type BackendState = "checking" | "online" | "offline";
const SIDEBAR_COLLAPSED_KEY = "nasclawbot-sidebar-collapsed";

function readStoredSidebarCollapsed(): boolean {
  try {
    return globalThis.localStorage?.getItem(SIDEBAR_COLLAPSED_KEY) === "true";
  } catch {
    return false;
  }
}

function persistSidebarCollapsed(collapsed: boolean): void {
  try {
    globalThis.localStorage?.setItem(SIDEBAR_COLLAPSED_KEY, String(collapsed));
  } catch {
    // Layout still works when browser storage is unavailable.
  }
}

export function AppShell() {
  const [activeTab, setActiveTab] = useState<WorkspaceTab>("chat");
  const [activeAgentSessionId, setActiveAgentSessionId] = useState<string | null>(() => readStoredAgentSessionId());
  const [agentSessions, setAgentSessions] = useState<AgentSessionSummary[]>([]);
  const [isLoadingAgentSessions, setIsLoadingAgentSessions] = useState(true);
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(() => readStoredSidebarCollapsed());
  const [downloadRefreshSignal, setDownloadRefreshSignal] = useState(0);
  const [backendState, setBackendState] = useState<BackendState>("checking");

  useEffect(() => {
    persistAgentSessionId(activeAgentSessionId);
  }, [activeAgentSessionId]);

  useEffect(() => {
    if (activeTab === "downloads") {
      setDownloadRefreshSignal((n) => n + 1);
    }
  }, [activeTab]);

  useEffect(() => {
    persistSidebarCollapsed(isSidebarCollapsed);
  }, [isSidebarCollapsed]);

  const refreshAgentSessions = useCallback(async (signal?: AbortSignal) => {
    setIsLoadingAgentSessions(true);
    try {
      const response = await chatApi.listAgentSessions(signal);
      setAgentSessions(response.sessions);
    } catch (error) {
      if (signal?.aborted) return;
      setAgentSessions([]);
    } finally {
      if (!signal?.aborted) setIsLoadingAgentSessions(false);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void refreshAgentSessions(controller.signal);
    return () => controller.abort();
  }, [refreshAgentSessions]);

  const handleRenameSession = useCallback(async (sessionId: string, title: string) => {
    await chatApi.updateAgentSession(sessionId, { title });
    setAgentSessions((sessions) =>
      sessions.map((session) =>
        session.session_id === sessionId
          ? { ...session, metadata: { ...session.metadata, title } }
          : session
      )
    );
    void refreshAgentSessions();
  }, [refreshAgentSessions]);

  const handleDeleteSession = useCallback(async (sessionId: string) => {
    await chatApi.deleteAgentSession(sessionId);
    setAgentSessions((sessions) => sessions.filter((session) => session.session_id !== sessionId));
    if (activeAgentSessionId === sessionId) {
      setActiveAgentSessionId(null);
      setActiveTab("chat");
    }
    void refreshAgentSessions();
  }, [activeAgentSessionId, refreshAgentSessions]);

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
    <div className="app-shell" data-sidebar-collapsed={isSidebarCollapsed}>
      <ConversationSidebar
        activeSessionId={activeAgentSessionId}
        sessions={agentSessions}
        isLoading={isLoadingAgentSessions}
        collapsed={isSidebarCollapsed}
        onNewConversation={() => {
          setActiveAgentSessionId(null);
          setActiveTab("chat");
        }}
        onSelectSession={(sessionId) => {
          setActiveAgentSessionId(sessionId);
          setActiveTab("chat");
        }}
        onToggleCollapsed={() => setIsSidebarCollapsed((collapsed) => !collapsed)}
        onRenameSession={handleRenameSession}
        onDeleteSession={handleDeleteSession}
      />
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
            activeSessionId={activeAgentSessionId}
            onActiveSessionChange={setActiveAgentSessionId}
            onDownloadSubmitted={() => setDownloadRefreshSignal((value) => value + 1)}
            onSessionActivity={() => void refreshAgentSessions()}
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
        <div style={panelStyle(activeTab === "free-torrents")}>
          <FreeTorrentsPanel
            id="workspace-panel-free-torrents"
            labelledBy="workspace-tab-free-torrents"
          />
        </div>
      </main>
    </div>
  );
}
