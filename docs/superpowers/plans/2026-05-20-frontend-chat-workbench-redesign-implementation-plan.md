# Frontend Chat Workbench Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the plain browser shell with a React + assistant-ui-inspired ChatGPT-like workbench using the approved Warm Paper White theme.

**Architecture:** Build a Vite React TypeScript app under `frontend/`, keep FastAPI as the backend, and wrap existing `/chat`, `/confirm`, `/health`, and `/qb/*` routes with typed frontend API modules. assistant-ui provides the chat runtime shell, while NasClawBot-specific candidate, receipt, and qB task UI stays in explicit React state.

**Tech Stack:** Vite, React, TypeScript, assistant-ui, lucide-react, Vitest, Testing Library, FastAPI static serving.

---

## File Map

Create or replace frontend app files:

- `frontend/package.json`: npm scripts and frontend dependencies.
- `frontend/index.html`: Vite app root.
- `frontend/tsconfig.json`: browser TypeScript config.
- `frontend/tsconfig.node.json`: Vite config TypeScript config.
- `frontend/vite.config.ts`: Vite dev server, proxy, test config.
- `frontend/src/main.tsx`: React entrypoint.
- `frontend/src/app/App.tsx`: app composition and providers.
- `frontend/src/app/AppShell.tsx`: sidebar, tabs, and active panel layout.
- `frontend/src/app/theme.css`: Warm Paper White tokens and shared layout CSS.
- `frontend/src/api/chatApi.ts`: `/chat` and `/confirm` wrappers.
- `frontend/src/api/downloadsApi.ts`: qB route wrappers.
- `frontend/src/api/healthApi.ts`: `/health` wrapper.
- `frontend/src/components/chat/ChatPanel.tsx`: assistant-ui runtime wrapper and chat panel.
- `frontend/src/components/chat/CandidateCard.tsx`: search result selection and approval card.
- `frontend/src/components/chat/ReceiptCard.tsx`: structured receipt display.
- `frontend/src/components/chat/ErrorCard.tsx`: inline error display.
- `frontend/src/components/downloads/DownloadsPanel.tsx`: qB task list/detail/actions panel.
- `frontend/src/components/settings/SettingsPanel.tsx`: read-only health/session status.
- `frontend/src/components/layout/ConversationSidebar.tsx`: future conversation history shell.
- `frontend/src/components/layout/WorkspaceTabs.tsx`: segmented top tabs.
- `frontend/src/state/chatState.ts`: chat reducer, message/card types, helpers.
- `frontend/src/state/downloadsState.ts`: downloads reducer and filters.
- `frontend/src/state/uiState.ts`: workspace tab state.
- `frontend/src/types/api.ts`: frontend API types matching Pydantic response shapes.
- `frontend/src/test/setup.ts`: Testing Library setup.

Modify backend static serving:

- `app/main.py`: serve Vite build assets from `frontend/dist` when present, while preserving current dev behavior.
- `app/api/chat_routes.py`: read `frontend/dist/index.html` first, fallback to `frontend/index.html`.

Add or update tests:

- `frontend/src/api/chatApi.test.ts`
- `frontend/src/api/downloadsApi.test.ts`
- `frontend/src/state/chatState.test.ts`
- `frontend/src/state/downloadsState.test.ts`
- `frontend/src/app/AppShell.test.tsx`
- `frontend/src/components/chat/CandidateCard.test.tsx`
- `frontend/src/components/downloads/DownloadsPanel.test.tsx`
- `frontend/src/components/settings/SettingsPanel.test.tsx`
- `tests/test_frontend_static.py`

## Task 1: Frontend Tooling Foundation

**Files:**

- Create: `frontend/package.json`
- Create: `frontend/index.html`
- Create: `frontend/tsconfig.json`
- Create: `frontend/tsconfig.node.json`
- Create: `frontend/vite.config.ts`
- Create: `frontend/src/main.tsx`
- Create: `frontend/src/test/setup.ts`
- Create: `frontend/src/app/App.tsx`
- Create: `frontend/src/app/theme.css`
- Create: `frontend/src/smoke.test.ts`

- [ ] **Step 1: Write the smoke test**

Create `frontend/src/smoke.test.ts`:

```ts
import { describe, expect, it } from "vitest";

describe("frontend test harness", () => {
  it("runs vitest in jsdom", () => {
    expect(document.createElement("div")).toBeInstanceOf(HTMLDivElement);
  });
});
```

- [ ] **Step 2: Add package and TypeScript/Vite config**

Create `frontend/package.json`:

```json
{
  "name": "nasclawbot-frontend",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite --host 127.0.0.1",
    "build": "tsc -b && vite build",
    "preview": "vite preview --host 127.0.0.1",
    "test": "vitest run",
    "test:watch": "vitest",
    "typecheck": "tsc -b"
  },
  "dependencies": {
    "@assistant-ui/react": "latest",
    "lucide-react": "latest",
    "react": "latest",
    "react-dom": "latest"
  },
  "devDependencies": {
    "@vitejs/plugin-react": "latest",
    "@testing-library/jest-dom": "latest",
    "@testing-library/react": "latest",
    "@testing-library/user-event": "latest",
    "@types/react": "latest",
    "@types/react-dom": "latest",
    "jsdom": "latest",
    "typescript": "latest",
    "vite": "latest",
    "vitest": "latest"
  }
}
```

Create `frontend/tsconfig.json`:

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "useDefineForClassFields": true,
    "lib": ["DOM", "DOM.Iterable", "ES2022"],
    "allowJs": false,
    "skipLibCheck": true,
    "esModuleInterop": true,
    "allowSyntheticDefaultImports": true,
    "strict": true,
    "forceConsistentCasingInFileNames": true,
    "module": "ESNext",
    "moduleResolution": "Node",
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "react-jsx"
  },
  "include": ["src"],
  "references": [{ "path": "./tsconfig.node.json" }]
}
```

Create `frontend/tsconfig.node.json`:

```json
{
  "compilerOptions": {
    "composite": true,
    "module": "ESNext",
    "moduleResolution": "Node",
    "allowSyntheticDefaultImports": true
  },
  "include": ["vite.config.ts"]
}
```

Create `frontend/vite.config.ts`:

```ts
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/chat": "http://127.0.0.1:8000",
      "/confirm": "http://127.0.0.1:8000",
      "/health": "http://127.0.0.1:8000",
      "/qb": "http://127.0.0.1:8000"
    }
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    globals: true
  }
});
```

Create `frontend/src/test/setup.ts`:

```ts
import "@testing-library/jest-dom/vitest";
```

Create `frontend/index.html`:

```html
<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>NasClawBot</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

Create `frontend/src/app/App.tsx`:

```tsx
import "./theme.css";

export function App() {
  return (
    <main className="app-loading-shell">
      <h1>NasClawBot</h1>
      <p>Frontend workbench is starting.</p>
    </main>
  );
}
```

Create `frontend/src/app/theme.css`:

```css
:root {
  color-scheme: light;
  --app-bg: #fffefd;
  --sidebar-bg: #f8f6f2;
  --surface: #ffffff;
  --surface-soft: #f5f3ee;
  --surface-subtle: #fbfaf7;
  --border: #e7e1d8;
  --border-strong: #d6cbbd;
  --text: #1f1c18;
  --text-soft: #453f37;
  --muted: #776f65;
  --primary: #24201b;
  --success: #2f7a54;
  --warning: #98680f;
  --danger: #c65f36;
  --radius: 8px;
}

* {
  box-sizing: border-box;
}

body {
  margin: 0;
  min-height: 100vh;
  background: var(--app-bg);
  color: var(--text);
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}

button,
input,
textarea {
  font: inherit;
}

.app-loading-shell {
  min-height: 100vh;
  display: grid;
  place-content: center;
  gap: 8px;
}
```

Create `frontend/src/main.tsx`:

```tsx
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./app/App";

const root = document.getElementById("root");

if (!root) {
  throw new Error("Missing #root element");
}

createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
```

- [ ] **Step 3: Install dependencies**

Run:

```bash
cd frontend
npm install
```

Expected: `package-lock.json` is created and npm exits with code 0.

- [ ] **Step 4: Run the smoke test**

Run:

```bash
cd frontend
npm test -- src/smoke.test.ts
```

Expected: PASS with `frontend test harness`.

- [ ] **Step 5: Run typecheck**

Run:

```bash
cd frontend
npm run typecheck
```

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

```bash
git add frontend/package.json frontend/package-lock.json frontend/index.html frontend/tsconfig.json frontend/tsconfig.node.json frontend/vite.config.ts frontend/src
git commit -m "feat: scaffold react frontend"
```

## Task 2: Typed API Wrappers

**Files:**

- Create: `frontend/src/types/api.ts`
- Create: `frontend/src/api/http.ts`
- Create: `frontend/src/api/chatApi.ts`
- Create: `frontend/src/api/downloadsApi.ts`
- Create: `frontend/src/api/healthApi.ts`
- Create: `frontend/src/api/chatApi.test.ts`
- Create: `frontend/src/api/downloadsApi.test.ts`

- [ ] **Step 1: Write API wrapper tests**

Create `frontend/src/api/chatApi.test.ts`:

```ts
import { afterEach, describe, expect, it, vi } from "vitest";
import { chatApi } from "./chatApi";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("chatApi", () => {
  it("posts a chat message with the current session", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          session_id: "session-1",
          status: "awaiting_confirmation",
          confirmation_payload: {
            summary: "Review candidates",
            recommended_result_id: "r1",
            results: [{ id: "r1", title: "Dune", seeders: 10, resolution: "2160p", size: "60 GB" }],
            selected_result_id: null,
            qb_category: "movies",
            execution_result: null,
            receipt: null
          },
          receipt: null,
          error: null
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );

    const result = await chatApi.sendMessage("session-1", "Dune tonight");

    expect(fetchMock).toHaveBeenCalledWith(
      "/chat",
      expect.objectContaining({
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: "session-1", message: "Dune tonight" })
      }),
    );
    expect(result.confirmation_payload?.results[0]?.title).toBe("Dune");
  });

  it("posts approval with selected result and payload", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          session_id: "session-1",
          status: "submitted_paused",
          confirmation_payload: null,
          receipt: { status: "submitted_paused", qb_hash: "abc" },
          error: null,
          messages: []
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );

    await chatApi.confirmDownload("session-1", {
      summary: "Review",
      recommended_result_id: "r1",
      results: [{ id: "r1", title: "Dune", seeders: 10, resolution: "2160p", size: "60 GB" }],
      selected_result_id: null,
      qb_category: "movies",
      execution_result: null,
      receipt: null
    }, "r1");

    expect(fetchMock).toHaveBeenCalledWith(
      "/confirm",
      expect.objectContaining({
        method: "POST",
        body: expect.stringContaining('"action":"approve"')
      }),
    );
  });
});
```

Create `frontend/src/api/downloadsApi.test.ts`:

```ts
import { afterEach, describe, expect, it, vi } from "vitest";
import { downloadsApi } from "./downloadsApi";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("downloadsApi", () => {
  it("lists qB torrents", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          items: [
            {
              hash: "hash-1",
              name: "Dune",
              category: "movies",
              tags: ["mteam"],
              state: "pausedDL",
              progress: 0.42,
              download_speed: 0,
              upload_speed: 0,
              eta: 3600,
              save_path: "/downloads",
              size: 100,
              total_size: 100
            }
          ]
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );

    const result = await downloadsApi.listTorrents();

    expect(result.items).toHaveLength(1);
    expect(result.items[0]?.hash).toBe("hash-1");
  });

  it("runs a torrent action", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ ok: true, status: "paused", qb_hash: "hash-1" }), {
        status: 200,
        headers: { "Content-Type": "application/json" }
      }),
    );

    const result = await downloadsApi.runTorrentAction("hash-1", "pause");

    expect(fetchMock).toHaveBeenCalledWith(
      "/qb/torrents/hash-1/actions",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ action: "pause", delete_files: false })
      }),
    );
    expect(result.ok).toBe(true);
  });
});
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
cd frontend
npm test -- src/api/chatApi.test.ts src/api/downloadsApi.test.ts
```

Expected: FAIL because `chatApi`, `downloadsApi`, and API types do not exist.

- [ ] **Step 3: Add API types and HTTP helper**

Create `frontend/src/types/api.ts`:

```ts
export type ConfirmationCandidate = {
  id: string;
  title: string;
  seeders: number;
  resolution: string | null;
  size: string | null;
};

export type ConfirmationPayload = {
  summary: string;
  recommended_result_id: string | null;
  results: ConfirmationCandidate[];
  selected_result_id: string | null;
  qb_category: string | null;
  execution_result: Record<string, unknown> | null;
  receipt: Record<string, unknown> | null;
};

export type ChatResponse = {
  session_id: string;
  status: string;
  confirmation_payload: ConfirmationPayload | null;
  receipt: Record<string, unknown> | null;
  error: string | null;
};

export type ConfirmResponse = ChatResponse & {
  messages: string[];
};

export type TorrentSummary = {
  hash: string;
  name: string;
  category: string;
  tags: string[];
  state: string;
  progress: number;
  download_speed: number;
  upload_speed: number;
  eta: number;
  save_path: string;
  size: number;
  total_size: number;
};

export type TorrentDetail = TorrentSummary & {
  comment: string;
  total_uploaded: number;
  share_ratio: number;
  creation_date: number;
};

export type TorrentListResponse = {
  items: TorrentSummary[];
};

export type TorrentAction = "pause" | "resume" | "recheck" | "reannounce" | "delete";

export type TorrentActionResponse = {
  ok: boolean;
  status: string;
  qb_hash: string | null;
};

export type HealthResponse = {
  status: string;
};
```

Create `frontend/src/api/http.ts`:

```ts
export async function readJson<T>(response: Response): Promise<T> {
  const body = (await response.json()) as T;
  if (!response.ok) {
    const statusText = response.statusText || `HTTP ${response.status}`;
    throw new Error(statusText);
  }
  return body;
}

export async function postJson<T>(url: string, body: unknown, signal?: AbortSignal): Promise<T> {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal
  });
  return readJson<T>(response);
}
```

- [ ] **Step 4: Add API wrappers**

Create `frontend/src/api/chatApi.ts`:

```ts
import type { ChatResponse, ConfirmationPayload, ConfirmResponse } from "../types/api";
import { postJson } from "./http";

export const chatApi = {
  sendMessage(sessionId: string, message: string, signal?: AbortSignal): Promise<ChatResponse> {
    return postJson<ChatResponse>("/chat", { session_id: sessionId, message }, signal);
  },

  confirmDownload(
    sessionId: string,
    confirmationPayload: ConfirmationPayload,
    selectedResultId: string | null,
    signal?: AbortSignal,
  ): Promise<ConfirmResponse> {
    return postJson<ConfirmResponse>(
      "/confirm",
      {
        session_id: sessionId,
        action: "approve",
        selected_result_id: selectedResultId,
        confirmation_payload: confirmationPayload
      },
      signal,
    );
  },

  cancel(sessionId: string, signal?: AbortSignal): Promise<ConfirmResponse> {
    return postJson<ConfirmResponse>("/confirm", { session_id: sessionId, action: "cancel" }, signal);
  }
};
```

Create `frontend/src/api/downloadsApi.ts`:

```ts
import type { TorrentAction, TorrentActionResponse, TorrentDetail, TorrentListResponse } from "../types/api";
import { postJson, readJson } from "./http";

export const downloadsApi = {
  async listTorrents(signal?: AbortSignal): Promise<TorrentListResponse> {
    const response = await fetch("/qb/torrents", { signal });
    return readJson<TorrentListResponse>(response);
  },

  async getTorrent(hash: string, signal?: AbortSignal): Promise<TorrentDetail> {
    const response = await fetch(`/qb/torrents/${encodeURIComponent(hash)}`, { signal });
    return readJson<TorrentDetail>(response);
  },

  runTorrentAction(
    hash: string,
    action: TorrentAction,
    options: { deleteFiles?: boolean } = {},
    signal?: AbortSignal,
  ): Promise<TorrentActionResponse> {
    return postJson<TorrentActionResponse>(
      `/qb/torrents/${encodeURIComponent(hash)}/actions`,
      { action, delete_files: options.deleteFiles ?? false },
      signal,
    );
  }
};
```

Create `frontend/src/api/healthApi.ts`:

```ts
import type { HealthResponse } from "../types/api";
import { readJson } from "./http";

export const healthApi = {
  async getHealth(signal?: AbortSignal): Promise<HealthResponse> {
    const response = await fetch("/health", { signal });
    return readJson<HealthResponse>(response);
  }
};
```

- [ ] **Step 5: Run API tests**

Run:

```bash
cd frontend
npm test -- src/api/chatApi.test.ts src/api/downloadsApi.test.ts
```

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

```bash
git add frontend/src/api frontend/src/types
git commit -m "feat: add typed frontend api clients"
```

## Task 3: State Reducers

**Files:**

- Create: `frontend/src/state/chatState.ts`
- Create: `frontend/src/state/chatState.test.ts`
- Create: `frontend/src/state/downloadsState.ts`
- Create: `frontend/src/state/downloadsState.test.ts`
- Create: `frontend/src/state/uiState.ts`

- [ ] **Step 1: Write reducer tests**

Create `frontend/src/state/chatState.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { chatInitialState, chatReducer, createSessionId } from "./chatState";

describe("chatState", () => {
  it("creates stable session ids with the app prefix", () => {
    expect(createSessionId()).toMatch(/^nasclaw-/);
  });

  it("adds user messages and stores confirmation payloads", () => {
    const withUser = chatReducer(chatInitialState("session-1"), {
      type: "user_submitted",
      text: "Dune tonight"
    });
    const withResponse = chatReducer(withUser, {
      type: "chat_response_received",
      response: {
        session_id: "session-1",
        status: "awaiting_confirmation",
        confirmation_payload: {
          summary: "Review candidates",
          recommended_result_id: "r1",
          results: [{ id: "r1", title: "Dune", seeders: 10, resolution: "2160p", size: "60 GB" }],
          selected_result_id: null,
          qb_category: "movies",
          execution_result: null,
          receipt: null
        },
        receipt: null,
        error: null
      }
    });

    expect(withResponse.messages.map((message) => message.kind)).toEqual(["user", "assistant", "candidate"]);
    expect(withResponse.selectedResultId).toBe("r1");
    expect(withResponse.pendingConfirmation?.summary).toBe("Review candidates");
  });
});
```

Create `frontend/src/state/downloadsState.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { downloadsInitialState, downloadsReducer, visibleTorrents } from "./downloadsState";

const torrent = {
  hash: "hash-1",
  name: "Dune",
  category: "movies",
  tags: ["mteam"],
  state: "pausedDL",
  progress: 0,
  download_speed: 0,
  upload_speed: 0,
  eta: 0,
  save_path: "/downloads",
  size: 100,
  total_size: 100
};

describe("downloadsState", () => {
  it("stores torrent lists and selects the first item", () => {
    const state = downloadsReducer(downloadsInitialState, {
      type: "list_loaded",
      items: [torrent]
    });

    expect(state.torrentItems).toHaveLength(1);
    expect(state.selectedTorrentHash).toBe("hash-1");
  });

  it("filters paused torrents", () => {
    const state = { ...downloadsInitialState, torrentItems: [torrent], filter: "paused" as const };

    expect(visibleTorrents(state)).toHaveLength(1);
  });
});
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
cd frontend
npm test -- src/state/chatState.test.ts src/state/downloadsState.test.ts
```

Expected: FAIL because state modules do not exist.

- [ ] **Step 3: Implement chat state**

Create `frontend/src/state/chatState.ts`:

```ts
import type { ChatResponse, ConfirmationPayload, ConfirmResponse } from "../types/api";

export type ChatMessage =
  | { id: string; kind: "user"; text: string }
  | { id: string; kind: "assistant"; text: string }
  | { id: string; kind: "candidate"; payload: ConfirmationPayload }
  | { id: string; kind: "receipt"; receipt: Record<string, unknown> }
  | { id: string; kind: "error"; title: string; detail: string };

export type ChatState = {
  sessionId: string;
  messages: ChatMessage[];
  pendingConfirmation: ConfirmationPayload | null;
  selectedResultId: string | null;
  isSubmitting: boolean;
  lastError: string | null;
};

type ChatAction =
  | { type: "user_submitted"; text: string }
  | { type: "chat_response_received"; response: ChatResponse }
  | { type: "confirm_response_received"; response: ConfirmResponse }
  | { type: "selected_result_changed"; selectedResultId: string }
  | { type: "request_failed"; title: string; detail: string }
  | { type: "request_started" };

export function createSessionId(): string {
  return `nasclaw-${Date.now()}`;
}

export function chatInitialState(sessionId = createSessionId()): ChatState {
  return {
    sessionId,
    messages: [],
    pendingConfirmation: null,
    selectedResultId: null,
    isSubmitting: false,
    lastError: null
  };
}

function id(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function assistantText(response: ChatResponse | ConfirmResponse): string {
  if (response.error) return response.error;
  if (response.confirmation_payload) return response.confirmation_payload.summary || "找到候选结果，请确认。";
  if (response.receipt) return "下载请求已提交，qB 任务保持暂停。";
  return response.status || "请求完成。";
}

export function chatReducer(state: ChatState, action: ChatAction): ChatState {
  switch (action.type) {
    case "request_started":
      return { ...state, isSubmitting: true, lastError: null };
    case "user_submitted":
      return {
        ...state,
        isSubmitting: true,
        lastError: null,
        messages: [...state.messages, { id: id("user"), kind: "user", text: action.text }]
      };
    case "chat_response_received": {
      const messages: ChatMessage[] = [
        ...state.messages,
        { id: id("assistant"), kind: "assistant", text: assistantText(action.response) }
      ];
      if (action.response.confirmation_payload) {
        messages.push({ id: id("candidate"), kind: "candidate", payload: action.response.confirmation_payload });
      }
      return {
        ...state,
        messages,
        pendingConfirmation: action.response.confirmation_payload,
        selectedResultId:
          action.response.confirmation_payload?.recommended_result_id ??
          action.response.confirmation_payload?.results[0]?.id ??
          null,
        isSubmitting: false,
        lastError: action.response.error
      };
    }
    case "confirm_response_received": {
      const messages: ChatMessage[] = [
        ...state.messages,
        { id: id("assistant"), kind: "assistant", text: assistantText(action.response) }
      ];
      if (action.response.receipt) {
        messages.push({ id: id("receipt"), kind: "receipt", receipt: action.response.receipt });
      }
      return {
        ...state,
        messages,
        pendingConfirmation: action.response.confirmation_payload,
        isSubmitting: false,
        lastError: action.response.error
      };
    }
    case "selected_result_changed":
      return { ...state, selectedResultId: action.selectedResultId };
    case "request_failed":
      return {
        ...state,
        isSubmitting: false,
        lastError: action.detail,
        messages: [...state.messages, { id: id("error"), kind: "error", title: action.title, detail: action.detail }]
      };
    default:
      return state;
  }
}
```

- [ ] **Step 4: Implement downloads and UI state**

Create `frontend/src/state/downloadsState.ts`:

```ts
import type { TorrentDetail, TorrentSummary } from "../types/api";

export type DownloadsFilter = "all" | "downloading" | "paused" | "completed";

export type DownloadsState = {
  torrentItems: TorrentSummary[];
  selectedTorrentHash: string | null;
  torrentDetail: TorrentDetail | null;
  isRefreshing: boolean;
  actionPendingHash: string | null;
  filter: DownloadsFilter;
  lastError: string | null;
};

type DownloadsAction =
  | { type: "refresh_started" }
  | { type: "list_loaded"; items: TorrentSummary[] }
  | { type: "detail_loaded"; detail: TorrentDetail }
  | { type: "torrent_selected"; hash: string }
  | { type: "filter_changed"; filter: DownloadsFilter }
  | { type: "action_started"; hash: string }
  | { type: "action_finished" }
  | { type: "request_failed"; detail: string };

export const downloadsInitialState: DownloadsState = {
  torrentItems: [],
  selectedTorrentHash: null,
  torrentDetail: null,
  isRefreshing: false,
  actionPendingHash: null,
  filter: "all",
  lastError: null
};

export function downloadsReducer(state: DownloadsState, action: DownloadsAction): DownloadsState {
  switch (action.type) {
    case "refresh_started":
      return { ...state, isRefreshing: true, lastError: null };
    case "list_loaded":
      return {
        ...state,
        torrentItems: action.items,
        selectedTorrentHash: state.selectedTorrentHash ?? action.items[0]?.hash ?? null,
        isRefreshing: false,
        lastError: null
      };
    case "detail_loaded":
      return { ...state, torrentDetail: action.detail, lastError: null };
    case "torrent_selected":
      return { ...state, selectedTorrentHash: action.hash };
    case "filter_changed":
      return { ...state, filter: action.filter };
    case "action_started":
      return { ...state, actionPendingHash: action.hash, lastError: null };
    case "action_finished":
      return { ...state, actionPendingHash: null };
    case "request_failed":
      return { ...state, isRefreshing: false, actionPendingHash: null, lastError: action.detail };
    default:
      return state;
  }
}

export function visibleTorrents(state: DownloadsState): TorrentSummary[] {
  if (state.filter === "all") return state.torrentItems;
  if (state.filter === "paused") return state.torrentItems.filter((item) => item.state.toLowerCase().includes("pause"));
  if (state.filter === "completed") return state.torrentItems.filter((item) => item.progress >= 1);
  return state.torrentItems.filter((item) => item.download_speed > 0 || item.state.toLowerCase().includes("download"));
}
```

Create `frontend/src/state/uiState.ts`:

```ts
export type WorkspaceTab = "chat" | "downloads" | "settings";

export type UiState = {
  activeTab: WorkspaceTab;
  sidebarCollapsed: boolean;
};

export const uiInitialState: UiState = {
  activeTab: "chat",
  sidebarCollapsed: false
};
```

- [ ] **Step 5: Run reducer tests**

Run:

```bash
cd frontend
npm test -- src/state/chatState.test.ts src/state/downloadsState.test.ts
```

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

```bash
git add frontend/src/state
git commit -m "feat: add frontend state reducers"
```

## Task 4: App Shell, Sidebar, Tabs, And Theme

**Files:**

- Modify: `frontend/src/app/App.tsx`
- Create: `frontend/src/app/AppShell.tsx`
- Create: `frontend/src/app/AppShell.test.tsx`
- Modify: `frontend/src/app/theme.css`
- Create: `frontend/src/components/layout/ConversationSidebar.tsx`
- Create: `frontend/src/components/layout/WorkspaceTabs.tsx`
- Create: `frontend/src/components/chat/ChatPanel.tsx`
- Create: `frontend/src/components/downloads/DownloadsPanel.tsx`
- Create: `frontend/src/components/settings/SettingsPanel.tsx`

- [ ] **Step 1: Write AppShell test**

Create `frontend/src/app/AppShell.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { App } from "./App";

describe("AppShell", () => {
  it("renders the conversation sidebar and chat tab by default", () => {
    render(<App />);

    expect(screen.getByText("NasClawBot")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "新会话" })).toBeDisabled();
    expect(screen.getByRole("tab", { name: "Chat" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByText("输入媒体需求")).toBeInTheDocument();
  });

  it("switches to downloads and settings tabs", async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.click(screen.getByRole("tab", { name: "Downloads" }));
    expect(screen.getByText("下载任务")).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "Settings" }));
    expect(screen.getByText("运行状态")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
cd frontend
npm test -- src/app/AppShell.test.tsx
```

Expected: FAIL because `AppShell` and layout components do not exist.

- [ ] **Step 3: Implement layout components**

Create `frontend/src/components/layout/ConversationSidebar.tsx`:

```tsx
export function ConversationSidebar() {
  return (
    <aside className="conversation-sidebar" aria-label="会话列表">
      <div className="brand-row">
        <div className="brand-mark">N</div>
        <div>
          <div className="brand-title">NasClawBot</div>
          <div className="brand-subtitle">Media assistant</div>
        </div>
      </div>
      <div className="sidebar-section">
        <button className="new-chat-button" type="button" disabled>
          新会话
        </button>
      </div>
      <div className="sidebar-section">
        <div className="sidebar-label">当前</div>
        <div className="conversation-item" aria-current="true">
          <div className="conversation-item-title">
            临时搜索会话
            <span className="online-dot" aria-hidden="true" />
          </div>
          <div className="conversation-item-meta">会话历史后续支持</div>
        </div>
      </div>
      <div className="sidebar-section">
        <div className="sidebar-label">历史</div>
        <p className="sidebar-empty">还没有历史会话。这里先保留空间。</p>
      </div>
    </aside>
  );
}
```

Create `frontend/src/components/layout/WorkspaceTabs.tsx`:

```tsx
import type { WorkspaceTab } from "../../state/uiState";

const tabs: Array<{ id: WorkspaceTab; label: string }> = [
  { id: "chat", label: "Chat" },
  { id: "downloads", label: "Downloads" },
  { id: "settings", label: "Settings" }
];

export function WorkspaceTabs({
  activeTab,
  onTabChange
}: {
  activeTab: WorkspaceTab;
  onTabChange: (tab: WorkspaceTab) => void;
}) {
  return (
    <div className="workspace-tabs" role="tablist" aria-label="Workspace">
      {tabs.map((tab) => (
        <button
          key={tab.id}
          className="workspace-tab"
          data-active={activeTab === tab.id}
          role="tab"
          type="button"
          aria-selected={activeTab === tab.id}
          onClick={() => onTabChange(tab.id)}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}
```

Create `frontend/src/components/chat/ChatPanel.tsx`:

```tsx
export function ChatPanel() {
  return (
    <section className="chat-panel" aria-label="Chat">
      <div className="chat-thread">
        <div className="chat-empty">
          <h1>今天想看什么？</h1>
          <p>输入媒体需求</p>
        </div>
      </div>
      <form className="composer-shell">
        <textarea aria-label="媒体需求" placeholder="输入媒体需求，例如：我想看一部 4K 科幻电影..." />
        <button type="submit" aria-label="发送">
          ↑
        </button>
      </form>
    </section>
  );
}
```

Create `frontend/src/components/downloads/DownloadsPanel.tsx`:

```tsx
export function DownloadsPanel() {
  return (
    <section className="downloads-panel" aria-label="Downloads">
      <header className="panel-heading">
        <h1>下载任务</h1>
        <p>qBittorrent 任务列表会显示在这里。</p>
      </header>
    </section>
  );
}
```

Create `frontend/src/components/settings/SettingsPanel.tsx`:

```tsx
export function SettingsPanel() {
  return (
    <section className="settings-panel" aria-label="Settings">
      <header className="panel-heading">
        <h1>运行状态</h1>
        <p>连接状态和运行信息会显示在这里。</p>
      </header>
    </section>
  );
}
```

Create `frontend/src/app/AppShell.tsx`:

```tsx
import { useState } from "react";
import { ChatPanel } from "../components/chat/ChatPanel";
import { DownloadsPanel } from "../components/downloads/DownloadsPanel";
import { ConversationSidebar } from "../components/layout/ConversationSidebar";
import { WorkspaceTabs } from "../components/layout/WorkspaceTabs";
import { SettingsPanel } from "../components/settings/SettingsPanel";
import type { WorkspaceTab } from "../state/uiState";

export function AppShell() {
  const [activeTab, setActiveTab] = useState<WorkspaceTab>("chat");

  return (
    <div className="app-shell">
      <ConversationSidebar />
      <main className="workspace-shell">
        <header className="workspace-topbar">
          <WorkspaceTabs activeTab={activeTab} onTabChange={setActiveTab} />
          <div className="backend-status">
            <span className="online-dot" aria-hidden="true" />
            Backend online
          </div>
        </header>
        {activeTab === "chat" && <ChatPanel />}
        {activeTab === "downloads" && <DownloadsPanel />}
        {activeTab === "settings" && <SettingsPanel />}
      </main>
    </div>
  );
}
```

Modify `frontend/src/app/App.tsx`:

```tsx
import { AppShell } from "./AppShell";
import "./theme.css";

export function App() {
  return <AppShell />;
}
```

- [ ] **Step 4: Expand theme CSS**

Replace `frontend/src/app/theme.css` with the final Warm Paper White layout styles from the design spec. Keep these selectors present because tests and components rely on them:

```css
:root {
  color-scheme: light;
  --app-bg: #fffefd;
  --sidebar-bg: #f8f6f2;
  --surface: #ffffff;
  --surface-soft: #f5f3ee;
  --surface-subtle: #fbfaf7;
  --border: #e7e1d8;
  --border-strong: #d6cbbd;
  --text: #1f1c18;
  --text-soft: #453f37;
  --muted: #776f65;
  --primary: #24201b;
  --success: #2f7a54;
  --warning: #98680f;
  --danger: #c65f36;
  --radius: 8px;
}

* {
  box-sizing: border-box;
}

body {
  margin: 0;
  min-height: 100vh;
  background: var(--app-bg);
  color: var(--text);
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}

button,
input,
textarea {
  font: inherit;
}

.app-shell {
  min-height: 100vh;
  display: grid;
  grid-template-columns: 268px minmax(0, 1fr);
}

.conversation-sidebar {
  min-width: 0;
  border-right: 1px solid var(--border);
  background: var(--sidebar-bg);
  display: flex;
  flex-direction: column;
}

.brand-row {
  height: 64px;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 16px;
}

.brand-mark {
  width: 28px;
  height: 28px;
  border-radius: 7px;
  background: var(--primary);
  color: #fff;
  display: grid;
  place-items: center;
  font-size: 12px;
  font-weight: 700;
}

.brand-title {
  font-size: 14px;
  font-weight: 650;
}

.brand-subtitle,
.conversation-item-meta,
.sidebar-empty,
.backend-status,
.panel-heading p {
  color: var(--muted);
  font-size: 12px;
}

.sidebar-section {
  padding: 8px 12px;
}

.new-chat-button {
  width: 100%;
  height: 38px;
  border-radius: var(--radius);
  border: 1px solid var(--border-strong);
  background: var(--surface);
  color: var(--text);
}

.sidebar-label {
  margin: 8px 4px;
  color: var(--muted);
  font-size: 12px;
}

.conversation-item {
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface);
  padding: 10px;
}

.conversation-item-title,
.backend-status {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.online-dot {
  width: 7px;
  height: 7px;
  border-radius: 999px;
  background: var(--success);
  flex: 0 0 auto;
}

.workspace-shell {
  min-width: 0;
  display: grid;
  grid-template-rows: 62px minmax(0, 1fr);
}

.workspace-topbar {
  border-bottom: 1px solid var(--border);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 10px 24px;
}

.workspace-tabs {
  display: flex;
  gap: 4px;
  border: 1px solid #ddd4c8;
  background: var(--surface-soft);
  border-radius: 11px;
  padding: 4px;
}

.workspace-tab {
  height: 34px;
  border: 0;
  border-radius: var(--radius);
  background: transparent;
  color: var(--text-soft);
  padding: 0 14px;
}

.workspace-tab[data-active="true"] {
  background: var(--surface);
  color: var(--text);
  box-shadow: 0 1px 2px rgba(38, 32, 24, 0.07);
}

.chat-panel {
  min-height: 0;
  display: grid;
  grid-template-rows: minmax(0, 1fr) auto;
}

.chat-thread {
  min-height: 0;
  overflow: auto;
  padding: 36px 24px 24px;
}

.chat-empty {
  max-width: 820px;
  margin: 0 auto;
}

.chat-empty h1,
.panel-heading h1 {
  margin: 0 0 8px;
  font-size: 24px;
  letter-spacing: 0;
}

.composer-shell {
  max-width: 820px;
  width: calc(100% - 48px);
  margin: 0 auto 22px;
  border: 1px solid var(--border-strong);
  border-radius: 18px;
  background: var(--surface);
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: end;
  gap: 10px;
  padding: 11px 12px 11px 16px;
  box-shadow: 0 8px 22px rgba(38, 32, 24, 0.07);
}

.composer-shell textarea {
  min-height: 34px;
  max-height: 160px;
  resize: vertical;
  border: 0;
  outline: none;
  background: transparent;
  color: var(--text);
}

.composer-shell button {
  width: 34px;
  height: 34px;
  border: 0;
  border-radius: 999px;
  background: var(--primary);
  color: #fff;
}

.downloads-panel,
.settings-panel {
  padding: 36px 24px;
  background: var(--surface-subtle);
}

.panel-heading {
  max-width: 820px;
}

@media (max-width: 900px) {
  .app-shell {
    grid-template-columns: 1fr;
  }

  .conversation-sidebar {
    display: none;
  }

  .workspace-topbar {
    padding: 10px 16px;
  }
}
```

- [ ] **Step 5: Run AppShell test**

Run:

```bash
cd frontend
npm test -- src/app/AppShell.test.tsx
```

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

```bash
git add frontend/src/app frontend/src/components/layout frontend/src/components/chat/ChatPanel.tsx frontend/src/components/downloads/DownloadsPanel.tsx frontend/src/components/settings/SettingsPanel.tsx
git commit -m "feat: add warm paper app shell"
```

## Task 5: Chat Candidate, Receipt, And Error Cards

**Files:**

- Create: `frontend/src/components/chat/CandidateCard.tsx`
- Create: `frontend/src/components/chat/CandidateCard.test.tsx`
- Create: `frontend/src/components/chat/ReceiptCard.tsx`
- Create: `frontend/src/components/chat/ErrorCard.tsx`
- Modify: `frontend/src/components/chat/ChatPanel.tsx`

- [ ] **Step 1: Write candidate card test**

Create `frontend/src/components/chat/CandidateCard.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { CandidateCard } from "./CandidateCard";

const payload = {
  summary: "Review candidates",
  recommended_result_id: "r1",
  results: [
    { id: "r1", title: "Dune 2160p", seeders: 128, resolution: "2160p", size: "61 GB" },
    { id: "r2", title: "Dune 1080p", seeders: 94, resolution: "1080p", size: "16 GB" }
  ],
  selected_result_id: null,
  qb_category: "movies",
  execution_result: null,
  receipt: null
};

describe("CandidateCard", () => {
  it("selects candidates and submits approval", async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    const onApprove = vi.fn();

    render(
      <CandidateCard
        payload={payload}
        selectedResultId="r1"
        isSubmitting={false}
        onSelect={onSelect}
        onApprove={onApprove}
        onCancel={vi.fn()}
        onRewrite={vi.fn()}
      />,
    );

    await user.click(screen.getByLabelText("Dune 1080p"));
    expect(onSelect).toHaveBeenCalledWith("r2");

    await user.click(screen.getByRole("button", { name: "确认加入 qB" }));
    expect(onApprove).toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
cd frontend
npm test -- src/components/chat/CandidateCard.test.tsx
```

Expected: FAIL because `CandidateCard` does not exist.

- [ ] **Step 3: Implement chat cards**

Create `frontend/src/components/chat/CandidateCard.tsx`:

```tsx
import type { ConfirmationPayload } from "../../types/api";

export function CandidateCard({
  payload,
  selectedResultId,
  isSubmitting,
  onSelect,
  onApprove,
  onCancel,
  onRewrite
}: {
  payload: ConfirmationPayload;
  selectedResultId: string | null;
  isSubmitting: boolean;
  onSelect: (id: string) => void;
  onApprove: () => void;
  onCancel: () => void;
  onRewrite: () => void;
}) {
  return (
    <section className="candidate-card">
      <header className="card-head">
        <div>
          <h2>搜索候选</h2>
          <p>{payload.summary || "推荐项已选中，提交后会以暂停状态加入 qB。"}</p>
        </div>
        <span className="status-pill">Human approval</span>
      </header>
      <div className="candidate-list">
        {payload.results.map((candidate) => (
          <label className="candidate-row" key={candidate.id}>
            <input
              type="radio"
              name="candidate"
              aria-label={candidate.title}
              checked={selectedResultId === candidate.id}
              onChange={() => onSelect(candidate.id)}
            />
            <span>
              <strong>{candidate.title}</strong>
              <small>
                {candidate.resolution ?? "unknown"} · {candidate.size ?? "unknown size"} · seeders {candidate.seeders}
              </small>
            </span>
            {payload.recommended_result_id === candidate.id && <span className="status-pill">推荐</span>}
          </label>
        ))}
      </div>
      <footer className="card-actions">
        <button type="button" onClick={onCancel} disabled={isSubmitting}>
          取消
        </button>
        <button type="button" onClick={onRewrite} disabled={isSubmitting}>
          重新描述
        </button>
        <button className="primary-action" type="button" onClick={onApprove} disabled={isSubmitting || !selectedResultId}>
          {isSubmitting ? "提交中" : "确认加入 qB"}
        </button>
      </footer>
    </section>
  );
}
```

Create `frontend/src/components/chat/ReceiptCard.tsx`:

```tsx
export function ReceiptCard({ receipt }: { receipt: Record<string, unknown> }) {
  return (
    <section className="receipt-card">
      <header className="card-head">
        <div>
          <h2>下载回执</h2>
          <p>任务已提交，当前保持暂停。</p>
        </div>
        <span className="status-pill">Paused</span>
      </header>
      <pre>{JSON.stringify(receipt, null, 2)}</pre>
    </section>
  );
}
```

Create `frontend/src/components/chat/ErrorCard.tsx`:

```tsx
export function ErrorCard({ title, detail }: { title: string; detail: string }) {
  return (
    <section className="error-card" role="alert">
      <h2>{title}</h2>
      <p>{detail}</p>
    </section>
  );
}
```

- [ ] **Step 4: Add card styles**

Append to `frontend/src/app/theme.css`:

```css
.candidate-card,
.receipt-card,
.error-card {
  width: min(660px, 100%);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface);
  overflow: hidden;
}

.card-head {
  padding: 12px 14px;
  border-bottom: 1px solid var(--border);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.card-head h2,
.error-card h2 {
  margin: 0;
  font-size: 14px;
}

.card-head p,
.error-card p {
  margin: 4px 0 0;
  color: var(--muted);
  font-size: 12px;
}

.status-pill {
  border: 1px solid #d7eadf;
  background: #eef8f2;
  color: var(--success);
  border-radius: 999px;
  padding: 4px 8px;
  font-size: 12px;
  white-space: nowrap;
}

.candidate-list {
  display: grid;
}

.candidate-row {
  display: grid;
  grid-template-columns: 22px minmax(0, 1fr) auto;
  align-items: center;
  gap: 10px;
  padding: 12px 14px;
  border-bottom: 1px solid var(--border);
}

.candidate-row:last-child {
  border-bottom: 0;
}

.candidate-row strong {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 14px;
}

.candidate-row small {
  display: block;
  margin-top: 4px;
  color: var(--muted);
}

.card-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding: 12px 14px;
  border-top: 1px solid var(--border);
}

.card-actions button {
  height: 34px;
  border-radius: 7px;
  border: 1px solid var(--border-strong);
  background: var(--surface);
  color: var(--text);
  padding: 0 12px;
}

.card-actions .primary-action {
  border-color: var(--primary);
  background: var(--primary);
  color: #fff;
}

.receipt-card pre {
  margin: 0;
  padding: 12px 14px;
  white-space: pre-wrap;
  color: var(--text-soft);
}

.error-card {
  border-color: #efc8b8;
  padding: 12px 14px;
}
```

- [ ] **Step 5: Run card test**

Run:

```bash
cd frontend
npm test -- src/components/chat/CandidateCard.test.tsx
```

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

```bash
git add frontend/src/components/chat frontend/src/app/theme.css
git commit -m "feat: add chat business cards"
```

## Task 6: Chat Panel API Integration

**Files:**

- Modify: `frontend/src/components/chat/ChatPanel.tsx`
- Modify: `frontend/src/app/App.tsx`

- [ ] **Step 1: Add an integration behavior test**

Create `frontend/src/components/chat/ChatPanel.test.tsx`:

```tsx
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ChatPanel } from "./ChatPanel";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("ChatPanel", () => {
  it("submits chat text and renders candidates", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          session_id: "session-1",
          status: "awaiting_confirmation",
          confirmation_payload: {
            summary: "找到 1 个候选",
            recommended_result_id: "r1",
            results: [{ id: "r1", title: "Dune 2160p", seeders: 128, resolution: "2160p", size: "61 GB" }],
            selected_result_id: null,
            qb_category: "movies",
            execution_result: null,
            receipt: null
          },
          receipt: null,
          error: null
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
    const user = userEvent.setup();

    render(<ChatPanel onDownloadSubmitted={() => undefined} />);

    await user.type(screen.getByLabelText("媒体需求"), "Dune tonight");
    await user.click(screen.getByRole("button", { name: "发送" }));

    await waitFor(() => expect(screen.getByText("Dune 2160p")).toBeInTheDocument());
  });
});
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
cd frontend
npm test -- src/components/chat/ChatPanel.test.tsx
```

Expected: FAIL because `ChatPanel` does not integrate with API and reducer yet.

- [ ] **Step 3: Implement ChatPanel integration**

Replace `frontend/src/components/chat/ChatPanel.tsx`:

```tsx
import {
  AssistantRuntimeProvider,
  ComposerPrimitive,
  ThreadPrimitive,
  useLocalRuntime,
  type ChatModelAdapter
} from "@assistant-ui/react";
import { FormEvent, useReducer, useRef, useState } from "react";
import { chatApi } from "../../api/chatApi";
import { chatInitialState, chatReducer } from "../../state/chatState";
import { CandidateCard } from "./CandidateCard";
import { ErrorCard } from "./ErrorCard";
import { ReceiptCard } from "./ReceiptCard";

const localModelAdapter: ChatModelAdapter = {
  async run() {
    return { content: [{ type: "text", text: "" }] };
  }
};

export function ChatPanel({ onDownloadSubmitted = () => undefined }: { onDownloadSubmitted?: () => void }) {
  const runtime = useLocalRuntime(localModelAdapter);
  const [state, dispatch] = useReducer(chatReducer, undefined, () => chatInitialState());
  const [input, setInput] = useState("");
  const inputRef = useRef<HTMLTextAreaElement | null>(null);

  async function submitMessage(event: FormEvent) {
    event.preventDefault();
    const text = input.trim();
    if (!text || state.isSubmitting) return;
    setInput("");
    dispatch({ type: "user_submitted", text });
    try {
      const response = await chatApi.sendMessage(state.sessionId, text);
      dispatch({ type: "chat_response_received", response });
    } catch (error) {
      dispatch({ type: "request_failed", title: "搜索失败", detail: error instanceof Error ? error.message : String(error) });
    }
  }

  async function approveDownload() {
    if (!state.pendingConfirmation) return;
    dispatch({ type: "request_started" });
    try {
      const response = await chatApi.confirmDownload(state.sessionId, state.pendingConfirmation, state.selectedResultId);
      dispatch({ type: "confirm_response_received", response });
      if (response.receipt) onDownloadSubmitted();
    } catch (error) {
      dispatch({ type: "request_failed", title: "确认失败", detail: error instanceof Error ? error.message : String(error) });
    }
  }

  async function cancelRequest() {
    dispatch({ type: "request_started" });
    try {
      const response = await chatApi.cancel(state.sessionId);
      dispatch({ type: "confirm_response_received", response });
    } catch (error) {
      dispatch({ type: "request_failed", title: "取消失败", detail: error instanceof Error ? error.message : String(error) });
    }
  }

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <ThreadPrimitive.Root className="chat-panel" aria-label="Chat">
        <ThreadPrimitive.Viewport className="chat-thread">
          <div className="thread-inner">
            {state.messages.length === 0 && (
              <div className="chat-empty">
                <h1>今天想看什么？</h1>
                <p>输入媒体需求</p>
              </div>
            )}
            {state.messages.map((message) => {
              if (message.kind === "user") return <div className="message user" key={message.id}><div className="bubble">{message.text}</div></div>;
              if (message.kind === "assistant") return <div className="message assistant" key={message.id}><div className="assistant-text">{message.text}</div></div>;
              if (message.kind === "candidate") {
                return (
                  <div className="message assistant" key={message.id}>
                    <CandidateCard
                      payload={message.payload}
                      selectedResultId={state.selectedResultId}
                      isSubmitting={state.isSubmitting}
                      onSelect={(selectedResultId) => dispatch({ type: "selected_result_changed", selectedResultId })}
                      onApprove={approveDownload}
                      onCancel={cancelRequest}
                      onRewrite={() => inputRef.current?.focus()}
                    />
                  </div>
                );
              }
              if (message.kind === "receipt") return <div className="message assistant" key={message.id}><ReceiptCard receipt={message.receipt} /></div>;
              return <div className="message assistant" key={message.id}><ErrorCard title={message.title} detail={message.detail} /></div>;
            })}
          </div>
        </ThreadPrimitive.Viewport>
        <ComposerPrimitive.Root className="composer-shell" onSubmit={submitMessage}>
          <textarea
            ref={inputRef}
            aria-label="媒体需求"
            placeholder="输入媒体需求，例如：我想看一部 4K 科幻电影..."
            value={input}
            onChange={(event) => setInput(event.target.value)}
          />
          <button type="submit" aria-label="发送" disabled={state.isSubmitting}>
            ↑
          </button>
        </ComposerPrimitive.Root>
      </ThreadPrimitive.Root>
    </AssistantRuntimeProvider>
  );
}
```

Add to `frontend/src/app/theme.css`:

```css
.thread-inner {
  max-width: 820px;
  margin: 0 auto;
  display: grid;
  gap: 22px;
}

.message {
  display: flex;
}

.message.user {
  justify-content: flex-end;
}

.message.assistant {
  justify-content: flex-start;
}

.bubble {
  max-width: 76%;
  border-radius: 18px;
  padding: 12px 14px;
  background: var(--surface-soft);
  font-size: 15px;
  line-height: 1.55;
}

.assistant-text {
  max-width: 820px;
  font-size: 15px;
  line-height: 1.6;
}
```

- [ ] **Step 4: Run chat integration test**

Run:

```bash
cd frontend
npm test -- src/components/chat/ChatPanel.test.tsx src/components/chat/CandidateCard.test.tsx
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add frontend/src/components/chat frontend/src/app/theme.css
git commit -m "feat: connect chat panel to api"
```

## Task 7: Downloads Panel

**Files:**

- Modify: `frontend/src/components/downloads/DownloadsPanel.tsx`
- Create: `frontend/src/components/downloads/DownloadsPanel.test.tsx`

- [ ] **Step 1: Write downloads panel test**

Create `frontend/src/components/downloads/DownloadsPanel.test.tsx`:

```tsx
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DownloadsPanel } from "./DownloadsPanel";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("DownloadsPanel", () => {
  it("loads torrents and runs a pause action", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(new Response(JSON.stringify({
        items: [{
          hash: "hash-1",
          name: "Dune 2160p",
          category: "movies",
          tags: ["mteam"],
          state: "downloading",
          progress: 0.42,
          download_speed: 1000,
          upload_speed: 0,
          eta: 120,
          save_path: "/downloads",
          size: 100,
          total_size: 100
        }]
      }), { status: 200, headers: { "Content-Type": "application/json" } }))
      .mockResolvedValueOnce(new Response(JSON.stringify({
        hash: "hash-1",
        name: "Dune 2160p",
        category: "movies",
        tags: ["mteam"],
        state: "downloading",
        progress: 0.42,
        download_speed: 1000,
        upload_speed: 0,
        eta: 120,
        save_path: "/downloads",
        size: 100,
        total_size: 100,
        comment: "",
        total_uploaded: 0,
        share_ratio: 0,
        creation_date: 0
      }), { status: 200, headers: { "Content-Type": "application/json" } }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ ok: true, status: "paused", qb_hash: "hash-1" }), {
        status: 200,
        headers: { "Content-Type": "application/json" }
      }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ items: [] }), {
        status: 200,
        headers: { "Content-Type": "application/json" }
      }));

    const user = userEvent.setup();
    render(<DownloadsPanel refreshSignal={0} />);

    await waitFor(() => expect(screen.getByText("Dune 2160p")).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "暂停" }));

    expect(fetchMock).toHaveBeenCalledWith("/qb/torrents/hash-1/actions", expect.objectContaining({ method: "POST" }));
  });
});
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
cd frontend
npm test -- src/components/downloads/DownloadsPanel.test.tsx
```

Expected: FAIL because the panel does not load qB data.

- [ ] **Step 3: Implement DownloadsPanel**

Replace `frontend/src/components/downloads/DownloadsPanel.tsx`:

```tsx
import { useEffect, useReducer } from "react";
import { downloadsApi } from "../../api/downloadsApi";
import { downloadsInitialState, downloadsReducer, visibleTorrents } from "../../state/downloadsState";
import type { TorrentAction } from "../../types/api";

export function DownloadsPanel({ refreshSignal = 0 }: { refreshSignal?: number }) {
  const [state, dispatch] = useReducer(downloadsReducer, downloadsInitialState);
  const torrents = visibleTorrents(state);

  async function loadList() {
    dispatch({ type: "refresh_started" });
    try {
      const response = await downloadsApi.listTorrents();
      dispatch({ type: "list_loaded", items: response.items });
      const selectedHash = response.items[0]?.hash;
      if (selectedHash) {
        const detail = await downloadsApi.getTorrent(selectedHash);
        dispatch({ type: "detail_loaded", detail });
      }
    } catch (error) {
      dispatch({ type: "request_failed", detail: error instanceof Error ? error.message : String(error) });
    }
  }

  async function runAction(action: TorrentAction) {
    const hash = state.selectedTorrentHash;
    if (!hash) return;
    if (action === "delete" && !window.confirm("确认删除这个 qB 任务？")) return;
    dispatch({ type: "action_started", hash });
    try {
      await downloadsApi.runTorrentAction(hash, action);
      dispatch({ type: "action_finished" });
      await loadList();
    } catch (error) {
      dispatch({ type: "request_failed", detail: error instanceof Error ? error.message : String(error) });
    }
  }

  useEffect(() => {
    void loadList();
  }, [refreshSignal]);

  return (
    <section className="downloads-panel" aria-label="Downloads">
      <header className="panel-heading downloads-toolbar">
        <div>
          <h1>下载任务</h1>
          <p>qBittorrent 任务列表和控制操作。</p>
        </div>
        <button type="button" onClick={loadList} disabled={state.isRefreshing}>
          刷新
        </button>
      </header>
      {state.lastError && <p className="inline-error">{state.lastError}</p>}
      {torrents.length === 0 && !state.isRefreshing ? (
        <p className="empty-state">当前没有 qB 任务。</p>
      ) : (
        <div className="downloads-grid">
          <div className="torrent-list">
            {torrents.map((torrent) => (
              <button
                className="torrent-row"
                data-active={state.selectedTorrentHash === torrent.hash}
                key={torrent.hash}
                type="button"
                onClick={() => dispatch({ type: "torrent_selected", hash: torrent.hash })}
              >
                <strong>{torrent.name}</strong>
                <span>{torrent.state} · {Math.round(torrent.progress * 100)}%</span>
              </button>
            ))}
          </div>
          <aside className="torrent-detail">
            <h2>{state.torrentDetail?.name ?? "选择任务"}</h2>
            {state.torrentDetail && (
              <>
                <p>{state.torrentDetail.save_path}</p>
                <p>Ratio {state.torrentDetail.share_ratio}</p>
                <div className="torrent-actions">
                  <button type="button" onClick={() => runAction("pause")}>暂停</button>
                  <button type="button" onClick={() => runAction("resume")}>继续</button>
                  <button type="button" onClick={() => runAction("recheck")}>校验</button>
                  <button type="button" onClick={() => runAction("reannounce")}>重新汇报</button>
                  <button type="button" onClick={() => runAction("delete")}>删除</button>
                </div>
              </>
            )}
          </aside>
        </div>
      )}
    </section>
  );
}
```

- [ ] **Step 4: Add Downloads styles**

Append to `frontend/src/app/theme.css`:

```css
.downloads-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
}

.downloads-toolbar button,
.torrent-actions button {
  height: 34px;
  border-radius: 7px;
  border: 1px solid var(--border-strong);
  background: var(--surface);
  color: var(--text);
  padding: 0 12px;
}

.downloads-grid {
  max-width: 1100px;
  margin-top: 18px;
  display: grid;
  grid-template-columns: minmax(0, 1fr) 320px;
  gap: 16px;
}

.torrent-list {
  display: grid;
  gap: 8px;
}

.torrent-row {
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface);
  text-align: left;
  padding: 12px;
}

.torrent-row[data-active="true"] {
  border-color: var(--border-strong);
  box-shadow: 0 1px 2px rgba(38, 32, 24, 0.07);
}

.torrent-row strong,
.torrent-row span {
  display: block;
}

.torrent-row span,
.torrent-detail p,
.empty-state,
.inline-error {
  color: var(--muted);
}

.torrent-detail {
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface);
  padding: 14px;
}

.torrent-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 12px;
}

.inline-error {
  color: var(--danger);
}

@media (max-width: 900px) {
  .downloads-grid {
    grid-template-columns: 1fr;
  }
}
```

- [ ] **Step 5: Run downloads test**

Run:

```bash
cd frontend
npm test -- src/components/downloads/DownloadsPanel.test.tsx
```

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

```bash
git add frontend/src/components/downloads frontend/src/app/theme.css
git commit -m "feat: add downloads workbench panel"
```

## Task 8: Settings Panel And App Integration

**Files:**

- Modify: `frontend/src/components/settings/SettingsPanel.tsx`
- Create: `frontend/src/components/settings/SettingsPanel.test.tsx`
- Modify: `frontend/src/app/AppShell.tsx`

- [ ] **Step 1: Write SettingsPanel test**

Create `frontend/src/components/settings/SettingsPanel.test.tsx`:

```tsx
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SettingsPanel } from "./SettingsPanel";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("SettingsPanel", () => {
  it("loads backend health and displays session id", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ status: "ok" }), {
        status: 200,
        headers: { "Content-Type": "application/json" }
      }),
    );

    render(<SettingsPanel sessionId="session-1" />);

    expect(screen.getByText("session-1")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("ok")).toBeInTheDocument());
  });
});
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
cd frontend
npm test -- src/components/settings/SettingsPanel.test.tsx
```

Expected: FAIL because `SettingsPanel` does not accept `sessionId` or call `/health`.

- [ ] **Step 3: Implement SettingsPanel**

Replace `frontend/src/components/settings/SettingsPanel.tsx`:

```tsx
import { useEffect, useState } from "react";
import { healthApi } from "../../api/healthApi";

export function SettingsPanel({ sessionId = "local-session" }: { sessionId?: string }) {
  const [health, setHealth] = useState("checking");

  useEffect(() => {
    let mounted = true;
    healthApi
      .getHealth()
      .then((response) => {
        if (mounted) setHealth(response.status);
      })
      .catch((error) => {
        if (mounted) setHealth(error instanceof Error ? error.message : String(error));
      });
    return () => {
      mounted = false;
    };
  }, []);

  return (
    <section className="settings-panel" aria-label="Settings">
      <header className="panel-heading">
        <h1>运行状态</h1>
        <p>只读状态页。密钥仍由后端环境变量管理。</p>
      </header>
      <div className="settings-grid">
        <article>
          <h2>Backend</h2>
          <p>{health}</p>
        </article>
        <article>
          <h2>Session</h2>
          <p>{sessionId}</p>
        </article>
        <article>
          <h2>Secrets</h2>
          <p>Environment managed</p>
        </article>
      </div>
    </section>
  );
}
```

Append to `frontend/src/app/theme.css`:

```css
.settings-grid {
  max-width: 820px;
  margin-top: 18px;
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.settings-grid article {
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface);
  padding: 14px;
}

.settings-grid h2 {
  margin: 0 0 8px;
  font-size: 14px;
}

.settings-grid p {
  margin: 0;
  color: var(--muted);
}

@media (max-width: 900px) {
  .settings-grid {
    grid-template-columns: 1fr;
  }
}
```

- [ ] **Step 4: Wire refresh signal into AppShell**

Modify `frontend/src/app/AppShell.tsx` so approved downloads can refresh the Downloads panel:

```tsx
import { useState } from "react";
import { ChatPanel } from "../components/chat/ChatPanel";
import { DownloadsPanel } from "../components/downloads/DownloadsPanel";
import { ConversationSidebar } from "../components/layout/ConversationSidebar";
import { WorkspaceTabs } from "../components/layout/WorkspaceTabs";
import { SettingsPanel } from "../components/settings/SettingsPanel";
import type { WorkspaceTab } from "../state/uiState";

export function AppShell() {
  const [activeTab, setActiveTab] = useState<WorkspaceTab>("chat");
  const [downloadRefreshSignal, setDownloadRefreshSignal] = useState(0);

  return (
    <div className="app-shell">
      <ConversationSidebar />
      <main className="workspace-shell">
        <header className="workspace-topbar">
          <WorkspaceTabs activeTab={activeTab} onTabChange={setActiveTab} />
          <div className="backend-status">
            <span className="online-dot" aria-hidden="true" />
            Backend online
          </div>
        </header>
        {activeTab === "chat" && <ChatPanel onDownloadSubmitted={() => setDownloadRefreshSignal((value) => value + 1)} />}
        {activeTab === "downloads" && <DownloadsPanel refreshSignal={downloadRefreshSignal} />}
        {activeTab === "settings" && <SettingsPanel />}
      </main>
    </div>
  );
}
```

- [ ] **Step 5: Run Settings and AppShell tests**

Run:

```bash
cd frontend
npm test -- src/components/settings/SettingsPanel.test.tsx src/app/AppShell.test.tsx
```

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

```bash
git add frontend/src/components/settings frontend/src/app/AppShell.tsx frontend/src/app/theme.css
git commit -m "feat: add settings status panel"
```

## Task 9: FastAPI Static Serving For Vite Build

**Files:**

- Modify: `app/main.py`
- Modify: `app/api/chat_routes.py`
- Create: `tests/test_frontend_static.py`

- [ ] **Step 1: Write backend static serving tests**

Create `tests/test_frontend_static.py`:

```python
from fastapi.testclient import TestClient

from app.main import create_app


class FakeRunner:
    def run_chat(self, session_id: str, message: str) -> dict:
        return {"status": "ok"}

    def run_confirm(self, session_id: str, **kwargs) -> dict:
        return {"status": "ok"}


def test_index_route_serves_html():
    client = TestClient(create_app(workflow_runner=FakeRunner()))

    response = client.get("/")

    assert response.status_code == 200
    assert "<html" in response.text.lower() or "<!doctype html" in response.text.lower()


def test_static_mount_does_not_break_health():
    client = TestClient(create_app(workflow_runner=FakeRunner()))

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

- [ ] **Step 2: Run tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_frontend_static.py -q
```

Expected: PASS against current fallback. This locks baseline before changing serving logic.

- [ ] **Step 3: Update index path selection**

Modify `app/api/chat_routes.py` near `_FRONTEND_INDEX`:

```python
_FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"
_FRONTEND_DIST_INDEX = _FRONTEND_DIR / "dist" / "index.html"
_FRONTEND_INDEX = _FRONTEND_DIR / "index.html"
```

Modify the `index()` route:

```python
    @router.get("/", response_class=HTMLResponse)
    def index() -> str:
        """Serve the built React page when present, fallback to the source index."""
        if _FRONTEND_DIST_INDEX.exists():
            return _FRONTEND_DIST_INDEX.read_text(encoding="utf-8")
        if _FRONTEND_INDEX.exists():
            return _FRONTEND_INDEX.read_text(encoding="utf-8")
        return "<h1>fnOS Media Agent</h1>"
```

- [ ] **Step 4: Update static mounts**

Modify `app/main.py` static mounting block:

```python
    frontend_dir = Path(__file__).resolve().parents[1] / "frontend"
    frontend_dist = frontend_dir / "dist"
    frontend_assets = frontend_dist / "assets"
    if frontend_assets.exists():
        app.mount("/assets", StaticFiles(directory=frontend_assets), name="assets")
    if frontend_dir.exists():
        app.mount("/static", StaticFiles(directory=frontend_dir), name="static")
```

- [ ] **Step 5: Run backend static tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_frontend_static.py tests/test_chat_api.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

```bash
git add app/main.py app/api/chat_routes.py tests/test_frontend_static.py
git commit -m "feat: serve built react frontend"
```

## Task 10: Final Build And Verification

**Files:**

- Modify only files required by test failures discovered in this task.

- [ ] **Step 1: Run full frontend test suite**

Run:

```bash
cd frontend
npm test
```

Expected: PASS.

- [ ] **Step 2: Run frontend typecheck and build**

Run:

```bash
cd frontend
npm run typecheck
npm run build
```

Expected: PASS and `frontend/dist/index.html` exists.

- [ ] **Step 3: Run backend focused tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_chat_api.py tests/test_frontend_static.py tests/test_qb_adapter.py -q
```

Expected: PASS.

- [ ] **Step 4: Run local app for manual verification**

Run backend:

```bash
.venv/bin/python -m uvicorn app.main:app --reload
```

Open:

```text
http://127.0.0.1:8000/
```

Expected:

- Warm Paper White theme appears.
- Left conversation sidebar is visible on desktop.
- Top tabs have clear breathing room from borders.
- Chat tab accepts a message.
- Candidate cards render from mocked or real `/chat` response.
- Downloads tab loads or shows qB unavailable/empty state.
- Settings tab shows `/health` status.

- [ ] **Step 5: Check git status**

Run:

```bash
git status --short
```

Expected: only intentional files are changed or the worktree is clean.

- [ ] **Step 6: Commit final verification fixes**

If Task 10 required fixes, run:

```bash
git add frontend app tests
git commit -m "fix: polish frontend workbench verification"
```

If Task 10 required no fixes, do not create an empty commit.
