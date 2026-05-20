import type { HealthResponse } from "../types/api";
import { readJson } from "./http";

export const healthApi = {
  async getHealth(signal?: AbortSignal): Promise<HealthResponse> {
    const response = await fetch("/health", { signal });
    return readJson<HealthResponse>(response);
  }
};
