export function SettingsPanel({ id, labelledBy }: { id: string; labelledBy: string }) {
  return (
    <section className="settings-panel" id={id} role="tabpanel" aria-labelledby={labelledBy}>
      <header className="panel-heading">
        <h1>运行状态</h1>
        <p>只读状态页，连接状态和运行信息会显示在这里。</p>
      </header>
    </section>
  );
}
