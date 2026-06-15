import { useCallback, useEffect, useId, useState } from "react";
import {
  fetchInbox,
  fetchCuration,
  applyCuration,
  type MemoryInboxEntry,
  type CurationSuggestion,
  type CuratorApplyDecision,
} from "../../api/chatApi";

type CardStatus = "keep" | "discard" | "modify" | "delete" | "skipped";

type CardState = {
  suggestion: CurationSuggestion;
  entry: MemoryInboxEntry | null;
  editedText: string;
  destination: "user_profile" | "knowledge";
  section: string;
  status: CardStatus;
};

export function MemoryPanel({ visible }: { visible: boolean }) {
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
    if (visible) {
      loadInbox();
    }
  }, [visible, loadInbox]);

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
        let status: CardStatus;
        let editedText = "";
        if (s.action === "modify") {
          status = "modify";
          editedText = s.new_text ?? "";
        } else if (s.action === "delete") {
          status = "delete";
          editedText = "";
        } else if (s.action === "keep") {
          status = "keep";
          editedText = s.edited_text ?? entry?.text ?? "";
        } else {
          // discard
          status = "discard";
          editedText = entry?.text ?? "";
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
      if (card.status === "skipped") continue;
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

  const skipCard = (index: number) => updateCard(index, { status: "skipped" });
  const unskipCard = (index: number) => {
    // restore the original action
    const original = cardStates[index].suggestion.action;
    if (original === "keep" || original === "discard" || original === "modify" || original === "delete") {
      updateCard(index, { status: original });
    }
  };

  const keepCount = cardStates.filter((c) => c.status === "keep").length;
  const discardCount = cardStates.filter((c) => c.status === "discard").length;
  const modifyCount = cardStates.filter((c) => c.status === "modify").length;
  const deleteCount = cardStates.filter((c) => c.status === "delete").length;
  const skippedCount = cardStates.filter((c) => c.status === "skipped").length;
  const totalActive = keepCount + discardCount + modifyCount + deleteCount;

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
            const isSkipped = card.status === "skipped";
            const isActive = !isSkipped;
            const hasReason = !!card.suggestion.reason;

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

                {/* Reason — show for all cards that have one */}
                {hasReason && (
                  <p className="memory-card-reason">原因：{card.suggestion.reason}</p>
                )}

                {/* Keep card: editable textarea */}
                {card.suggestion.action === "keep" && (
                  <textarea
                    className="memory-card-textarea"
                    value={card.editedText}
                    onChange={(e) => updateCard(idx, { editedText: e.target.value })}
                    disabled={isSkipped}
                    rows={4}
                  />
                )}

                {/* Discard card: read-only preview */}
                {card.suggestion.action === "discard" && (
                  <div className="memory-card-existing">{card.editedText}</div>
                )}

                {/* Modify card: strikethrough existing + editable new */}
                {isModify && card.suggestion.existing_text && (
                  <>
                    <div className="memory-card-existing">{card.suggestion.existing_text}</div>
                    <textarea
                      className="memory-card-new-textarea"
                      value={card.editedText}
                      onChange={(e) => updateCard(idx, { editedText: e.target.value })}
                      disabled={isSkipped}
                      rows={3}
                    />
                  </>
                )}

                {/* Delete card: strikethrough existing */}
                {isDelete && card.suggestion.existing_text && (
                  <div className="memory-card-existing">{card.suggestion.existing_text}</div>
                )}

                <div className="memory-card-controls">
                  {/* Destination dropdown (not for delete) */}
                  {(isInbox || isModify) && (
                    <select
                      value={card.destination}
                      onChange={(e) =>
                        updateCard(idx, { destination: e.target.value as "user_profile" | "knowledge" })
                      }
                      disabled={isSkipped}
                    >
                      <option value="user_profile">user_profile</option>
                      <option value="knowledge">knowledge</option>
                    </select>
                  )}

                  {/* Section dropdown (not for delete) */}
                  <select
                    value={card.section}
                    onChange={(e) => updateCard(idx, { section: e.target.value })}
                    disabled={isSkipped || isDelete}
                  >
                    {(sections[card.destination] ?? []).map((sec) => (
                      <option key={sec} value={sec}>{sec}</option>
                    ))}
                  </select>

                  {/* Status badge */}
                  {isActive && (
                    <span className={`memory-status-badge ${card.status}`}>
                      {card.status === "keep" && "将被应用"}
                      {card.status === "discard" && "将被丢弃"}
                      {card.status === "modify" && "将被修改"}
                      {card.status === "delete" && "将被删除"}
                    </span>
                  )}
                  {isSkipped && (
                    <span className="memory-status-badge skipped">已跳过</span>
                  )}

                  {/* Skip / Undo button */}
                  {isActive && (
                    <button className="skip-btn" onClick={() => skipCard(idx)}>
                      跳过
                    </button>
                  )}
                  {isSkipped && (
                    <button className="skip-btn" onClick={() => unskipCard(idx)}>
                      撤销
                    </button>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {cardStates.length > 0 && (
        <footer className="memory-panel-footer">
          <span>
            共 {cardStates.length} 条建议：{keepCount} 应用 · {modifyCount} 修改 · {deleteCount}{" "}
            删除 · {discardCount} 丢弃{skippedCount > 0 ? ` · ${skippedCount} 跳过` : ""}
          </span>
          <button
            className="memory-apply-all-btn"
            onClick={applyDecisions}
            disabled={applying || totalActive === 0}
          >
            {applying ? "应用中..." : `全部应用 (${totalActive})`}
          </button>
        </footer>
      )}
    </div>
  );
}
