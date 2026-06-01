import type { ChatResponse, DownloadResponse } from "../types/api";
import { postJson } from "./http";

export const chatApi = {
  sendMessage(sessionId: string, message: string, signal?: AbortSignal): Promise<ChatResponse> {
    return postJson<ChatResponse>("/chat", { session_id: sessionId, message }, signal);
  },

  addDownload(
    torrentId: string,
    qbCategory = "mteam",
    signal?: AbortSignal,
  ): Promise<DownloadResponse> {
    return postJson<DownloadResponse>(
      "/download",
      {
        torrent_id: torrentId,
        qb_category: qbCategory
      },
      signal,
    );
  }
};
