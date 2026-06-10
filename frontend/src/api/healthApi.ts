import type { HealthResponse, HealthServicesResponse } from "../types/api";
import { readJson } from "./http";

export const healthApi = {
  async getHealth(signal?: AbortSignal): Promise<HealthResponse> {
    const response = await fetch("/health", { signal });
    return readJson<HealthResponse>(response);
  },

  async getServicesHealth(signal?: AbortSignal): Promise<HealthServicesResponse> {
    const response = await fetch("/health/services", { signal });
    return readJson<HealthServicesResponse>(response);
  }
};
