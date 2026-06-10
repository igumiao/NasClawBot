import { useCallback, useEffect, useState } from "react";
import { healthApi } from "../../api/healthApi";
import type { HealthServicesResponse, ServiceHealth, ServiceHealthStatus } from "../../types/api";

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
      </div>
    </section>
  );
}
