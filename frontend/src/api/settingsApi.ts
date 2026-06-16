import type { DownloadAuthorizationPolicy } from "../types/api";
import { putJson, readJson } from "./http";

const DOWNLOAD_AUTHORIZATION_URL = "/settings/download-authorization";

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
};
