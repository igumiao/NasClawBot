import { useId } from "react";

export type PendingApprovalLike = {
  approval_id: string;
  tool_name?: string;
  arguments?: Record<string, unknown> | null;
  status?: string;
  expires_at: string;
  risk?: {
    level?: string;
    summary?: string;
  } | null;
  authorization?: {
    eligible?: boolean;
    reason?: string;
  } | null;
};

export type ApprovalCardStatus = "pending" | "approved" | "denied" | "failed" | "expired";

type ApprovalCardProps = {
  approval: PendingApprovalLike;
  status: ApprovalCardStatus;
  isSubmitting: boolean;
  onApprove: (approvalId: string) => void;
  onApproveWithGrant?: (approvalId: string) => void;
  onDeny: (approvalId: string) => void;
};

const STATUS_LABELS: Record<ApprovalCardStatus, string> = {
  pending: "等待确认",
  approved: "已批准",
  denied: "已拒绝",
  failed: "执行失败",
  expired: "已过期"
};

const STATUS_MESSAGES: Partial<Record<ApprovalCardStatus, string>> = {
  approved: "此审批已批准。",
  denied: "此审批已拒绝。",
  failed: "此审批执行失败，请重新发起请求。",
  expired: "此审批已过期，请重新发起请求。"
};

function isPast(expiresAt: string): boolean {
  const timestamp = Date.parse(expiresAt);
  return Number.isFinite(timestamp) && timestamp <= Date.now();
}

function formatExpiry(expiresAt: string): string {
  const timestamp = Date.parse(expiresAt);
  if (!Number.isFinite(timestamp)) return expiresAt;

  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "short"
  }).format(timestamp);
}

function batchItems(argumentsValue: Record<string, unknown>): Record<string, unknown>[] {
  return Array.isArray(argumentsValue.items)
    ? argumentsValue.items.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object" && !Array.isArray(item))
    : [];
}

function formatStartAt(startAt: string): string {
  try {
    return new Intl.DateTimeFormat("zh-CN", {
      dateStyle: "full",
      timeStyle: "short",
      timeZone: Intl.DateTimeFormat().resolvedOptions().timeZone,
    }).format(new Date(startAt));
  } catch {
    return startAt;
  }
}

function isDownloadAddTool(toolName: string): boolean {
  return toolName === "qb_add_torrent" || toolName === "qb_add_torrents";
}

function isMonitorCreate(toolName: string): boolean {
  return toolName === "monitor_download";
}

function isMonitorUpdate(toolName: string): boolean {
  return toolName === "update_download_monitor";
}

function completionActionLabel(action: unknown, fallback = "未提供"): string {
  if (action === "none") return "仅下载";
  if (action === "notify") return "完成后通知";
  if (action === "organize") return "完成后整理";
  return fallback;
}

function monitorModeLabel(mode: unknown, fallback = "未提供"): string {
  if (mode === "once") return "检查一次";
  if (mode === "until_complete") return "持续监督至完成";
  return fallback;
}

function incompleteBehaviorLabel(mode: unknown, fallback = "由当前模式决定"): string {
  if (mode === "once") return "通知并结束";
  if (mode === "until_complete") return "继续动态监督";
  return fallback;
}

export function ApprovalCard({
  approval,
  status,
  isSubmitting,
  onApprove,
  onApproveWithGrant,
  onDeny
}: ApprovalCardProps) {
  const titleId = `${useId()}-approval-title`;
  const argumentsValue = approval.arguments ?? {};
  const toolName = approval.tool_name ?? "";
  const torrentId = String(argumentsValue.torrent_id ?? "未提供");
  const qbCategory = String(argumentsValue.qb_category ?? "mteam");
  const savePath = argumentsValue.save_path ? String(argumentsValue.save_path) : null;
  const items = batchItems(argumentsValue);
  const displayStatus: ApprovalCardStatus = status === "pending" && isPast(approval.expires_at) ? "expired" : status;
  const isPending = displayStatus === "pending";
  const isBatch = items.length > 0;
  const isDownload = isDownloadAddTool(toolName);
  const completionAction = argumentsValue.completion_action;
  const canGrant = isDownload
    && (completionAction === "none" || completionAction === "notify")
    && approval.authorization?.eligible === true
    && typeof onApproveWithGrant === "function";

  // Download monitor fields
  const torrentHash = String(argumentsValue.torrent_hash ?? "");
  const startAt = String(argumentsValue.start_at ?? "");
  const monitorMode = argumentsValue.mode;
  const onCompleted = argumentsValue.on_completed;

  // Task mutation fields
  const taskId = String(argumentsValue.task_id ?? "");

  const titleLabel = isMonitorCreate(toolName) ? "创建下载监督"
    : isMonitorUpdate(toolName) ? "修改下载监督"
    : toolName === "task_cancel" ? "取消任务"
    : approval.tool_name ?? "工具调用";

  return (
    <section className="chat-card approval-card" aria-labelledby={titleId}>
      <header className="chat-card-header">
        <div>
          <p className="chat-card-eyebrow">需要确认</p>
          <h2 className="chat-card-title" id={titleId}>
            {titleLabel}
          </h2>
        </div>
        <span className="status-pill" data-status={displayStatus}>
          {STATUS_LABELS[displayStatus]}
        </span>
      </header>

      <p className="approval-risk">{approval.risk?.summary ?? "该操作会产生外部副作用。"}</p>
      {isMonitorUpdate(toolName) && (
        <p className="approval-risk">此次修改可能改变任务性质，请确认时间、模式和完成动作。</p>
      )}

      <dl className="approval-details">
        {isMonitorCreate(toolName) ? (
          <>
            <div>
              <dt>Torrent</dt>
              <dd><code>{torrentHash || "未提供"}</code></dd>
            </div>
            <div>
              <dt>首次检查时间</dt>
              <dd>
                {startAt ? <time dateTime={startAt}>{formatStartAt(startAt)}</time> : "立即开始"}
              </dd>
            </div>
            <div>
              <dt>监督模式</dt>
              <dd>{monitorModeLabel(monitorMode)}</dd>
            </div>
            <div>
              <dt>完成后</dt>
              <dd>{completionActionLabel(onCompleted)}</dd>
            </div>
            <div>
              <dt>未完成</dt>
              <dd>{incompleteBehaviorLabel(monitorMode)}</dd>
            </div>
          </>
        ) : isMonitorUpdate(toolName) ? (
          <>
            <div>
              <dt>任务 ID</dt>
              <dd><code>{taskId || "未提供"}</code></dd>
            </div>
            <div>
              <dt>首次检查时间</dt>
              <dd>{startAt ? <time dateTime={startAt}>{formatStartAt(startAt)}</time> : "未修改"}</dd>
            </div>
            <div>
              <dt>监督模式</dt>
              <dd>{monitorModeLabel(monitorMode, "未修改")}</dd>
            </div>
            <div>
              <dt>完成后</dt>
              <dd>{completionActionLabel(onCompleted, "未修改")}</dd>
            </div>
            <div>
              <dt>未完成</dt>
              <dd>{incompleteBehaviorLabel(monitorMode)}</dd>
            </div>
          </>
        ) : toolName === "task_cancel" ? (
          <div>
            <dt>任务 ID</dt>
            <dd><code>{taskId || "未提供"}</code></dd>
          </div>
        ) : isBatch ? (
          <div>
            <dt>批量项目</dt>
            <dd>{items.length} 个 torrent</dd>
          </div>
        ) : (
          <>
            <div>
              <dt>Torrent ID</dt>
              <dd>{torrentId}</dd>
            </div>
            <div>
              <dt>qB 分类</dt>
              <dd>{qbCategory}</dd>
            </div>
            {savePath && (
              <div>
                <dt>存储路径</dt>
                <dd>{savePath}</dd>
              </div>
            )}
          </>
        )}
        {isDownload && (
          <div>
            <dt>完成动作</dt>
            <dd>{completionActionLabel(completionAction)}</dd>
          </div>
        )}
        <div>
          <dt>过期时间</dt>
          <dd>
            <time dateTime={approval.expires_at}>{formatExpiry(approval.expires_at)}</time>
          </dd>
        </div>
      </dl>

      {isBatch && (
        <ol className="approval-item-list" aria-label="待添加 torrent">
          {items.map((item, index) => (
            <li key={`${String(item.torrent_id ?? index)}-${index}`}>
              <span>{String(item.torrent_id ?? "未提供")}</span>
              <span>{String(item.qb_category ?? item.category ?? "mteam")}</span>
              {item.save_path ? <span>{String(item.save_path)}</span> : null}
            </li>
          ))}
        </ol>
      )}

      {!isPending ? (
        <p className="approval-status-message" data-status={displayStatus} role="status">
          {STATUS_MESSAGES[displayStatus]}
        </p>
      ) : (
        <div className="chat-card-actions">
          <button
            type="button"
            className="secondary-button"
            disabled={isSubmitting}
            onClick={() => onDeny(approval.approval_id)}
          >
            拒绝
          </button>
          <button
            type="button"
            className="primary-button"
            disabled={isSubmitting}
            onClick={() => onApprove(approval.approval_id)}
          >
            {isSubmitting ? "处理中..." : "仅批准本次"}
          </button>
          {canGrant && (
            <button
              type="button"
              className="primary-button"
              disabled={isSubmitting}
              onClick={() => onApproveWithGrant?.(approval.approval_id)}
            >
              本会话内允许
            </button>
          )}
        </div>
      )}
    </section>
  );
}
