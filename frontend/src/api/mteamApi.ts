import { readJson } from "./http";
import type { FreeToppedResponse } from "../types/api";

export const mteamApi = {
  async getFreeTopped(
    params: { minSizeGb?: number; toppingOnly?: boolean },
    signal?: AbortSignal,
  ): Promise<FreeToppedResponse> {
    const searchParams = new URLSearchParams();
    if (params.minSizeGb !== undefined && params.minSizeGb > 0) {
      searchParams.set("min_size_gb", String(params.minSizeGb));
    }
    if (params.toppingOnly !== undefined) {
      searchParams.set("topping_only", String(params.toppingOnly));
    }
    const qs = searchParams.toString();
    const url = `/mteam/free-topped${qs ? "?" + qs : ""}`;
    const response = await fetch(url, { signal });
    return readJson<FreeToppedResponse>(response);
  },
};
