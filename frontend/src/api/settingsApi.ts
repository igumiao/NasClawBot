import type { DownloadAuthorizationPolicy, OrganizationAuthorizationPolicy, TMDBNetworkSettings } from "../types/api";
import { apiFetch } from "./apiFetch";
import { putJson, readJson } from "./http";

const DOWNLOAD_AUTHORIZATION_URL = "/settings/download-authorization";
const TMDB_NETWORK_URL = "/settings/tmdb-network";
const ORGANIZATION_AUTHORIZATION_URL = "/settings/organization-authorization";

export const settingsApi = {
  async getDownloadAuthorization(signal?: AbortSignal): Promise<DownloadAuthorizationPolicy> {
    const response = await apiFetch(DOWNLOAD_AUTHORIZATION_URL, { signal });
    return readJson<DownloadAuthorizationPolicy>(response);
  },

  updateDownloadAuthorization(
    policy: DownloadAuthorizationPolicy,
    signal?: AbortSignal,
  ): Promise<DownloadAuthorizationPolicy> {
    return putJson<DownloadAuthorizationPolicy>(DOWNLOAD_AUTHORIZATION_URL, policy, signal);
  },

  async getTMDBNetwork(signal?: AbortSignal): Promise<TMDBNetworkSettings> {
    const response = await apiFetch(TMDB_NETWORK_URL, { signal });
    return readJson<TMDBNetworkSettings>(response);
  },

  updateTMDBNetwork(
    settings: TMDBNetworkSettings,
    signal?: AbortSignal,
  ): Promise<TMDBNetworkSettings> {
    return putJson<TMDBNetworkSettings>(TMDB_NETWORK_URL, settings, signal);
  },

  async getOrganizationAuthorizationPolicy(signal?: AbortSignal): Promise<OrganizationAuthorizationPolicy> {
    const response = await apiFetch(ORGANIZATION_AUTHORIZATION_URL, { signal });
    return readJson<OrganizationAuthorizationPolicy>(response);
  },

  updateOrganizationAuthorizationPolicy(
    policy: OrganizationAuthorizationPolicy,
    signal?: AbortSignal,
  ): Promise<OrganizationAuthorizationPolicy> {
    return putJson<OrganizationAuthorizationPolicy>(ORGANIZATION_AUTHORIZATION_URL, policy, signal);
  },
};
