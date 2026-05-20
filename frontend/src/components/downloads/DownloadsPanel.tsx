import { useCallback, useEffect, useReducer } from "react";
import { downloadsApi } from "../../api/downloadsApi";
import { downloadsInitialState, downloadsReducer, visibleTorrents } from "../../state/downloadsState";
import type { TorrentAction } from "../../types/api";

type DownloadsPanelProps = {
  id: string;
  labelledBy: string;
  refreshSignal?: number;
};

function errorDetail(error: unknown): string {
  if (error instanceof Error && error.message) {
    return error.message;
  }
  return "请求失败，请稍后重试。";
}

function formatProgress(progress: number): string {
  return `${Math.round(progress * 100)}%`;
}

function formatRatio(ratio: number): string {
  return ratio.toFixed(2);
}

function stateLabel(state: string): string {
  switch (state) {
    case "pausedDL":
    case "pausedUP":
    case "stoppedDL":
    case "stoppedUP":
      return "已暂停";
    case "uploading":
    case "queuedUP":
    case "stalledUP":
    case "forcedUP":
    case "checkingUP":
      return "做种中";
    case "downloading":
    case "queuedDL":
    case "stalledDL":
    case "forcedDL":
    case "metaDL":
      return "下载中";
    default:
      return state;
  }
}

export function DownloadsPanel({ id, labelledBy, refreshSignal = 0 }: DownloadsPanelProps) {
  const [state, dispatch] = useReducer(downloadsReducer, downloadsInitialState);
  const items = visibleTorrents(state);

  const loadDetail = useCallback(async (hash: string) => {
    const detail = await downloadsApi.getTorrent(hash);
    dispatch({ type: "detail_loaded", detail });
  }, []);

  const refreshList = useCallback(
    async (preferredHash?: string | null) => {
      dispatch({ type: "refresh_started" });

      try {
        const response = await downloadsApi.listTorrents();
        dispatch({ type: "list_loaded", items: response.items });

        const nextHash = response.items.find((item) => item.hash === preferredHash)?.hash ?? response.items[0]?.hash;
        if (nextHash) {
          await loadDetail(nextHash);
        }
      } catch (error) {
        dispatch({ type: "request_failed", detail: errorDetail(error) });
      }
    },
    [loadDetail],
  );

  useEffect(() => {
    void refreshList(state.selectedTorrentHash);
  }, [refreshList, refreshSignal]);

  async function handleSelect(hash: string) {
    if (state.isRefreshing || state.actionPendingHash === hash || state.selectedTorrentHash === hash) {
      return;
    }

    dispatch({ type: "torrent_selected", hash });
    try {
      await loadDetail(hash);
    } catch (error) {
      dispatch({ type: "request_failed", detail: errorDetail(error) });
    }
  }

  async function handleAction(action: TorrentAction) {
    const hash = state.selectedTorrentHash;
    if (!hash || state.isRefreshing || state.actionPendingHash) {
      return;
    }

    if (action === "delete" && !window.confirm("确认删除这个 qB 任务？")) {
      return;
    }

    dispatch({ type: "action_started", hash });
    try {
      await downloadsApi.runTorrentAction(hash, action, { deleteFiles: action === "delete" });
      dispatch({ type: "action_finished" });
      await refreshList(hash);
    } catch (error) {
      dispatch({ type: "request_failed", detail: errorDetail(error) });
    }
  }

  const selectedHash = state.selectedTorrentHash;
  const actionDisabled = state.isRefreshing || !selectedHash || state.actionPendingHash !== null;

  return (
    <section className="downloads-panel" id={id} role="tabpanel" aria-labelledby={labelledBy}>
      <div className="downloads-surface">
        <div className="downloads-toolbar">
          <div className="downloads-toolbar-copy">
            <h1>下载任务</h1>
            <p>查看 qBittorrent 任务、状态和详情。</p>
          </div>
          <button type="button" className="downloads-refresh-button" onClick={() => void refreshList(selectedHash)} disabled={state.isRefreshing}>
            刷新
          </button>
        </div>

        {state.lastError ? <div className="inline-error">{state.lastError}</div> : null}

        {!state.isRefreshing && items.length === 0 ? (
          <div className="downloads-empty">当前没有可显示的下载任务。</div>
        ) : (
          <div className="downloads-grid">
            <div className="downloads-list" role="list" aria-label="下载任务列表">
              {items.map((item) => (
                <button
                  key={item.hash}
                  type="button"
                  role="listitem"
                  className="downloads-row"
                  data-selected={item.hash === selectedHash ? "true" : "false"}
                  onClick={() => void handleSelect(item.hash)}
                  disabled={state.isRefreshing || state.actionPendingHash === item.hash}
                >
                  <span className="downloads-row-name">{item.name}</span>
                  <span className="downloads-row-meta">{stateLabel(item.state)}</span>
                  <span className="downloads-row-progress">{formatProgress(item.progress)}</span>
                </button>
              ))}
            </div>

            <div className="downloads-detail">
              {state.torrentDetail ? (
                <>
                  <div className="downloads-detail-block">
                    <div className="downloads-detail-label">保存路径</div>
                    <div className="downloads-detail-value">{state.torrentDetail.save_path}</div>
                  </div>
                  <div className="downloads-detail-block">
                    <div className="downloads-detail-label">分享率</div>
                    <div className="downloads-detail-value">{formatRatio(state.torrentDetail.share_ratio)}</div>
                  </div>
                  <div className="downloads-actions">
                    <button type="button" onClick={() => void handleAction("pause")} disabled={actionDisabled}>
                      暂停
                    </button>
                    <button type="button" onClick={() => void handleAction("resume")} disabled={actionDisabled}>
                      继续
                    </button>
                    <button type="button" onClick={() => void handleAction("recheck")} disabled={actionDisabled}>
                      校验
                    </button>
                    <button type="button" onClick={() => void handleAction("reannounce")} disabled={actionDisabled}>
                      重新汇报
                    </button>
                    <button type="button" className="danger" onClick={() => void handleAction("delete")} disabled={actionDisabled}>
                      删除
                    </button>
                  </div>
                </>
              ) : (
                <div className="downloads-empty-detail">选择一个任务以查看详情。</div>
              )}
            </div>
          </div>
        )}
      </div>
    </section>
  );
}
