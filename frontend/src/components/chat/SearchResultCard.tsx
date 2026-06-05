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
          <p className="chat-card-summary">选择结果后由 Agent 发起下载审批。</p>
        </div>
        <span className="status-pill">Agent search</span>
      </header>

      <div className="candidate-list" role="list" aria-label="搜索结果列表">
        {results.map((candidate, index) => (
          <div key={`${candidate.id}-${index}`} className="candidate-row" role="listitem" data-selected="false">
            <div className="candidate-body">
              <div className="candidate-heading">
                <span className="candidate-title">{candidate.title}</span>
                {candidate.discount ? <span className="candidate-badge">{candidate.discount}</span> : null}
              </div>
              <div className="candidate-meta">
                <span>{candidate.resolution || "分辨率待定"}</span>
                <span>{candidate.size || "大小待定"}</span>
                <span>{candidate.seeders} seeders</span>
                <span>{candidate.leechers ?? 0} leechers</span>
                <span>Torrent ID {candidate.id}</span>
              </div>
              {candidate.imdb || candidate.douban ? (
                <div className="candidate-identifiers">
                  {candidate.imdb ? <span>IMDb {candidate.imdb}</span> : null}
                  {candidate.douban ? <span>豆瓣 {candidate.douban}</span> : null}
                </div>
              ) : null}
            </div>
            <button
              type="button"
              className="primary-button"
              disabled={isSubmitting}
              onClick={() => onDownload(candidate.id)}
            >
              {isSubmitting ? "请求中" : "请求下载"}
            </button>
          </div>
        ))}
      </div>
    </section>
  );
}
