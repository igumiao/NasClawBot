import { useCallback, useEffect, useState } from "react";
import { healthApi } from "../../api/healthApi";
import { settingsApi } from "../../api/settingsApi";
import type { DownloadAuthorizationPolicy, HealthServicesResponse, ServiceHealth, ServiceHealthStatus } from "../../types/api";

type SettingsPanelProps = {
  id: string;
  labelledBy: string;
  sessionId?: string;
};

const STATUS_COLORS: Record<ServiceHealthStatus, string> = {
  ok: "var(--green, #16a34a)",
  unavailable: "var(--red, #dc2626)",
  error: "var(--yellow, #ca8a04)",
  unconfigured: "var(--muted, #9ca3af)",
};

const STATUS_LABELS: Record<ServiceHealthStatus, string> = {
  ok: "正常",
  unavailable: "无法连接",
  error: "错误",
  unconfigured: "未配置",
};

const CATEGORY_OPTIONS = ["电影", "电视剧", "综艺", "动漫", "纪录片"];

const DEFAULT_POLICY: DownloadAuthorizationPolicy = {
  enabled: false,
  categories: [],
  save_path_prefixes: [],
  max_items_per_batch: 10,
  max_total_items_per_session: 20,
  paused_required: true
};

function ServiceCard({ service }: { service: ServiceHealth }) {
  return (
    <section className="settings-card" aria-label={service.service}>
      <div className="settings-card-label">{service.service}</div>
      <div className="settings-card-value" style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span
          className="health-dot"
          style={{ backgroundColor: STATUS_COLORS[service.status] }}
          aria-hidden="true"
        />
        <span>{STATUS_LABELS[service.status]}</span>
      </div>
      {service.status !== "unconfigured" && (
        <p className="settings-card-copy">
          {service.latency_ms} ms — {service.message}
        </p>
      )}
      {service.status === "unconfigured" && (
        <p className="settings-card-copy">{service.message}</p>
      )}
    </section>
  );
}

export function SettingsPanel({
  id,
  labelledBy,
  sessionId = "local-session"
}: SettingsPanelProps) {
  const [services, setServices] = useState<ServiceHealth[]>([]);
  const [overallStatus, setOverallStatus] = useState<string>("checking");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [policy, setPolicy] = useState<DownloadAuthorizationPolicy>(DEFAULT_POLICY);
  const [savePathText, setSavePathText] = useState("");
  const [settingsLoading, setSettingsLoading] = useState(false);
  const [settingsStatus, setSettingsStatus] = useState<string | null>(null);

  const loadServices = useCallback(async (signal?: AbortSignal) => {
    setLoading(true);
    setError(null);
    try {
      const response: HealthServicesResponse = await healthApi.getServicesHealth(signal);
      setServices(response.services);
      setOverallStatus(response.status);
    } catch (err) {
      if (signal?.aborted) return;
      setError(err instanceof Error ? err.message : "健康检查请求失败");
      setOverallStatus("error");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void loadServices(controller.signal);
    return () => controller.abort();
  }, [loadServices]);

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

  function toggleCategory(category: string) {
    setPolicy((current) => ({
      ...current,
      categories: current.categories.includes(category)
        ? current.categories.filter((item) => item !== category)
        : [...current.categories, category]
    }));
  }

  async function savePolicy() {
    setSettingsLoading(true);
    setSettingsStatus(null);
    const next: DownloadAuthorizationPolicy = {
      ...policy,
      save_path_prefixes: savePathText
        .split("\n")
        .map((line) => line.trim())
        .filter(Boolean),
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

  return (
    <section className="settings-panel" id={id} role="tabpanel" aria-labelledby={labelledBy}>
      <div className="settings-surface">
        <header className="health-header">
          <div>
            <h1>服务健康检查</h1>
            <p>手动检查各外部服务的连通性和凭据状态。</p>
          </div>
          <button
            className="health-refresh-btn"
            type="button"
            onClick={() => loadServices()}
            disabled={loading}
            aria-label="刷新健康检查"
          >
            {loading ? "检查中…" : "刷新检查"}
          </button>
        </header>

        {error && (
          <div className="health-error-banner" role="alert">
            {error}
          </div>
        )}

        <div className="settings-grid health-services-grid">
          {services.map((svc) => (
            <ServiceCard key={svc.service} service={svc} />
          ))}
        </div>

        <section className="settings-card" aria-label="Session">
          <div className="settings-card-label">Session</div>
          <div className="settings-card-value">{sessionId}</div>
          <p className="settings-card-copy">当前前端会话标识，用于串联聊天和下载动作。</p>
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

          <div className="settings-field-group" aria-label="允许分类">
            {CATEGORY_OPTIONS.map((category) => (
              <label key={category} className="settings-check-chip">
                <input
                  type="checkbox"
                  checked={policy.categories.includes(category)}
                  onChange={() => toggleCategory(category)}
                />
                <span>{category}</span>
              </label>
            ))}
          </div>

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
      </div>
    </section>
  );
}
