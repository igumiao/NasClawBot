import type { DownloadAuthorizationPolicy, TMDBNetworkSettings } from "../types/api";
import { putJson, readJson } from "./http";

const DOWNLOAD_AUTHORIZATION_URL = "/settings/download-authorization";
const TMDB_NETWORK_URL = "/settings/tmdb-network";

export const settingsApi = {
  async getDownloadAuthorization(signal?: AbortSignal): Promise<DownloadAuthorizationPolicy> {
    const response = await fetch(DOWNLOAD_AUTHORIZATION_URL, { signal });
    return readJson<DownloadAuthorizationPolicy>(response);
  },

  updateDownloadAuthorization(
    policy: DownloadAuthorizationPolicy,
    signal?: AbortSignal,
  ): Promise<DownloadAuthorizationPolicy> {
    return putJson<DownloadAuthorizationPolicy>(DOWNLOAD_AUTHORIZATION_URL, policy, signal);
  },

  async getTMDBNetwork(signal?: AbortSignal): Promise<TMDBNetworkSettings> {
    const response = await fetch(TMDB_NETWORK_URL, { signal });
    return readJson<TMDBNetworkSettings>(response);
  },

  updateTMDBNetwork(
    settings: TMDBNetworkSettings,
    signal?: AbortSignal,
  ): Promise<TMDBNetworkSettings> {
    return putJson<TMDBNetworkSettings>(TMDB_NETWORK_URL, settings, signal);
  },
};
