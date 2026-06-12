import { useId } from "react";

export type ToolActivity = {
  tool?: string;
  tool_name?: string;
  status?: string;
  arguments?: Record<string, unknown> | null;
  gate_result?: string | null;
};

type ToolActivityCardProps = {
  toolCall: ToolActivity;
};

const PRIORITY_ARGUMENTS = ["keyword", "mode", "sort_by"];

function argumentEntries(argumentsValue: Record<string, unknown> | null | undefined) {
  const entries = Object.entries(argumentsValue ?? {});
  return entries.sort(([left], [right]) => {
    const leftIndex = PRIORITY_ARGUMENTS.indexOf(left);
    const rightIndex = PRIORITY_ARGUMENTS.indexOf(right);
    if (leftIndex === -1 && rightIndex === -1) return left.localeCompare(right);
    if (leftIndex === -1) return 1;
    if (rightIndex === -1) return -1;
    return leftIndex - rightIndex;
  });
}

function formatArgument(value: unknown): string {
  if (value === "") return '""';
  if (value === undefined) return "undefined";
  if (typeof value === "string") return value;
  if (typeof value === "object" && value !== null) return JSON.stringify(value);
  return String(value);
}

export function ToolActivityCard({ toolCall }: ToolActivityCardProps) {
  const titleId = `${useId()}-tool-activity-title`;
  const toolName = toolCall.tool ?? toolCall.tool_name ?? "unknown_tool";
  const status = toolCall.status ?? toolCall.gate_result ?? "unknown";
  const entries = argumentEntries(toolCall.arguments);
  const isMemoryCard = toolName === "remember_this";
  const cardClass = `chat-card tool-activity-card${isMemoryCard ? " memory-activity-card" : ""}`;

  return (
    <section className={cardClass} aria-labelledby={titleId}>
      <header className="chat-card-header">
        <div>
          <p className="chat-card-eyebrow">工具调用</p>
          <h2 className="chat-card-title tool-activity-name" id={titleId}>
            {toolName}
          </h2>
        </div>
        <span className="status-pill" data-status={status}>
          {status}
        </span>
      </header>

      {entries.length > 0 ? (
        <dl className="tool-activity-grid" aria-label={`${toolName} 参数`}>
          {entries.map(([name, value]) => (
            <div className="tool-activity-item" key={name}>
              <dt>{name}</dt>
              <dd>{formatArgument(value)}</dd>
            </div>
          ))}
        </dl>
      ) : (
        <p className="chat-card-summary">无参数</p>
      )}
    </section>
  );
}
