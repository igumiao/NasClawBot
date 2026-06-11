import type { FreeToppedTorrent } from "../types/api";

export type FreeTorrentsState = {
  level2: FreeToppedTorrent[];
  level1: FreeToppedTorrent[];
  isLoading: boolean;
  lastError: string | null;
  minSizeGb: number;
  savePath: string;
};

type FreeTorrentsAction =
  | { type: "fetch_started" }
  | { type: "fetch_succeeded"; level2: FreeToppedTorrent[]; level1: FreeToppedTorrent[] }
  | { type: "fetch_failed"; detail: string }
  | { type: "min_size_changed"; value: number }
  | { type: "save_path_changed"; value: string };

export const freeTorrentsInitialState: FreeTorrentsState = {
  level2: [], level1: [], isLoading: false, lastError: null,
  minSizeGb: 30, savePath: "/vol1/1000/NasClawBot下载区域",
};

export function freeTorrentsReducer(
  state: FreeTorrentsState,
  action: FreeTorrentsAction,
): FreeTorrentsState {
  switch (action.type) {
    case "fetch_started":
      return { ...state, isLoading: true, lastError: null };
    case "fetch_succeeded":
      return { ...state, level2: action.level2, level1: action.level1, isLoading: false, lastError: null };
    case "fetch_failed":
      return { ...state, isLoading: false, lastError: action.detail };
    case "min_size_changed":
      return { ...state, minSizeGb: action.value };
    case "save_path_changed":
      return { ...state, savePath: action.value };
    default:
      return state;
  }
}
