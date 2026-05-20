import { useId } from "react";
import type { ConfirmationPayload } from "../../types/api";

const SUMMARY_FALLBACK = "推荐项已选中，提交后会以暂停状态加入 qB。";

type CandidateCardProps = {
  payload: ConfirmationPayload;
  selectedResultId: string | null;
  isSubmitting: boolean;
  isDisabled?: boolean;
  onSelect: (id: string) => void;
  onApprove: () => void;
  onCancel: () => void;
  onRewrite: () => void;
};

export function CandidateCard({
  payload,
  selectedResultId,
  isSubmitting,
  isDisabled = false,
  onSelect,
  onApprove,
  onCancel,
  onRewrite
}: CandidateCardProps) {
  const instanceId = useId();
  const titleId = `${instanceId}-candidate-card-title`;
  const radioGroupName = `${instanceId}-candidate-result`;
  const controlsDisabled = isDisabled || isSubmitting;
  const approvalDisabled = controlsDisabled || selectedResultId === null;

  return (
    <section className="chat-card" aria-labelledby={titleId}>
      <header className="chat-card-header">
        <div>
          <h2 className="chat-card-title" id={titleId}>
            搜索候选
          </h2>
          <p className="chat-card-summary">{payload.summary || SUMMARY_FALLBACK}</p>
        </div>
        <span className="status-pill">Human approval</span>
      </header>

      <div className="candidate-list" role="radiogroup" aria-label="搜索候选列表">
        {payload.results.map((candidate) => {
          const checked = candidate.id === selectedResultId;

          return (
            <label
              key={candidate.id}
              className="candidate-row"
              data-selected={checked ? "true" : "false"}
            >
              <input
                type="radio"
                name={radioGroupName}
                aria-label={candidate.title}
                checked={checked}
                disabled={controlsDisabled}
                onChange={() => onSelect(candidate.id)}
              />
              <div className="candidate-body">
                <div className="candidate-heading">
                  <span className="candidate-title">{candidate.title}</span>
                  {candidate.id === payload.recommended_result_id ? (
                    <span className="candidate-badge">推荐</span>
                  ) : null}
                </div>
                <div className="candidate-meta">
                  <span>{candidate.resolution || "分辨率待定"}</span>
                  <span>{candidate.size || "大小待定"}</span>
                  <span>{candidate.seeders} seeders</span>
                </div>
              </div>
            </label>
          );
        })}
      </div>

      <div className="chat-card-actions">
        <button type="button" className="secondary-button" onClick={onCancel} disabled={controlsDisabled}>
          取消
        </button>
        <button type="button" className="secondary-button" onClick={onRewrite} disabled={controlsDisabled}>
          重新描述
        </button>
        <button
          type="button"
          className="primary-button"
          onClick={onApprove}
          disabled={approvalDisabled}
        >
          {isSubmitting ? "提交中" : "确认加入 qB"}
        </button>
      </div>
    </section>
  );
}
