import { useCallback, useEffect, useState } from "react";
import { healthApi } from "../../api/healthApi";
import { settingsApi } from "../../api/settingsApi";
import type {
  DownloadAuthorizationPolicy,
  OrganizationAuthorizationPolicy,
  ServiceHealth,
  ServiceHealthStatus,
  TMDBNetworkSettings
} from "../../types/api";

type SettingsPanelProps = {
  id: string;
  labelledBy: string;
  sessionId?: string;
};

const STATUS_COLORS: Record<ServiceHealthStatus | "untested" | "loading", string> = {
  ok: "var(--green, #16a34a)",
  unavailable: "var(--red, #dc2626)",
  error: "var(--red, #dc2626)",
  unconfigured: "var(--muted, #9ca3af)",
  untested: "var(--muted, #9ca3af)",
  loading: "var(--muted, #9ca3af)",
};

const STATUS_LABELS: Record<ServiceHealthStatus | "untested" | "loading", string> = {
  ok: "正常",
  unavailable: "无法连接",
  error: "异常",
  unconfigured: "未配置",
  untested: "未测试",
  loading: "检查中…",
};

const SERVICE_NAMES: Record<string, string> = {
  tmdb: "TMDB",
  tavily: "Tavily",
  mteam: "M-Team",
  qbittorrent: "qBittorrent",
};

const ALL_SERVICES = ["tmdb", "tavily", "mteam", "qbittorrent"];

const DEFAULT_POLICY: DownloadAuthorizationPolicy = {
  enabled: false,
  save_path_prefixes: [],
  max_items_per_batch: 10,
  max_total_items_per_session: 20,
  paused_required: true
};

const DEFAULT_TMDB_NETWORK: TMDBNetworkSettings = {
  enabled: false,
  proxy_url: ""
};

const DEFAULT_ORGANIZATION_POLICY: OrganizationAuthorizationPolicy = {
  background_organization_allowed: false,
  allowed_source_path_prefixes: [],
  destination_root: "",
  allow_delete: false,
  allow_overwrite: false
};

type CardState = {
  status: ServiceHealthStatus | "untested" | "loading";
  latency_ms: number | null;
  message: string;
};

function ServiceCard({
  service,
  state,
  onClick,
}: {
  service: string;
  state: CardState;
  onClick: () => void;
}) {
  const isLoading = state.status === "loading";

  return (
    <section
      className={`settings-card health-card${isLoading ? " health-card-loading" : ""}`}
      aria-label={SERVICE_NAMES[service] || service}
      role="button"
      tabIndex={0}
      onClick={onClick}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onClick();
        }
      }}
    >
      <div className="settings-card-label">{SERVICE_NAMES[service] || service}</div>
      <div className="settings-card-value" style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span
          className={`health-dot${isLoading ? " health-dot-pulse" : ""}`}
          style={{ backgroundColor: STATUS_COLORS[state.status] }}
          aria-hidden="true"
        />
        <span>{STATUS_LABELS[state.status]}</span>
      </div>
      {state.status !== "untested" && state.status !== "loading" && state.latency_ms != null && (
        <p className="settings-card-copy">
          {state.latency_ms} ms — {state.message}
        </p>
      )}
      {state.status === "untested" && (
        <p className="settings-card-copy">点击检查</p>
      )}
      {state.status === "loading" && (
        <p className="settings-card-copy">正在连接…</p>
      )}
    </section>
  );
}

export function SettingsPanel({
  id,
  labelledBy,
  sessionId = "local-session"
}: SettingsPanelProps) {
  const [cards, setCards] = useState<Record<string, CardState>>(() => {
    const initial: Record<string, CardState> = {};
    for (const svc of ALL_SERVICES) {
      initial[svc] = { status: "untested", latency_ms: null, message: "点击检查" };
    }
    return initial;
  });
  const [policy, setPolicy] = useState<DownloadAuthorizationPolicy>(DEFAULT_POLICY);
  const [savePathText, setSavePathText] = useState("");
  const [settingsLoading, setSettingsLoading] = useState(false);
  const [settingsStatus, setSettingsStatus] = useState<string | null>(null);
  const [tmdbNetwork, setTMDBNetwork] = useState<TMDBNetworkSettings>(DEFAULT_TMDB_NETWORK);
  const [tmdbProxyText, setTMDBProxyText] = useState("");
  const [tmdbNetworkLoading, setTMDBNetworkLoading] = useState(false);
  const [tmdbNetworkStatus, setTMDBNetworkStatus] = useState<string | null>(null);
  const [orgPolicy, setOrgPolicy] = useState<OrganizationAuthorizationPolicy>(DEFAULT_ORGANIZATION_POLICY);
  const [orgSourcePrefixText, setOrgSourcePrefixText] = useState("");
  const [orgDestRoot, setOrgDestRoot] = useState("");
  const [orgPolicyLoading, setOrgPolicyLoading] = useState(false);
  const [orgPolicyStatus, setOrgPolicyStatus] = useState<string | null>(null);

  const checkService = useCallback(async (service: string) => {
    setCards((prev) => ({
      ...prev,
      [service]: { status: "loading", latency_ms: null, message: "正在连接…" },
    }));
    try {
      const result: ServiceHealth = await healthApi.getServiceHealth(service);
      setCards((prev) => ({
        ...prev,
        [service]: {
          status: result.status,
          latency_ms: result.latency_ms,
          message: result.message,
        },
      }));
    } catch {
      setCards((prev) => ({
        ...prev,
        [service]: { status: "error", latency_ms: null, message: "请求失败" },
      }));
    }
  }, []);

  const loadPolicy = useCallback(async (signal?: AbortSignal) => {
    setSettingsLoading(true);
    setSettingsStatus(null);
    try {
      const response = await settingsApi.getDownloadAuthorization(signal);
      setPolicy(response);
      setSavePathText(response.save_path_prefixes.join("\n"));
    } catch (err) {
      if (signal?.aborted) return;
      setSettingsStatus(err instanceof Error ? err.message : "授权设置读取失败");
    } finally {
      setSettingsLoading(false);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void loadPolicy(controller.signal);
    return () => controller.abort();
  }, [loadPolicy]);

  const loadTMDBNetwork = useCallback(async (signal?: AbortSignal) => {
    setTMDBNetworkLoading(true);
    setTMDBNetworkStatus(null);
    try {
      const response = await settingsApi.getTMDBNetwork(signal);
      setTMDBNetwork(response);
      setTMDBProxyText(response.proxy_url);
    } catch (err) {
      if (signal?.aborted) return;
      setTMDBNetworkStatus(err instanceof Error ? err.message : "TMDB 网络设置读取失败");
    } finally {
      setTMDBNetworkLoading(false);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void loadTMDBNetwork(controller.signal);
    return () => controller.abort();
  }, [loadTMDBNetwork]);

  const loadOrgPolicy = useCallback(async (signal?: AbortSignal) => {
    setOrgPolicyLoading(true);
    setOrgPolicyStatus(null);
    try {
      const response = await settingsApi.getOrganizationAuthorizationPolicy(signal);
      setOrgPolicy(response);
      setOrgSourcePrefixText(response.allowed_source_path_prefixes.join("\n"));
      setOrgDestRoot(response.destination_root);
    } catch (err) {
      if (signal?.aborted) return;
      setOrgPolicyStatus(err instanceof Error ? err.message : "后台整理授权读取失败");
    } finally {
      setOrgPolicyLoading(false);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void loadOrgPolicy(controller.signal);
    return () => controller.abort();
  }, [loadOrgPolicy]);

  async function savePolicy() {
    setSettingsLoading(true);
    setSettingsStatus(null);
    const next: DownloadAuthorizationPolicy = {
      enabled: policy.enabled,
      save_path_prefixes: savePathText
        .split("\n")
        .map((line) => line.trim())
        .filter(Boolean),
      max_items_per_batch: policy.max_items_per_batch,
      max_total_items_per_session: policy.max_total_items_per_session,
      paused_required: true
    };
    try {
      const saved = await settingsApi.updateDownloadAuthorization(next);
      setPolicy(saved);
      setSavePathText(saved.save_path_prefixes.join("\n"));
      setSettingsStatus("已保存下载设置。");
    } catch (err) {
      setSettingsStatus(err instanceof Error ? err.message : "设置保存失败");
    } finally {
      setSettingsLoading(false);
    }
  }

  async function saveTMDBNetwork() {
    setTMDBNetworkLoading(true);
    setTMDBNetworkStatus(null);
    const next: TMDBNetworkSettings = {
      enabled: tmdbNetwork.enabled,
      proxy_url: tmdbProxyText.trim()
    };
    try {
      const saved = await settingsApi.updateTMDBNetwork(next);
      setTMDBNetwork(saved);
      setTMDBProxyText(saved.proxy_url);
      setTMDBNetworkStatus("已保存 TMDB 网络设置。");
    } catch (err) {
      setTMDBNetworkStatus(err instanceof Error ? err.message : "TMDB 网络设置保存失败");
    } finally {
      setTMDBNetworkLoading(false);
    }
  }

  async function saveOrgPolicy() {
    setOrgPolicyLoading(true);
    setOrgPolicyStatus(null);
    const next: OrganizationAuthorizationPolicy = {
      background_organization_allowed: orgPolicy.background_organization_allowed,
      allowed_source_path_prefixes: orgSourcePrefixText
        .split("\n")
        .map((line) => line.trim())
        .filter(Boolean),
      destination_root: orgDestRoot.trim(),
      allow_delete: false,
      allow_overwrite: false
    };
    try {
      const saved = await settingsApi.updateOrganizationAuthorizationPolicy(next);
      setOrgPolicy(saved);
      setOrgSourcePrefixText(saved.allowed_source_path_prefixes.join("\n"));
      setOrgDestRoot(saved.destination_root);
      setOrgPolicyStatus("已保存后台整理授权。");
    } catch (err) {
      setOrgPolicyStatus(err instanceof Error ? err.message : "后台整理授权保存失败");
    } finally {
      setOrgPolicyLoading(false);
    }
  }

  return (
    <section className="settings-panel" id={id} role="tabpanel" aria-labelledby={labelledBy}>
      <div className="settings-surface">
        <header className="health-header">
          <div>
            <h1>服务健康检查</h1>
            <p>点击卡片检查各外部服务的连通性和凭据状态。</p>
          </div>
        </header>

        <div className="settings-grid health-services-grid">
          {ALL_SERVICES.map((svc) => (
            <ServiceCard
              key={svc}
              service={svc}
              state={cards[svc]}
              onClick={() => {
                if (cards[svc].status !== "loading") {
                  void checkService(svc);
                }
              }}
            />
          ))}
        </div>

        <section className="settings-card" aria-label="Session">
          <div className="settings-card-label">Session</div>
          <div className="settings-card-value">{sessionId}</div>
          <p className="settings-card-copy">当前前端会话标识，用于串联聊天和下载动作。</p>
        </section>

        <section className="settings-card settings-policy-card tmdb-network-card" aria-label="TMDB 网络">
          <div className="settings-card-label">TMDB 网络</div>
          <label className="settings-toggle-row">
            <input
              type="checkbox"
              checked={tmdbNetwork.enabled}
              onChange={(event) => setTMDBNetwork((current) => ({ ...current, enabled: event.target.checked }))}
            />
            <span>为 TMDB 请求启用代理</span>
          </label>

          <label className="settings-field">
            <span>代理地址</span>
            <input
              type="url"
              value={tmdbProxyText}
              onChange={(event) => setTMDBProxyText(event.target.value)}
              placeholder="http://127.0.0.1:7890"
            />
          </label>

          <div className="settings-actions">
            <button
              className="primary-button"
              type="button"
              onClick={() => void saveTMDBNetwork()}
              disabled={tmdbNetworkLoading}
            >
              {tmdbNetworkLoading ? "保存中..." : "保存 TMDB 网络设置"}
            </button>
          </div>
          {tmdbNetworkStatus && <p className="settings-card-copy" role="status">{tmdbNetworkStatus}</p>}
        </section>

        <section className="settings-card settings-policy-card" aria-label="下载授权">
          <div className="settings-card-label">下载授权</div>
          <label className="settings-toggle-row">
            <input
              type="checkbox"
              checked={policy.enabled}
              onChange={(event) => setPolicy((current) => ({ ...current, enabled: event.target.checked }))}
            />
            <span>允许在审批后启用本会话自动添加 paused torrent</span>
          </label>

          <label className="settings-field">
            <span>允许保存路径前缀</span>
            <textarea
              value={savePathText}
              onChange={(event) => setSavePathText(event.target.value)}
              rows={3}
              placeholder="/downloads/tv"
            />
          </label>

          <div className="settings-number-grid">
            <label className="settings-field">
              <span>单批上限</span>
              <input
                type="number"
                min={1}
                max={10}
                value={policy.max_items_per_batch}
                onChange={(event) => setPolicy((current) => ({
                  ...current,
                  max_items_per_batch: Number(event.target.value)
                }))}
              />
            </label>
            <label className="settings-field">
              <span>本会话累计上限</span>
              <input
                type="number"
                min={1}
                max={100}
                value={policy.max_total_items_per_session}
                onChange={(event) => setPolicy((current) => ({
                  ...current,
                  max_total_items_per_session: Number(event.target.value)
                }))}
              />
            </label>
          </div>

          <div className="settings-actions">
            <button
              className="primary-button"
              type="button"
              onClick={() => void savePolicy()}
              disabled={settingsLoading}
            >
              {settingsLoading ? "保存中..." : "保存授权设置"}
            </button>
          </div>
          {settingsStatus && <p className="settings-card-copy" role="status">{settingsStatus}</p>}
        </section>

        <section className="settings-card settings-policy-card" aria-label="后台整理授权">
          <div className="settings-card-label">后台整理授权</div>
          <p className="settings-card-copy">
            仅授权经审批的后台任务整理媒体文件，不会自动决定下载完成后的动作。删除和覆写操作永久禁用。
          </p>

          <label className="settings-toggle-row">
            <input
              type="checkbox"
              checked={orgPolicy.background_organization_allowed}
              onChange={(event) => setOrgPolicy((current) => ({
                ...current,
                background_organization_allowed: event.target.checked
              }))}
            />
            <span>允许经审批的后台任务执行整理</span>
          </label>

          <label className="settings-field">
            <span>允许的来源路径前缀</span>
            <textarea
              value={orgSourcePrefixText}
              onChange={(event) => setOrgSourcePrefixText(event.target.value)}
              rows={3}
              placeholder="/downloads/tv"
            />
          </label>

          <label className="settings-field">
            <span>目标根路径</span>
            <input
              type="text"
              value={orgDestRoot}
              onChange={(event) => setOrgDestRoot(event.target.value)}
              placeholder="/media/library"
            />
          </label>

          <div className="settings-card-copy" style={{ marginTop: 8, opacity: 0.7 }}>
            <p>安全限制（不可更改）:</p>
            <ul style={{ margin: "4px 0 0 16px", padding: 0 }}>
              <li><code>allow_delete</code> — 永久禁用，不会删除任何源文件</li>
              <li><code>allow_overwrite</code> — 永久禁用，不会覆盖任何现有文件</li>
            </ul>
          </div>

          <div className="settings-actions">
            <button
              className="primary-button"
              type="button"
              onClick={() => void saveOrgPolicy()}
              disabled={orgPolicyLoading}
            >
              {orgPolicyLoading ? "保存中..." : "保存后台整理授权"}
            </button>
          </div>
          {orgPolicyStatus && <p className="settings-card-copy" role="status">{orgPolicyStatus}</p>}
        </section>
      </div>
    </section>
  );
}
