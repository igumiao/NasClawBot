import type { DownloadAuthorizationPolicy, OrganizationAutomationPolicy, TMDBNetworkSettings } from "../types/api";
import { putJson, readJson } from "./http";

const DOWNLOAD_AUTHORIZATION_URL = "/settings/download-authorization";
const TMDB_NETWORK_URL = "/settings/tmdb-network";
const ORGANIZATION_AUTOMATION_URL = "/settings/organization-automation";

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

  async getOrganizationPolicy(signal?: AbortSignal): Promise<OrganizationAutomationPolicy> {
    const response = await fetch(ORGANIZATION_AUTOMATION_URL, { signal });
    return readJson<OrganizationAutomationPolicy>(response);
  },

  updateOrganizationPolicy(
    policy: OrganizationAutomationPolicy,
    signal?: AbortSignal,
  ): Promise<OrganizationAutomationPolicy> {
    return putJson<OrganizationAutomationPolicy>(ORGANIZATION_AUTOMATION_URL, policy, signal);
  },
};
