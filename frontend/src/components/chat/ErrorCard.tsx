type ErrorCardProps = {
  title: string;
  detail: string;
};

export function ErrorCard({ title, detail }: ErrorCardProps) {
  return (
    <section className="chat-card error-card" role="alert" aria-live="assertive">
      <h2 className="chat-card-title">{title}</h2>
      <p className="chat-card-summary">{detail}</p>
    </section>
  );
}
