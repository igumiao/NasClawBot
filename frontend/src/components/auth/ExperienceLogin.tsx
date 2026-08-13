import { FormEvent, useEffect, useRef, useState } from "react";
import { ArrowRight, KeyRound, LoaderCircle } from "lucide-react";

type ExperienceLoginProps = {
  isSubmitting: boolean;
  error: string | null;
  onSubmit: (code: string) => Promise<void>;
};

export function ExperienceLogin({ isSubmitting, error, onSubmit }: ExperienceLoginProps) {
  const [code, setCode] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (code.length !== 5 || isSubmitting) return;
    await onSubmit(code);
  }

  return (
    <main className="experience-login-shell">
      <section className="experience-login-card" aria-labelledby="experience-login-title">
        <img className="experience-login-logo" src="/brand-logo.png" alt="NasClawBot" />
        <div className="experience-login-heading">
          <span className="experience-login-eyebrow">PROJECT EXPERIENCE</span>
          <h1 id="experience-login-title">体验 NasClawBot</h1>
          <p>输入简历中提供的 5 位体验代码，即可进入完整项目。</p>
        </div>

        <form className="experience-login-form" onSubmit={handleSubmit}>
          <label htmlFor="experience-code">体验代码</label>
          <div className="experience-code-field">
            <KeyRound size={18} aria-hidden="true" />
            <input
              ref={inputRef}
              id="experience-code"
              name="experience-code"
              type="text"
              inputMode="text"
              autoComplete="one-time-code"
              pattern="[A-Za-z0-9]{5}"
              maxLength={5}
              spellCheck={false}
              value={code}
              disabled={isSubmitting}
              aria-invalid={Boolean(error)}
              aria-describedby={error ? "experience-login-error" : undefined}
              onChange={(event) => setCode(event.target.value.replace(/[^A-Za-z0-9]/g, "").slice(0, 5))}
              placeholder="•••••"
            />
          </div>
          {error ? (
            <p className="experience-login-error" id="experience-login-error" role="alert">
              {error}
            </p>
          ) : null}
          <button type="submit" disabled={code.length !== 5 || isSubmitting}>
            {isSubmitting ? <LoaderCircle className="experience-login-spinner" size={18} /> : <ArrowRight size={18} />}
            {isSubmitting ? "正在验证" : "进入体验"}
          </button>
        </form>

        <p className="experience-login-note">
          公网登录保持 1 小时 · 本地设备长期有效
          <br />
          为统计体验并保障安全，公网成功登录会登记 IP 与时间，最长保存 180 天。
        </p>
      </section>
    </main>
  );
}
