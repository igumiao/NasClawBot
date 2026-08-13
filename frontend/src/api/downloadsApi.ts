import type { TorrentAction, TorrentActionResponse, TorrentDetail, TorrentListResponse } from "../types/api";
import { apiFetch } from "./apiFetch";
import { postJson, readJson } from "./http";

export const downloadsApi = {
  async listTorrents(signal?: AbortSignal): Promise<TorrentListResponse> {
    const response = await apiFetch("/qb/torrents", { signal });
    return readJson<TorrentListResponse>(response);
  },

  async getTorrent(hash: string, signal?: AbortSignal): Promise<TorrentDetail> {
    const response = await apiFetch(`/qb/torrents/${encodeURIComponent(hash)}`, { signal });
    return readJson<TorrentDetail>(response);
  },

  runTorrentAction(
    hash: string,
    action: TorrentAction,
    options: { deleteFiles?: boolean } = {},
    signal?: AbortSignal,
  ): Promise<TorrentActionResponse> {
    return postJson<TorrentActionResponse>(
      `/qb/torrents/${encodeURIComponent(hash)}/actions`,
      { action, delete_files: options.deleteFiles ?? false },
      signal,
    );
  }
};
