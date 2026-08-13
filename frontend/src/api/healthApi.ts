import type { HealthResponse, HealthServicesResponse, ServiceHealth } from "../types/api";
import { apiFetch } from "./apiFetch";
import { readJson } from "./http";

export const healthApi = {
  async getHealth(signal?: AbortSignal): Promise<HealthResponse> {
    const response = await apiFetch("/health", { signal });
    return readJson<HealthResponse>(response);
  },

  async getServicesHealth(signal?: AbortSignal): Promise<HealthServicesResponse> {
    const response = await apiFetch("/health/services", { signal });
    return readJson<HealthServicesResponse>(response);
  },

  async getServiceHealth(service: string, signal?: AbortSignal): Promise<ServiceHealth> {
    const response = await apiFetch(`/health/services/${service}`, { signal });
    return readJson<ServiceHealth>(response);
  }
};
