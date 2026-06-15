import { useCallback, useEffect, useId, useState } from "react";
import {
  fetchInbox,
  fetchCuration,
  applyCuration,
  type MemoryInboxEntry,
  type CurationSuggestion,
  type CuratorApplyDecision,
} from "../../api/chatApi";

type CardStatus = "pending" | "keep" | "discard" | "modify" | "delete";

type CardState = {
  suggestion: CurationSuggestion;
  entry: MemoryInboxEntry | null;
  editedText: string;
  destination: "user_profile" | "knowledge";
  section: string;
  status: CardStatus;
};

export function MemoryPanel() {
  const panelId = useId();
  const [entries, setEntries] = useState<MemoryInboxEntry[]>([]);
  const [cardStates, setCardStates] = useState<CardState[]>([]);
  const [sections, setSections] = useState<{ user_profile: string[]; knowledge: string[] }>({
    user_profile: [],
    knowledge: [],
  });
  const [loading, setLoading] = useState(false);
  const [applying, setApplying] = useState(false);
  const [curated, setCurated] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadInbox = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchInbox();
      setEntries(data.entries);
      setCardStates([]);
      setCurated(false);
    } catch (e) {
      setError("无法加载收件箱");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadInbox();
  }, [loadInbox]);

  const runCuration = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchCuration();
      const cards: CardState[] = [];
      for (const s of data.suggestions) {
        const entry = s.inbox_index != null
          ? entries.find((e) => e.index === s.inbox_index) ?? null
          : null;
        let status: CardStatus = "pending";
        let editedText = "";
        if (s.action === "modify") {
          status = "modify";
          editedText = s.new_text ?? "";
        } else if (s.action === "delete") {
          status = "delete";
          editedText = "";
        } else {
          status = "pending";
          editedText = s.edited_text ?? entry?.text ?? "";
        }
        cards.push({
          suggestion: s,
          entry,
          editedText,
          destination: s.destination ?? "knowledge",
          section: s.section ?? "Other",
          status,
        });
      }
      setCardStates(cards);
      setSections(data.sections);
      setCurated(true);
    } catch (e) {
      setError("记忆分析失败");
    } finally {
      setLoading(false);
    }
  };

  const applyDecisions = async () => {
    const decisions: CuratorApplyDecision[] = [];
    for (const card of cardStates) {
      if (card.status === "pending") continue;
      if (card.status === "keep") {
        decisions.push({
          action: "keep",
          inbox_index: card.entry?.index,
          destination: card.destination,
          section: card.section,
          text: card.editedText,
        });
      } else if (card.status === "discard") {
        decisions.push({
          action: "discard",
          inbox_index: card.entry?.index,
        });
      } else if (card.status === "modify") {
        decisions.push({
          action: "modify",
          destination: card.destination,
          existing_text: card.suggestion.existing_text ?? undefined,
          new_text: card.editedText,
        });
      } else if (card.status === "delete") {
        decisions.push({
          action: "delete",
          destination: card.destination,
          existing_text: card.suggestion.existing_text ?? undefined,
        });
      }
    }

    setApplying(true);
    setError(null);
    try {
      await applyCuration(entries.length, decisions);
      setEntries((prev) =>
        prev.filter((e) => {
          const card = cardStates.find(
            (c) => c.entry?.index === e.index && (c.status === "keep" || c.status === "discard")
          );
          return !card;
        })
      );
      setCardStates([]);
      setCurated(false);
    } catch (e) {
      setError(`应用失败: ${String(e)}`);
    } finally {
      setApplying(false);
    }
  };

  const updateCard = (index: number, update: Partial<CardState>) => {
    setCardStates((prev) => {
      const next = [...prev];
      if (index >= 0 && index < next.length) {
        next[index] = { ...next[index], ...update };
      }
      return next;
    });
  };

  const markKeep = (index: number) => updateCard(index, { status: "keep" });
  const markDiscard = (index: number) => updateCard(index, { status: "discard" });
  const markModify = (index: number) => updateCard(index, { status: "modify" });
  const markDelete = (index: number) => updateCard(index, { status: "delete" });

  const pendingCount = cardStates.filter((c) => c.status === "pending").length;
  const keepCount = cardStates.filter((c) => c.status === "keep").length;
  const discardCount = cardStates.filter((c) => c.status === "discard").length;
  const modifyCount = cardStates.filter((c) => c.status === "modify").length;
  const deleteCount = cardStates.filter((c) => c.status === "delete").length;
  const totalDecided = keepCount + discardCount + modifyCount + deleteCount;

  return (
    <div className="memory-panel" id={panelId}>
      <header className="memory-panel-header">
        <h2>记忆收件箱</h2>
        {entries.length > 0 && !curated && (
          <button className="memory-analyze-btn" onClick={runCuration} disabled={loading}>
            {loading ? "分析中..." : "分析"}
          </button>
        )}
      </header>

      {error && <p className="memory-error">{error}</p>}
      {loading && <p className="memory-loading">加载中...</p>}

      {!loading && entries.length === 0 && cardStates.length === 0 && (
        <p className="memory-empty">
          暂无待整理记忆。Agent 调用 remember_this 后会出现在这里。
        </p>
      )}

      {!loading && cardStates.length === 0 && entries.length > 0 && (
        <div className="memory-unanalyzed">
          <p>收件箱中有 {entries.length} 条未分析条目。</p>
          <button onClick={runCuration}>开始分析</button>
        </div>
      )}

      {!loading && cardStates.length > 0 && (
        <div className="memory-cards">
          {cardStates.map((card, idx) => {
            const isInbox = card.suggestion.action === "keep" || card.suggestion.action === "discard";
            const isModify = card.suggestion.action === "modify";
            const isDelete = card.suggestion.action === "delete";
            const isDecided = card.status !== "pending";

            return (
              <div key={idx} className={`memory-card ${card.status}`}>
                <header className="memory-card-header">
                  <span className="memory-card-index">
                    {isInbox && card.entry
                      ? `条目 ${card.entry.index + 1}/${entries.length}`
                      : isModify
                      ? "✎ 修改建议"
                      : "✕ 删除建议"}
                  </span>
                  {card.entry && (
                    <time className="memory-card-time">{card.entry.timestamp}</time>
                  )}
                </header>

                {card.suggestion.reason && (isModify || isDelete) && (
                  <p className="memory-card-reason">原因：{card.suggestion.reason}</p>
                )}

                {isInbox && (
                  <textarea
                    className="memory-card-textarea"
                    value={card.editedText}
                    onChange={(e) => updateCard(idx, { editedText: e.target.value })}
                    disabled={isDecided}
                    rows={4}
                  />
                )}

                {isModify && card.suggestion.existing_text && (
                  <>
                    <div className="memory-card-existing">{card.suggestion.existing_text}</div>
                    <textarea
                      className="memory-card-new-textarea"
                      value={card.editedText}
                      onChange={(e) => updateCard(idx, { editedText: e.target.value })}
                      disabled={isDecided}
                      rows={3}
                    />
                  </>
                )}

                {isDelete && card.suggestion.existing_text && (
                  <div className="memory-card-existing">{card.suggestion.existing_text}</div>
                )}

                <div className="memory-card-controls">
                  {(isInbox || isModify) && (
                    <select
                      value={card.destination}
                      onChange={(e) =>
                        updateCard(idx, { destination: e.target.value as "user_profile" | "knowledge" })
                      }
                      disabled={isDecided}
                    >
                      <option value="user_profile">user_profile</option>
                      <option value="knowledge">knowledge</option>
                    </select>
                  )}

                  <select
                    value={card.section}
                    onChange={(e) => updateCard(idx, { section: e.target.value })}
                    disabled={isDecided || isDelete}
                  >
                    {(sections[card.destination] ?? []).map((sec) => (
                      <option key={sec} value={sec}>{sec}</option>
                    ))}
                  </select>

                  {isInbox && card.status === "pending" && (
                    <>
                      <button onClick={() => markKeep(idx)}>应用</button>
                      <button onClick={() => markDiscard(idx)}>丢弃</button>
                    </>
                  )}
                  {isInbox && card.status === "keep" && (
                    <span className="memory-status-badge applied">✓ 待应用</span>
                  )}
                  {isInbox && card.status === "discard" && (
                    <span className="memory-status-badge discarded">✗ 已丢弃</span>
                  )}

                  {isModify && card.status === "modify" && (
                    <span className="memory-status-badge modify">✓ 待应用修改</span>
                  )}

                  {isDelete && card.status === "delete" && (
                    <span className="memory-status-badge delete">✗ 待删除</span>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {cardStates.length > 0 && (totalDecided > 0 || pendingCount > 0) && (
        <footer className="memory-panel-footer">
          <span>
            已选 {keepCount} 条应用 · {modifyCount} 条修改 · {deleteCount}{" "}
            条删除 · {discardCount} 条丢弃 · {pendingCount} 条未处理
          </span>
          <button
            className="memory-apply-all-btn"
            onClick={applyDecisions}
            disabled={applying || totalDecided === 0}
          >
            {applying ? "应用中..." : `全部应用 (${totalDecided})`}
          </button>
        </footer>
      )}
    </div>
  );
}
