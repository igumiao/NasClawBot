import { useCallback, useEffect, useMemo, useReducer, useState } from "react";
import { freeTorrentsReducer, freeTorrentsInitialState } from "../../state/freeTorrentsState";
import { mteamApi } from "../../api/mteamApi";
import { chatApi } from "../../api/chatApi";
import { settingsApi } from "../../api/settingsApi";
import type { FreeToppedTorrent } from "../../types/api";

type Props = { id: string; labelledBy: string };

function errorDetail(error: unknown): string {
  if (error instanceof Error) return error.message;
  return String(error);
}

function formatRemaining(raw: string | null): string {
  if (!raw) return "-";
  const end = new Date(raw.replace(" ", "T"));
  if (isNaN(end.getTime())) return raw.slice(0, 10);
  const now = new Date();
  const diffMs = end.getTime() - now.getTime();
  if (diffMs <= 0) return "已过期";
  const totalMinutes = Math.floor(diffMs / 60000);
  const days = Math.floor(totalMinutes / 1440);
  const hours = Math.floor((totalMinutes % 1440) / 60);
  if (days > 0) return `${days}天${hours}小时`;
  const mins = totalMinutes % 60;
  if (hours > 0) return `${hours}小时${mins}分`;
  return `${mins}分钟`;
}

export function FreeTorrentsPanel({ id, labelledBy }: Props) {
  const [state, dispatch] = useReducer(freeTorrentsReducer, freeTorrentsInitialState);
  const [downloadingIds, setDownloadingIds] = useState<Set<string>>(new Set());
  const [downloadedIds, setDownloadedIds] = useState<Set<string>>(new Set());

  useEffect(() => {
    const controller = new AbortController();
    settingsApi.getDownloadDefaults(controller.signal).then(
      (defaults) => {
        if (defaults.default_save_path) {
          dispatch({ type: "save_path_changed", value: defaults.default_save_path });
        }
      },
      () => { /* keep hardcoded fallback */ },
    );
    return () => controller.abort();
  }, []);

  const handleRefresh = useCallback(async () => {
    dispatch({ type: "fetch_started" });
    try {
      const resp = await mteamApi.getFreeTopped({ minSizeGb: state.minSizeGb });
      dispatch({ type: "fetch_succeeded", level2: resp.level2, level1: resp.level1 });
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") return;
      dispatch({ type: "fetch_failed", detail: errorDetail(err) });
    }
  }, [state.minSizeGb]);

  const handleDownload = useCallback(async (torrent: FreeToppedTorrent) => {
    setDownloadingIds(prev => new Set(prev).add(torrent.id));
    try {
      await chatApi.addDownload(torrent.id, "mteam", state.savePath);
      setDownloadedIds(prev => new Set(prev).add(torrent.id));
    } catch {
      // keep button active, silently fail
    } finally {
      setDownloadingIds(prev => {
        const next = new Set(prev);
        next.delete(torrent.id);
        return next;
      });
    }
  }, [state.savePath]);

  const hasData = state.level2.length > 0 || state.level1.length > 0;
  const showInitial = !state.isLoading && !state.lastError && !hasData;

  return (
    <section className="free-torrents-panel" id={id} role="tabpanel" aria-labelledby={labelledBy}>
      <div className="free-torrents-surface">
        {/* Toolbar */}
        <div className="free-torrents-toolbar">
          <div className="free-torrents-filters">
            <label className="free-torrents-filter-label">
              最小体积 (GB)
              <input
                type="number"
                min={0}
                step={1}
                value={state.minSizeGb}
                onChange={e => dispatch({ type: "min_size_changed", value: Number(e.target.value) || 0 })}
                className="free-torrents-filter-input"
              />
            </label>
            <label className="free-torrents-filter-label">
              下载路径
              <input
                type="text"
                value={state.savePath}
                onChange={e => dispatch({ type: "save_path_changed", value: e.target.value })}
                className="free-torrents-filter-input"
                style={{ width: 200 }}
              />
            </label>
          </div>
          <button className="free-torrents-refresh-btn" onClick={handleRefresh} disabled={state.isLoading}>
            {state.isLoading ? "加载中..." : "刷新"}
          </button>
        </div>

        {/* Error */}
        {state.lastError && <div className="free-torrents-error">{state.lastError}</div>}

        {/* Initial empty */}
        {showInitial && <div className="free-torrents-empty">点击刷新获取种子列表</div>}

        {/* Section: Level 2 */}
        <TorrentSection
          title="置顶 Level 2"
          torrents={state.level2}
          downloadingIds={downloadingIds}
          downloadedIds={downloadedIds}
          onDownload={handleDownload}
        />

        {/* Section: Level 1 */}
        <TorrentSection
          title="置顶 Level 1"
          torrents={state.level1}
          downloadingIds={downloadingIds}
          downloadedIds={downloadedIds}
          onDownload={handleDownload}
        />
      </div>
    </section>
  );
}

function TorrentSection({ title, torrents, downloadingIds, downloadedIds, onDownload }: {
  title: string;
  torrents: FreeToppedTorrent[];
  downloadingIds: Set<string>;
  downloadedIds: Set<string>;
  onDownload: (t: FreeToppedTorrent) => void;
}) {
  if (torrents.length === 0) return null;
  return (
    <div className="free-torrents-section">
      <div className="free-torrents-section-header">
        {title}
        <span className="count">({torrents.length})</span>
      </div>
      <div className="free-torrents-header-row">
        <span>名称</span>
        <span className="free-torrents-header-right">大小</span>
        <span className="free-torrents-header-right">做种</span>
        <span className="free-torrents-header-right">下载</span>
        <span className="free-torrents-header-right">剩余</span>
        <span></span>
      </div>
      {torrents.map(t => (
        <TorrentRow
          key={t.id}
          torrent={t}
          isDownloading={downloadingIds.has(t.id)}
          isDownloaded={downloadedIds.has(t.id)}
          onDownload={onDownload}
        />
      ))}
    </div>
  );
}

function TorrentRow({ torrent, isDownloading, isDownloaded, onDownload }: {
  torrent: FreeToppedTorrent;
  isDownloading: boolean;
  isDownloaded: boolean;
  onDownload: (t: FreeToppedTorrent) => void;
}) {
  return (
    <div className="free-torrents-row">
      <span className="free-torrents-row-name" title={torrent.name}>{torrent.name}</span>
      <span className="free-torrents-row-size">{torrent.size_display}</span>
      <span className="free-torrents-row-seeders">{torrent.seeders}</span>
      <span className="free-torrents-row-leechers">{torrent.leechers}</span>
      <span className="free-torrents-row-expiry">{formatRemaining(torrent.free_until)}</span>
      <button
        className="free-torrents-dl-btn"
        onClick={() => onDownload(torrent)}
        disabled={isDownloading || isDownloaded}
      >
        {isDownloading ? "..." : isDownloaded ? "已添加" : "下载"}
      </button>
    </div>
  );
}
