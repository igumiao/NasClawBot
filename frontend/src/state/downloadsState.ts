import type { TorrentDetail, TorrentSummary } from "../types/api";

export type DownloadsFilter = "all" | "downloading" | "paused" | "completed";

export type DownloadsState = {
  torrentItems: TorrentSummary[];
  selectedTorrentHash: string | null;
  torrentDetail: TorrentDetail | null;
  isRefreshing: boolean;
  actionPendingHash: string | null;
  filter: DownloadsFilter;
  lastError: string | null;
};

type DownloadsAction =
  | { type: "refresh_started" }
  | { type: "list_loaded"; items: TorrentSummary[] }
  | { type: "detail_loaded"; detail: TorrentDetail }
  | { type: "torrent_selected"; hash: string }
  | { type: "filter_changed"; filter: DownloadsFilter }
  | { type: "action_started"; hash: string }
  | { type: "action_finished" }
  | { type: "request_failed"; detail: string };

export const downloadsInitialState: DownloadsState = {
  torrentItems: [],
  selectedTorrentHash: null,
  torrentDetail: null,
  isRefreshing: false,
  actionPendingHash: null,
  filter: "all",
  lastError: null
};

export function downloadsReducer(state: DownloadsState, action: DownloadsAction): DownloadsState {
  switch (action.type) {
    case "refresh_started":
      return { ...state, isRefreshing: true, lastError: null };
    case "list_loaded": {
      const hashes = new Set(action.items.map((item) => item.hash));
      const selectedTorrentHash =
        state.selectedTorrentHash && hashes.has(state.selectedTorrentHash)
          ? state.selectedTorrentHash
          : action.items[0]?.hash ?? null;
      const torrentDetail =
        state.torrentDetail && hashes.has(state.torrentDetail.hash) ? state.torrentDetail : null;

      return {
        ...state,
        torrentItems: action.items,
        selectedTorrentHash,
        torrentDetail,
        isRefreshing: false,
        lastError: null
      };
    }
    case "detail_loaded":
      return { ...state, torrentDetail: action.detail, lastError: null };
    case "torrent_selected":
      return { ...state, selectedTorrentHash: action.hash };
    case "filter_changed":
      return { ...state, filter: action.filter };
    case "action_started":
      return { ...state, actionPendingHash: action.hash, lastError: null };
    case "action_finished":
      return { ...state, actionPendingHash: null };
    case "request_failed":
      return { ...state, isRefreshing: false, actionPendingHash: null, lastError: action.detail };
    default:
      return state;
  }
}

export function visibleTorrents(state: DownloadsState): TorrentSummary[] {
  if (state.filter === "all") return state.torrentItems;
  if (state.filter === "paused") return state.torrentItems.filter((item) => pausedStates.has(item.state));
  if (state.filter === "completed") {
    return state.torrentItems.filter((item) => item.progress >= 1 || completedStates.has(item.state));
  }
  return state.torrentItems.filter((item) => downloadingStates.has(item.state));
}

const pausedStates = new Set(["stoppedDL", "stoppedUP", "pausedDL"]);
const completedStates = new Set(["uploading", "queuedUP", "stalledUP", "forcedUP", "checkingUP", "pausedUP"]);
const downloadingStates = new Set(["queuedDL", "stalledDL", "forcedDL", "metaDL", "downloading"]);
