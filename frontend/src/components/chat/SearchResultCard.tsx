import { useState } from "react";
import type { ResourceCandidate } from "../../types/api";

type SearchResultCardProps = {
  results: ResourceCandidate[];
  isSubmitting: boolean;
  onDownload: (id: string) => void;
};

export function SearchResultCard({ results, isSubmitting, onDownload }: SearchResultCardProps) {
  const [expanded, setExpanded] = useState(false);

  if (results.length === 0) return null;

  return (
    <section className="chat-card" aria-label="搜索结果" data-expanded={expanded}>
      <header className="chat-card-header">
        <div>
          <h2 className="chat-card-title">搜索结果</h2>
          <p className="chat-card-summary">
            {expanded ? `${results.length} 个结果` : `共 ${results.length} 个结果 · 已折叠`}
          </p>
        </div>
        <div className="chat-card-actions">
          <span className="status-pill">Agent search</span>
          <button
            type="button"
            className="toggle-button"
            onClick={() => setExpanded((prev) => !prev)}
            aria-expanded={expanded}
          >
            {expanded ? "收起 ▲" : "展开 ▼"}
          </button>
        </div>
      </header>

      {expanded && (
        <div className="candidate-list" role="list" aria-label="搜索结果列表">
          {results.map((candidate, index) => (
            <div key={`${candidate.id}-${index}`} className="candidate-row" role="listitem" data-selected="false">
              <div className="candidate-body">
                <div className="candidate-heading">
                  <span className="candidate-title">{candidate.title}</span>
                  {(candidate.subtitle_flags ?? []).map((flag) => (
                    <span key={flag} className={`subtitle-flag subtitle-flag--${flag}`}>{flag}</span>
                  ))}
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
      )}
    </section>
  );
}
