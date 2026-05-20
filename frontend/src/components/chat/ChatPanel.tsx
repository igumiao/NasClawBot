import type { FormEvent } from "react";

export function ChatPanel({ id, labelledBy }: { id: string; labelledBy: string }) {
  function handlePlaceholderSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
  }

  return (
    <section className="chat-panel" id={id} role="tabpanel" aria-labelledby={labelledBy}>
      <div className="chat-thread">
        <div className="chat-empty">
          <h1>今天想看什么？</h1>
          <p>输入媒体需求</p>
        </div>
      </div>
      <form className="composer-shell" onSubmit={handlePlaceholderSubmit}>
        <textarea aria-label="媒体需求" placeholder="输入媒体需求，例如：我想看一部 4K 科幻电影..." />
        <button type="submit" aria-label="发送">
          ↑
        </button>
      </form>
    </section>
  );
}
