export type WorkspaceTab = "chat" | "downloads" | "settings" | "free-torrents" | "memory";

export type UiState = {
  activeTab: WorkspaceTab;
  sidebarCollapsed: boolean;
};

export const uiInitialState: UiState = {
  activeTab: "chat",
  sidebarCollapsed: false
};
