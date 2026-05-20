export function DownloadsPanel({ id, labelledBy }: { id: string; labelledBy: string }) {
  return (
    <section className="downloads-panel" id={id} role="tabpanel" aria-labelledby={labelledBy}>
      <header className="panel-heading">
        <h1>下载任务</h1>
        <p>qBittorrent 任务列表会显示在这里。</p>
      </header>
    </section>
  );
}
