import { useId } from "react";

type ReceiptCardProps = {
  receipt: Record<string, unknown>;
};

export function ReceiptCard({ receipt }: ReceiptCardProps) {
  const titleId = `${useId()}-receipt-card-title`;

  return (
    <section className="chat-card" aria-labelledby={titleId}>
      <header className="chat-card-header">
        <h2 className="chat-card-title" id={titleId}>
          下载回执
        </h2>
        <span className="status-pill">Paused</span>
      </header>
      <pre className="chat-card-json">{JSON.stringify(receipt, null, 2)}</pre>
    </section>
  );
}
