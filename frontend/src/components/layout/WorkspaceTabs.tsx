import type { WorkspaceTab } from "../../state/uiState";

const tabs: Array<{ id: WorkspaceTab; label: string }> = [
  { id: "chat", label: "Chat" },
  { id: "downloads", label: "Downloads" },
  { id: "memory", label: "记忆" },
  { id: "free-torrents", label: "刷流" },
  { id: "settings", label: "状态" }
];

export function getWorkspaceTabId(tab: WorkspaceTab) {
  return `workspace-tab-${tab}`;
}

export function getWorkspacePanelId(tab: WorkspaceTab) {
  return `workspace-panel-${tab}`;
}

export function WorkspaceTabs({
  activeTab,
  onTabChange
}: {
  activeTab: WorkspaceTab;
  onTabChange: (tab: WorkspaceTab) => void;
}) {
  function moveToTab(nextTab: WorkspaceTab, tablist: HTMLDivElement) {
    onTabChange(nextTab);
    tablist.querySelector<HTMLButtonElement>(`#${getWorkspaceTabId(nextTab)}`)?.focus();
  }

  function handleKeyDown(event: React.KeyboardEvent<HTMLButtonElement>, tab: WorkspaceTab) {
    const currentIndex = tabs.findIndex((item) => item.id === tab);
    const lastIndex = tabs.length - 1;
    let nextIndex: number | undefined;

    if (event.key === "ArrowRight") {
      nextIndex = currentIndex === lastIndex ? 0 : currentIndex + 1;
    } else if (event.key === "ArrowLeft") {
      nextIndex = currentIndex === 0 ? lastIndex : currentIndex - 1;
    } else if (event.key === "Home") {
      nextIndex = 0;
    } else if (event.key === "End") {
      nextIndex = lastIndex;
    }

    if (nextIndex === undefined) {
      return;
    }

    event.preventDefault();
    moveToTab(tabs[nextIndex].id, event.currentTarget.parentElement as HTMLDivElement);
  }

  return (
    <div className="workspace-tabs" role="tablist" aria-label="Workspace">
      {tabs.map((tab) => (
        <button
          key={tab.id}
          id={getWorkspaceTabId(tab.id)}
          className="workspace-tab"
          data-active={activeTab === tab.id}
          role="tab"
          type="button"
          tabIndex={activeTab === tab.id ? 0 : -1}
          aria-controls={getWorkspacePanelId(tab.id)}
          aria-selected={activeTab === tab.id}
          onClick={() => onTabChange(tab.id)}
          onKeyDown={(event) => handleKeyDown(event, tab.id)}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}
