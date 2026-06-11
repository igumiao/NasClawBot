import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SettingsPanel } from "./SettingsPanel";

const MOCK_SERVICES_RESPONSE = {
  status: "ok",
  services: [
    { service: "tmdb", status: "ok", latency_ms: 123.4, message: "TMDB API 响应正常" },
    { service: "tavily", status: "unconfigured", latency_ms: 0.0, message: "Tavily 未配置" },
    { service: "mteam", status: "unavailable", latency_ms: 5001.2, message: "M-Team 无法连接" },
    { service: "qbittorrent", status: "error", latency_ms: 89.1, message: "qBittorrent 返回错误" },
  ],
};

const MOCK_POLICY_RESPONSE = {
  enabled: false,
  categories: [],
  save_path_prefixes: [],
  max_items_per_batch: 10,
  max_total_items_per_session: 20,
  paused_required: true
};

function mockSettingsFetch() {
  return vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
    const url = String(input);
    if (url === "/health/services") {
      return Promise.resolve(new Response(JSON.stringify(MOCK_SERVICES_RESPONSE), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }));
    }
    if (url === "/settings/download-authorization") {
      const body = init?.method === "PUT" ? init.body : JSON.stringify(MOCK_POLICY_RESPONSE);
      return Promise.resolve(new Response(String(body), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }));
    }
    return Promise.resolve(new Response("{}", {
      status: 404,
      headers: { "Content-Type": "application/json" },
    }));
  });
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("SettingsPanel", () => {
  it("renders the session id and service health cards", async () => {
    mockSettingsFetch();

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

    // Session card
    expect(screen.getByText("session-1")).toBeInTheDocument();

    // All four service cards render (by aria-label)
    for (const svc of ["tmdb", "tavily", "mteam", "qbittorrent"]) {
      expect(await screen.findByLabelText(svc)).toBeInTheDocument();
    }

    // Status labels in Chinese
    expect(await screen.findByText("正常")).toBeInTheDocument();
    expect(screen.getByText("未配置")).toBeInTheDocument();
    expect(screen.getByText("无法连接")).toBeInTheDocument();
    expect(screen.getByText("错误")).toBeInTheDocument();

    // Latency shown for configured services
    expect(screen.getByText(/123\.4 ms/)).toBeInTheDocument();
    // Unconfigured service hides latency
    const tavilyCard = screen.getByLabelText("tavily");
    expect(tavilyCard.textContent).not.toMatch(/0\.0 ms/);
  });

  it("shows refresh button and triggers re-fetch", async () => {
    const fetchSpy = mockSettingsFetch();

    render(
      <SettingsPanel
        id="workspace-panel-settings"
        labelledBy="workspace-tab-settings"
        sessionId="session-2"
      />,
    );

    const refreshBtn = await screen.findByRole("button", { name: "刷新健康检查" });
    expect(refreshBtn).toBeInTheDocument();

    // Initial fetch happened on mount
    expect(fetchSpy).toHaveBeenCalledTimes(2);

    await userEvent.click(refreshBtn);
    expect(fetchSpy).toHaveBeenCalledTimes(3);
  });

  it("shows error banner on fetch failure", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("Network error"));

    render(
      <SettingsPanel
        id="workspace-panel-settings"
        labelledBy="workspace-tab-settings"
        sessionId="session-3"
      />,
    );

    expect(await screen.findByRole("alert")).toHaveTextContent("Network error");
  });

  it("saves download authorization policy", async () => {
    const fetchSpy = mockSettingsFetch();

    render(
      <SettingsPanel
        id="workspace-panel-settings"
        labelledBy="workspace-tab-settings"
        sessionId="session-4"
      />,
    );

    await userEvent.click(await screen.findByLabelText(/允许在审批后/));
    await userEvent.click(screen.getByLabelText("电视剧"));
    await userEvent.type(screen.getByLabelText("允许保存路径前缀"), "/downloads/tv");
    await userEvent.click(screen.getByRole("button", { name: "保存授权设置" }));

    expect(await screen.findByRole("status")).toHaveTextContent("已保存下载授权设置");
    const putCall = fetchSpy.mock.calls.find(([url, init]) => String(url) === "/settings/download-authorization" && init?.method === "PUT");
    expect(putCall).toBeTruthy();
    expect(JSON.parse(String(putCall?.[1]?.body))).toMatchObject({
      enabled: true,
      categories: ["电视剧"],
      save_path_prefixes: ["/downloads/tv"],
      paused_required: true
    });
  });
});
