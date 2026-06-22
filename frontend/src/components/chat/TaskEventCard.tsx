import { useId } from "react";
import type { TaskEventSummary } from "../../types/api";

type TaskEventCardProps = {
  event: TaskEventSummary;
  onAcknowledge: (eventId: string) => void;
};

const SEVERITY_CONFIG: Record<string, { icon: string; className: string }> = {
  success: { icon: "✓", className: "task-event-severity--success" },
  info: { icon: "ℹ", className: "task-event-severity--info" },
  warning: { icon: "⚠", className: "task-event-severity--warning" },
  error: { icon: "✗", className: "task-event-severity--error" },
};

function formatTimestamp(iso: string): string {
  try {
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return iso;
    const pad = (n: number) => String(n).padStart(2, "0");
    return `${pad(date.getHours())}:${pad(date.getMinutes())}`;
  } catch {
    return iso;
  }
}

export function TaskEventCard({ event, onAcknowledge }: TaskEventCardProps) {
  const titleId = `${useId()}-task-event-title`;
  const severity = event.severity in SEVERITY_CONFIG ? event.severity : "info";
  const { icon, className: severityClass } = SEVERITY_CONFIG[severity];

  return (
    <section
      className={`chat-card task-event-card ${severityClass}`}
      aria-labelledby={titleId}
      role="status"
    >
      <header className="chat-card-header">
        <div className="task-event-header-icon">
          <span className="task-event-icon" aria-hidden="true">{icon}</span>
          <div>
            <p className="chat-card-eyebrow">任务事件</p>
            <h2 className="chat-card-title" id={titleId}>{event.title}</h2>
          </div>
        </div>
        <div className="task-event-header-actions">
          <time className="task-event-time" dateTime={event.created_at}>
            {formatTimestamp(event.created_at)}
          </time>
          <button
            className="task-event-dismiss"
            onClick={() => onAcknowledge(event.event_id)}
            aria-label="忽略事件"
            title="忽略"
          >
            ✕
          </button>
        </div>
      </header>
      <p className="task-event-summary">{event.summary}</p>
      <footer className="task-event-footer">
        <span className="task-event-kind">{event.kind}</span>
      </footer>
    </section>
  );
}
