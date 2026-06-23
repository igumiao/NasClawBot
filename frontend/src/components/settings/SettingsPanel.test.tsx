import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SettingsPanel } from "./SettingsPanel";

const MOCK_TMDB_HEALTH = {
  service: "tmdb",
  status: "ok",
  latency_ms: 123.4,
  message: "TMDB API 响应正常",
};

const MOCK_TAVILY_HEALTH = {
  service: "tavily",
  status: "unconfigured",
  latency_ms: 0.0,
  message: "Tavily 未配置",
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

const MOCK_ORGANIZATION_AUTHORIZATION_RESPONSE = {
  background_organization_allowed: false,
  allowed_source_path_prefixes: ["/downloads"],
  destination_root: "/media",
  allow_delete: false,
  allow_overwrite: false
};

function mockSettingsFetch() {
  return vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
    const url = String(input);
    if (url === "/health/services/tmdb") {
      return Promise.resolve(new Response(JSON.stringify(MOCK_TMDB_HEALTH), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }));
    }
    if (url === "/health/services/tavily") {
      return Promise.resolve(new Response(JSON.stringify(MOCK_TAVILY_HEALTH), {
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
    if (url === "/settings/organization-authorization") {
      const body = init?.method === "PUT" ? init.body : JSON.stringify(MOCK_ORGANIZATION_AUTHORIZATION_RESPONSE);
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
  it("renders session id and health cards in untested state", async () => {
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

    // All four service cards render in untested state (by aria-label)
    for (const svc of ["TMDB", "Tavily", "M-Team", "qBittorrent"]) {
      expect(screen.getByLabelText(svc)).toBeInTheDocument();
    }

    // All cards show "未测试" initially
    expect(screen.getAllByText("未测试")).toHaveLength(4);
    // Each card shows "点击检查" hint
    expect(screen.getAllByText("点击检查")).toHaveLength(4);
  });

  it("clicks a health card to check that service", async () => {
    const fetchSpy = mockSettingsFetch();

    render(
      <SettingsPanel
        id="workspace-panel-settings"
        labelledBy="workspace-tab-settings"
        sessionId="session-2"
      />,
    );

    // Click the TMDB card
    const tmdbCard = screen.getByLabelText("TMDB");
    await userEvent.click(tmdbCard);

    // Should show loading then result
    await waitFor(() => {
      expect(screen.getByText("正常")).toBeInTheDocument();
    });
    expect(screen.getByText(/123\.4 ms/)).toBeInTheDocument();

    // Only TMDB endpoint was called (plus settings endpoints)
    expect(fetchSpy.mock.calls.filter(([url]) => String(url) === "/health/services/tmdb")).toHaveLength(1);
  });

  it("shows error state when health check fails", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.startsWith("/health/services/")) {
        return Promise.reject(new Error("Network error"));
      }
      if (url === "/settings/download-authorization") {
        return Promise.resolve(new Response(JSON.stringify(MOCK_POLICY_RESPONSE), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }));
      }
      if (url === "/settings/tmdb-network") {
        return Promise.resolve(new Response(JSON.stringify(MOCK_TMDB_NETWORK_RESPONSE), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }));
      }
      if (url === "/settings/organization-authorization") {
        return Promise.resolve(new Response(JSON.stringify(MOCK_ORGANIZATION_AUTHORIZATION_RESPONSE), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }));
      }
      return Promise.resolve(new Response("{}", { status: 404 }));
    });

    render(
      <SettingsPanel
        id="workspace-panel-settings"
        labelledBy="workspace-tab-settings"
        sessionId="session-3"
      />,
    );

    // Click TMDB card — should end up in error state
    await userEvent.click(screen.getByLabelText("TMDB"));

    await waitFor(() => {
      expect(screen.getByText("异常")).toBeInTheDocument();
    });
  });

  it("saves TMDB network proxy settings without auto-test", async () => {
    const fetchSpy = mockSettingsFetch();

    render(
      <SettingsPanel
        id="workspace-panel-settings"
        labelledBy="workspace-tab-settings"
        sessionId="session-4"
      />,
    );

    await userEvent.click(screen.getByLabelText("为 TMDB 请求启用代理"));
    await userEvent.type(screen.getByLabelText("代理地址"), "http://127.0.0.1:7890");
    await userEvent.click(screen.getByRole("button", { name: "保存 TMDB 网络设置" }));

    // Should show save confirmation (no auto-test, so no TMDB API response text)
    const statuses = await screen.findAllByRole("status");
    expect(statuses.some((el) => el.textContent === "已保存 TMDB 网络设置。")).toBe(true);

    const putCall = fetchSpy.mock.calls.find(([url, init]) => String(url) === "/settings/tmdb-network" && init?.method === "PUT");
    expect(putCall).toBeTruthy();
    expect(JSON.parse(String(putCall?.[1]?.body))).toMatchObject({
      enabled: true,
      proxy_url: "http://127.0.0.1:7890"
    });
    // No health endpoint should be called during save
    expect(fetchSpy.mock.calls.filter(([url]) => String(url).startsWith("/health/services/"))).toHaveLength(0);
  });

  it("clicking TMDB health card checks only TMDB", async () => {
    const fetchSpy = mockSettingsFetch();

    render(
      <SettingsPanel
        id="workspace-panel-settings"
        labelledBy="workspace-tab-settings"
        sessionId="session-5"
      />,
    );

    // All cards start untested
    expect(screen.getAllByText("未测试")).toHaveLength(4);

    // Click the TMDB card (not a separate test button)
    await userEvent.click(screen.getByLabelText("TMDB"));

    await waitFor(() => {
      expect(screen.getByText("正常")).toBeInTheDocument();
    });

    // Only TMDB was called, not the bulk endpoint
    expect(fetchSpy.mock.calls.filter(([url]) => String(url) === "/health/services/tmdb")).toHaveLength(1);
    // The other 3 cards are still untested
    expect(screen.getAllByText("未测试")).toHaveLength(3);

    expect(screen.getByText(/123\.4 ms/)).toBeInTheDocument();
  });

  it("saves background organization authorization without a default action", async () => {
    const fetchSpy = mockSettingsFetch();

    render(
      <SettingsPanel
        id="workspace-panel-settings"
        labelledBy="workspace-tab-settings"
        sessionId="session-org"
      />,
    );

    expect(await screen.findByLabelText("后台整理授权")).toBeInTheDocument();
    expect(screen.queryByLabelText("下载完成后")).not.toBeInTheDocument();
    await userEvent.click(screen.getByLabelText("允许经审批的后台任务执行整理"));
    await userEvent.clear(screen.getByLabelText("允许的来源路径前缀"));
    await userEvent.type(screen.getByLabelText("允许的来源路径前缀"), "/downloads/tv\n/downloads/movies");
    await userEvent.clear(screen.getByLabelText("目标根路径"));
    await userEvent.type(screen.getByLabelText("目标根路径"), "/media/library");
    await userEvent.click(screen.getByRole("button", { name: "保存后台整理授权" }));

    expect(await screen.findByText("已保存后台整理授权。")).toBeInTheDocument();
    const putCall = fetchSpy.mock.calls.find(
      ([url, init]) => String(url) === "/settings/organization-authorization" && init?.method === "PUT",
    );
    expect(putCall).toBeTruthy();
    expect(JSON.parse(String(putCall?.[1]?.body))).toEqual({
      background_organization_allowed: true,
      allowed_source_path_prefixes: ["/downloads/tv", "/downloads/movies"],
      destination_root: "/media/library",
      allow_delete: false,
      allow_overwrite: false
    });
  });
});
