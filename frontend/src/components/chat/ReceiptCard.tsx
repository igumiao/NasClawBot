type ReceiptCardProps = {
  receipt: Record<string, unknown>;
};

export function ReceiptCard({ receipt }: ReceiptCardProps) {
  return (
    <section className="chat-card" aria-labelledby="receipt-card-title">
      <header className="chat-card-header">
        <h2 className="chat-card-title" id="receipt-card-title">
          下载回执
        </h2>
        <span className="status-pill">Paused</span>
      </header>
      <pre className="chat-card-json">{JSON.stringify(receipt, null, 2)}</pre>
    </section>
  );
}
