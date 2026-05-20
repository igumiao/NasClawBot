import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SettingsPanel } from "./SettingsPanel";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("SettingsPanel", () => {
  it("renders the session id and fetched health status inside the tabpanel", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ status: "ok" }), {
        status: 200,
        headers: { "Content-Type": "application/json" }
      }),
    );

    render(
      <SettingsPanel
        id="workspace-panel-settings"
        labelledBy="workspace-tab-settings"
        sessionId="session-1"
      />,
    );

    const panel = screen.getByRole("tabpanel");
    expect(panel).toHaveAttribute("id", "workspace-panel-settings");
    expect(panel).toHaveAttribute("aria-labelledby", "workspace-tab-settings");

    expect(screen.getByText("session-1")).toBeInTheDocument();
    expect(await screen.findByText("ok")).toBeInTheDocument();
  });
});
