import { afterEach, describe, expect, it, vi } from "vitest";
import type { OrganizationAuthorizationPolicy } from "../types/api";
import { settingsApi } from "./settingsApi";

const policy: OrganizationAuthorizationPolicy = {
  background_organization_allowed: true,
  allowed_source_path_prefixes: ["/downloads"],
  destination_root: "/media",
  allow_delete: false,
  allow_overwrite: false
};

afterEach(() => {
  vi.restoreAllMocks();
});

describe("settingsApi organization authorization", () => {
  it("reads the authorization-only endpoint", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify(policy), {
        status: 200,
        headers: { "Content-Type": "application/json" }
      }),
    );

    await expect(settingsApi.getOrganizationAuthorizationPolicy()).resolves.toEqual(policy);
    expect(fetchMock).toHaveBeenCalledWith("/settings/organization-authorization", { signal: undefined });
  });

  it("updates the authorization-only endpoint without behavior defaults", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify(policy), {
        status: 200,
        headers: { "Content-Type": "application/json" }
      }),
    );

    await expect(settingsApi.updateOrganizationAuthorizationPolicy(policy)).resolves.toEqual(policy);
    expect(fetchMock).toHaveBeenCalledWith(
      "/settings/organization-authorization",
      expect.objectContaining({
        method: "PUT",
        body: JSON.stringify(policy)
      }),
    );
  });
});
