import type { ResourceCandidate } from "../../types/api";

type SearchResultCardProps = {
  results: ResourceCandidate[];
  isSubmitting: boolean;
  onDownload: (id: string) => void;
};

export function SearchResultCard({ results, isSubmitting, onDownload }: SearchResultCardProps) {
  return (
    <section className="chat-card" aria-label="搜索结果">
      <header className="chat-card-header">
        <div>
          <h2 className="chat-card-title">搜索结果</h2>
          <p className="chat-card-summary">选择一个结果后会以暂停状态加入 qB。</p>
        </div>
        <span className="status-pill">Readonly search</span>
      </header>

      <div className="candidate-list" role="list" aria-label="搜索结果列表">
        {results.map((candidate) => (
          <div key={candidate.id} className="candidate-row" role="listitem" data-selected="false">
            <div className="candidate-body">
              <div className="candidate-heading">
                <span className="candidate-title">{candidate.title}</span>
              </div>
              <div className="candidate-meta">
                <span>{candidate.resolution || "分辨率待定"}</span>
                <span>{candidate.size || "大小待定"}</span>
                <span>{candidate.seeders} seeders</span>
                <span>{candidate.source}</span>
              </div>
            </div>
            <button
              type="button"
              className="primary-button"
              disabled={isSubmitting}
              onClick={() => onDownload(candidate.id)}
            >
              {isSubmitting ? "提交中" : "加入 qB"}
            </button>
          </div>
        ))}
      </div>
    </section>
  );
}
