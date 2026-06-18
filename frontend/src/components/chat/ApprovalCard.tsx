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
  failed: "此审批执行失败，请重新发起下载请求。",
  expired: "此审批已过期，请重新发起下载请求。"
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
  const torrentId = String(argumentsValue.torrent_id ?? "未提供");
  const qbCategory = String(argumentsValue.qb_category ?? "mteam");
  const savePath = argumentsValue.save_path ? String(argumentsValue.save_path) : null;
  const items = batchItems(argumentsValue);
  const displayStatus: ApprovalCardStatus = status === "pending" && isPast(approval.expires_at) ? "expired" : status;
  const isPending = displayStatus === "pending";
  const isBatch = items.length > 0;
  const canGrant = approval.authorization?.eligible === true && typeof onApproveWithGrant === "function";

  return (
    <section className="chat-card approval-card" aria-labelledby={titleId}>
      <header className="chat-card-header">
        <div>
          <p className="chat-card-eyebrow">需要确认</p>
          <h2 className="chat-card-title" id={titleId}>
            {approval.tool_name ?? "工具调用"}
          </h2>
        </div>
        <span className="status-pill" data-status={displayStatus}>
          {STATUS_LABELS[displayStatus]}
        </span>
      </header>

      <p className="approval-risk">{approval.risk?.summary ?? "该操作会产生外部副作用。"}</p>

      <dl className="approval-details">
        {isBatch ? (
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
