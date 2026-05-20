export type WorkspaceTab = "chat" | "downloads" | "settings";

export type UiState = {
  activeTab: WorkspaceTab;
  sidebarCollapsed: boolean;
};

export const uiInitialState: UiState = {
  activeTab: "chat",
  sidebarCollapsed: false
};
