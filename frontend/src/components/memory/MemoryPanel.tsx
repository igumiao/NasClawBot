import { useCallback, useEffect, useId, useState } from "react";
import {
  fetchInbox,
  fetchCuration,
  applyCuration,
  type MemoryInboxEntry,
  type CurationSuggestion,
  type CuratorApplyDecision,
} from "../../api/chatApi";

type EntryState = {
  entry: MemoryInboxEntry;
  suggestion: CurationSuggestion | null;
  editedText: string;
  destination: "user_profile" | "knowledge";
  section: string;
  status: "pending" | "applied" | "discarded";
};

export function MemoryPanel() {
  const panelId = useId();
  const [entries, setEntries] = useState<MemoryInboxEntry[]>([]);
  const [entryStates, setEntryStates] = useState<Map<number, EntryState>>(new Map());
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
      setEntryStates(new Map());
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
      const map = new Map<number, EntryState>();
      for (const s of data.suggestions) {
        const entry = entries.find((e) => e.index === s.inbox_index);
        if (entry) {
          map.set(s.inbox_index, {
            entry,
            suggestion: s,
            editedText: s.edited_text ?? entry.text,
            destination: s.destination ?? "knowledge",
            section: s.section ?? "Other",
            status: "pending",
          });
        }
      }
      setEntryStates(map);
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
    for (const state of entryStates.values()) {
      if (state.status === "applied") continue;
      const decision: CuratorApplyDecision = {
        inbox_index: state.entry.index,
        action: state.status === "discarded" ? "discard" : "keep",
        destination: state.destination,
        section: state.section,
        text: state.editedText,
      };
      decisions.push(decision);
    }

    setApplying(true);
    setError(null);
    try {
      await applyCuration(entries.length, decisions);
      setEntries((prev) =>
        prev.filter((e) => {
          const s = entryStates.get(e.index);
          return !s || (s.status !== "applied" && s.status !== "discarded");
        })
      );
      setEntryStates(new Map());
      setCurated(false);
    } catch (e) {
      setError(`应用失败: ${String(e)}`);
    } finally {
      setApplying(false);
    }
  };

  const updateEntry = (index: number, update: Partial<EntryState>) => {
    setEntryStates((prev) => {
      const next = new Map(prev);
      const current = next.get(index);
      if (current) next.set(index, { ...current, ...update });
      return next;
    });
  };

  const markApplied = (index: number) => updateEntry(index, { status: "applied" });
  const markDiscarded = (index: number) => updateEntry(index, { status: "discarded" });

  const pendingCount = Array.from(entryStates.values()).filter(
    (s) => s.status === "pending"
  ).length;
  const appliedCount = Array.from(entryStates.values()).filter(
    (s) => s.status === "applied"
  ).length;
  const discardedCount = Array.from(entryStates.values()).filter(
    (s) => s.status === "discarded"
  ).length;

  return (
    <div className="memory-panel" id={panelId}>
      <header className="memory-panel-header">
        <h2>记忆收件箱</h2>
        {entries.length > 0 && !curated && (
          <button
            className="memory-analyze-btn"
            onClick={runCuration}
            disabled={loading}
          >
            {loading ? "分析中..." : "分析"}
          </button>
        )}
      </header>

      {error && <p className="memory-error">{error}</p>}
      {loading && <p className="memory-loading">加载中...</p>}

      {!loading && entries.length === 0 && (
        <p className="memory-empty">
          暂无待整理记忆。Agent 调用 remember_this 后会出现在这里。
        </p>
      )}

      {!loading && entryStates.size === 0 && entries.length > 0 && (
        <div className="memory-unanalyzed">
          <p>收件箱中有 {entries.length} 条未分析条目。</p>
          <button onClick={runCuration}>开始分析</button>
        </div>
      )}

      {!loading && entryStates.size > 0 && (
        <div className="memory-cards">
          {Array.from(entryStates.values())
            .sort((a, b) => a.entry.index - b.entry.index)
            .map((state) => (
              <div
                key={state.entry.index}
                className={`memory-card ${state.status}`}
              >
                <header className="memory-card-header">
                  <span className="memory-card-index">
                    条目 {state.entry.index + 1}/{entries.length}
                  </span>
                  <time className="memory-card-time">
                    {state.entry.timestamp}
                  </time>
                </header>

                <textarea
                  className="memory-card-textarea"
                  value={state.editedText}
                  onChange={(e) =>
                    updateEntry(state.entry.index, { editedText: e.target.value })
                  }
                  disabled={state.status !== "pending"}
                  rows={4}
                />

                <div className="memory-card-controls">
                  <select
                    value={state.destination}
                    onChange={(e) =>
                      updateEntry(state.entry.index, {
                        destination: e.target.value as "user_profile" | "knowledge",
                      })
                    }
                    disabled={state.status !== "pending"}
                  >
                    <option value="user_profile">user_profile</option>
                    <option value="knowledge">knowledge</option>
                  </select>

                  <select
                    value={state.section}
                    onChange={(e) =>
                      updateEntry(state.entry.index, { section: e.target.value })
                    }
                    disabled={state.status !== "pending"}
                  >
                    {(sections[state.destination] ?? []).map((sec) => (
                      <option key={sec} value={sec}>
                        {sec}
                      </option>
                    ))}
                  </select>

                  {state.status === "pending" && (
                    <>
                      <button onClick={() => markApplied(state.entry.index)}>
                        应用
                      </button>
                      <button onClick={() => markDiscarded(state.entry.index)}>
                        丢弃
                      </button>
                    </>
                  )}
                  {state.status === "applied" && (
                    <span className="memory-status-badge applied">✓ 待应用</span>
                  )}
                  {state.status === "discarded" && (
                    <span className="memory-status-badge discarded">✗ 已丢弃</span>
                  )}
                </div>
              </div>
            ))}
        </div>
      )}

      {entryStates.size > 0 && pendingCount > 0 && (
        <footer className="memory-panel-footer">
          <span>
            已选 {appliedCount} 条应用 · {discardedCount} 条丢弃 · {pendingCount}{" "}
            条未处理
          </span>
          <button
            className="memory-apply-all-btn"
            onClick={applyDecisions}
            disabled={applying || appliedCount === 0}
          >
            {applying ? "应用中..." : `全部应用 (${appliedCount})`}
          </button>
        </footer>
      )}
    </div>
  );
}
