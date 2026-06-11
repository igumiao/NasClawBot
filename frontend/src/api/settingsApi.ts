import type { DownloadAuthorizationPolicy, DownloadDefaults } from "../types/api";
import { putJson, readJson } from "./http";

const DOWNLOAD_AUTHORIZATION_URL = "/settings/download-authorization";
const DOWNLOAD_DEFAULTS_URL = "/settings/download-defaults";

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

  async getDownloadDefaults(signal?: AbortSignal): Promise<DownloadDefaults> {
    const response = await fetch(DOWNLOAD_DEFAULTS_URL, { signal });
    return readJson<DownloadDefaults>(response);
  },

  updateDownloadDefaults(
    defaults: DownloadDefaults,
    signal?: AbortSignal,
  ): Promise<DownloadDefaults> {
    return putJson<DownloadDefaults>(DOWNLOAD_DEFAULTS_URL, defaults, signal);
  },
};
