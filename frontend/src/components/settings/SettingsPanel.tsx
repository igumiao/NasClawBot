import { useEffect, useState } from "react";
import { healthApi } from "../../api/healthApi";

type SettingsPanelProps = {
  id: string;
  labelledBy: string;
  sessionId?: string;
};

function errorDetail(error: unknown): string {
  if (error instanceof Error && error.message) {
    return error.message;
  }
  return "暂时不可用";
}

export function SettingsPanel({
  id,
  labelledBy,
  sessionId = "local-session"
}: SettingsPanelProps) {
  const [healthStatus, setHealthStatus] = useState("checking");
  const [healthDetail, setHealthDetail] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    let isMounted = true;

    async function loadHealth() {
      try {
        const response = await healthApi.getHealth(controller.signal);
        if (!isMounted) {
          return;
        }
        setHealthStatus(response.status);
        setHealthDetail("后端健康检查接口已响应。");
      } catch (error) {
        if (!isMounted || controller.signal.aborted) {
          return;
        }
        setHealthStatus("unavailable");
        setHealthDetail(errorDetail(error));
      }
    }

    void loadHealth();

    return () => {
      isMounted = false;
      controller.abort();
    };
  }, []);

  return (
    <section className="settings-panel" id={id} role="tabpanel" aria-labelledby={labelledBy}>
      <div className="settings-surface">
        <header className="panel-heading">
          <h1>运行状态</h1>
          <p>只读面板。密钥由环境统一管理，这里只展示当前会话和后端状态。</p>
        </header>

        <div className="settings-grid">
          <section className="settings-card" aria-label="Backend">
            <div className="settings-card-label">Backend</div>
            <div className="settings-card-value">{healthStatus}</div>
            <p className="settings-card-copy">{healthDetail ?? "正在检查服务可用性。"}</p>
          </section>

          <section className="settings-card" aria-label="Session">
            <div className="settings-card-label">Session</div>
            <div className="settings-card-value">{sessionId}</div>
            <p className="settings-card-copy">当前前端会话标识，用于串联聊天和下载动作。</p>
          </section>

          <section className="settings-card" aria-label="Secrets">
            <div className="settings-card-label">Secrets</div>
            <div className="settings-card-value">Environment managed</div>
            <p className="settings-card-copy">凭据不在浏览器内编辑，部署侧负责注入和轮换。</p>
          </section>
        </div>
      </div>
    </section>
  );
}
