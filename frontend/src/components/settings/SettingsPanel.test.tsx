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

const MOCK_TMDB_NETWORK_RESPONSE = {
  enabled: false,
  proxy_url: ""
};

const MOCK_TMDB_HEALTH_RESPONSE = {
  service: "tmdb",
  status: "ok",
  latency_ms: 45.2,
  message: "TMDB API 响应正常"
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
    if (url === "/health/services/tmdb") {
      return Promise.resolve(new Response(JSON.stringify(MOCK_TMDB_HEALTH_RESPONSE), {
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
    if (url === "/settings/tmdb-network") {
      const body = init?.method === "PUT" ? init.body : JSON.stringify(MOCK_TMDB_NETWORK_RESPONSE);
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
    expect(fetchSpy).toHaveBeenCalledTimes(3);

    await userEvent.click(refreshBtn);
    expect(fetchSpy).toHaveBeenCalledTimes(4);
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

  it("saves TMDB network proxy settings", async () => {
    const fetchSpy = mockSettingsFetch();

    render(
      <SettingsPanel
        id="workspace-panel-settings"
        labelledBy="workspace-tab-settings"
        sessionId="session-4"
      />,
    );

    await userEvent.click(await screen.findByLabelText("为 TMDB 请求启用代理"));
    await userEvent.type(screen.getByLabelText("代理地址"), "http://127.0.0.1:7890");
    await userEvent.click(screen.getByRole("button", { name: "保存 TMDB 网络设置" }));

    expect(await screen.findByRole("status")).toHaveTextContent("TMDB API 响应正常");
    const putCall = fetchSpy.mock.calls.find(([url, init]) => String(url) === "/settings/tmdb-network" && init?.method === "PUT");
    expect(putCall).toBeTruthy();
    expect(JSON.parse(String(putCall?.[1]?.body))).toMatchObject({
      enabled: true,
      proxy_url: "http://127.0.0.1:7890"
    });
    expect(fetchSpy.mock.calls.filter(([url]) => String(url) === "/health/services")).toHaveLength(1);
    expect(fetchSpy.mock.calls.filter(([url]) => String(url) === "/health/services/tmdb")).toHaveLength(1);
    expect(screen.getByText("正常 · 45.2 ms")).toBeInTheDocument();
  });

  it("tests only TMDB from the TMDB network card", async () => {
    const fetchSpy = mockSettingsFetch();

    render(
      <SettingsPanel
        id="workspace-panel-settings"
        labelledBy="workspace-tab-settings"
        sessionId="session-5"
      />,
    );

    expect(await screen.findByText("未测试")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "测试 TMDB 连接" }));

    expect(await screen.findByRole("status")).toHaveTextContent("TMDB API 响应正常");
    expect(fetchSpy.mock.calls.filter(([url]) => String(url) === "/health/services")).toHaveLength(1);
    expect(fetchSpy.mock.calls.filter(([url]) => String(url) === "/health/services/tmdb")).toHaveLength(1);
    expect(screen.getByText("正常 · 45.2 ms")).toBeInTheDocument();
  });

});
