# Frontend Chat Workbench Redesign

## Summary

Redesign the current plain HTML/CSS/JS frontend into a React-based ChatGPT-like light interface for NasClawBot. The new frontend should make chat the primary interaction, while giving qBittorrent task management a clear workspace surface.

The selected direction is a hybrid assistant-ui approach:

- Use assistant-ui primitives for the chat shell and interaction model.
- Keep NasClawBot-specific business cards and download state in app-managed React state.
- Preserve the existing FastAPI backend APIs for the first implementation.

## Product Shape

The first version is a lightweight workbench, not a full multi-user product.

Primary layout:

- Left conversation sidebar.
- Main workspace with top segmented tabs: `Chat`, `Downloads`, `Settings`.
- Chat panel as the default view.
- Downloads panel for qB task management.
- Settings panel for read-only runtime and connection status.

The left sidebar is reserved for future conversation history. In the first version it shows:

- NasClawBot brand.
- Disabled new conversation button that makes the future affordance visible without creating real history.
- Current temporary conversation.
- Empty history state explaining that history support comes later.

The sidebar represents the conversation dimension. The top tabs represent the active workspace within the current conversation.

## Theme

Use the selected `Warm Paper White` theme. The design should feel close to ChatGPT, but slightly warmer.

Core tokens:

```css
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
```

Visual rules:

- Keep the main workspace near-white.
- Use warm gray only for the sidebar, segmented controls, subtle user bubbles, and secondary surfaces.
- Use `--primary` for primary actions, not random blue.
- Use semantic colors only for status: success, warning, and danger.
- Keep card border radius around `8px`.
- Avoid decorative gradients, orbs, and ornamental color.

Top tabs should be a segmented control with enough breathing room:

- Topbar height around `62px`.
- Topbar padding around `10px 24px`.
- Tabs padding around `4px`.
- Tabs should keep at least `10px` vertical space from the topbar divider and outer edge.
- Tabs border should not visually collide with the topbar bottom border.

## Architecture

Introduce a modern frontend app under `frontend/` using React. Vite is the preferred build tool for this repo because the backend is FastAPI and there is no existing Next.js app.

Suggested structure:

```text
frontend/
  package.json
  index.html
  src/
    main.tsx
    app/
      App.tsx
      AppShell.tsx
      theme.css
    api/
      chatApi.ts
      downloadsApi.ts
    components/
      chat/
        ChatPanel.tsx
        ChatThread.tsx
        Composer.tsx
        CandidateCard.tsx
        ReceiptCard.tsx
        ErrorCard.tsx
      downloads/
        DownloadsPanel.tsx
        TorrentList.tsx
        TorrentDetail.tsx
        TorrentActions.tsx
      layout/
        ConversationSidebar.tsx
        WorkspaceTabs.tsx
      settings/
        SettingsPanel.tsx
    state/
      chatStore.ts
      downloadsStore.ts
      uiStore.ts
    types/
      api.ts
```

The exact state library can be decided during implementation. React state plus reducer is enough for the first version; Zustand is acceptable if it reduces boilerplate without expanding scope.

## assistant-ui Usage

Use assistant-ui for the chat shell:

- `AssistantRuntimeProvider`
- `ThreadPrimitive.Root`
- `ThreadPrimitive.Viewport`
- `ThreadPrimitive.Messages`
- `MessagePrimitive.Root`
- `MessagePrimitive.Parts` or custom message renderers
- `ComposerPrimitive.Root`
- `ComposerPrimitive.Input`
- `ComposerPrimitive.Send`

Because the current backend does not speak the Vercel AI SDK transport format, do not force the backend into `useChatRuntime` in the first version. Prefer a custom local runtime or a thin adapter that lets the app coordinate existing `/chat` and `/confirm` calls.

NasClawBot business UI is app-driven:

- Search candidate card.
- Human approval controls.
- Download receipt card.
- qB task summary.
- Error card.

This keeps assistant-ui responsible for chat ergonomics while keeping workflow-specific logic explicit and testable.

## Panels

### Chat

The Chat panel is the default first screen.

It contains:

- Message viewport.
- User messages as right-aligned warm gray bubbles.
- Assistant text as left-aligned content.
- Candidate result cards inside assistant turns.
- Receipt cards after approval.
- Error cards for failed API calls.
- Sticky bottom composer.

Primary chat flow:

```text
User submits media request
→ POST /chat
→ Add assistant text/status
→ If confirmation_payload exists, render CandidateCard
→ User selects a candidate
→ POST /confirm with action=approve
→ Render receipt or error
→ Refresh download summary/list
```

The current backend rejects `reject_and_refine`; therefore the first UI should not expose a primary refine action. It may expose a neutral "重新描述" action that puts focus back into the composer rather than calling `/confirm` with `reject_and_refine`.

### Downloads

The Downloads panel uses existing qB APIs.

It contains:

- Toolbar with refresh, status filter, and search.
- Torrent list with name, category, state, progress, speed, ETA, size.
- Detail panel for the selected torrent.
- Actions for pause, resume, recheck, reannounce, and delete.

Delete should require a confirmation step. Destructive actions must be visually distinct but not over-styled.

Primary downloads flow:

```text
Open Downloads tab or submit approved download
→ GET /qb/torrents
→ Select torrent
→ GET /qb/torrents/{hash}
→ Run action
→ POST /qb/torrents/{hash}/actions
→ Refresh list and detail
```

### Settings

Settings is read-only in the first version.

It should show:

- `/health` status.
- qB API availability if detectable through existing list/detail behavior.
- Current frontend session id.
- Backend app title or version if available.
- A note that secrets are managed by environment variables.

Do not build secret editing in the first version.

## State

Chat state:

- `sessionId`
- `messages`
- `pendingConfirmation`
- `selectedResultId`
- `isSubmitting`
- `lastError`

Downloads state:

- `torrentItems`
- `selectedTorrentHash`
- `torrentDetail`
- `isRefreshing`
- `actionPendingHash`
- `filter`
- `lastError`

UI state:

- `activeTab`: `chat | downloads | settings`
- `sidebarCollapsed`
- `toast` or inline status

## API Wrappers

Create a small typed API layer:

- `chatApi.sendMessage(sessionId, message)`
- `chatApi.confirmDownload(sessionId, payload, selectedResultId)`
- `chatApi.cancel(sessionId)`
- `downloadsApi.listTorrents()`
- `downloadsApi.getTorrent(hash)`
- `downloadsApi.runTorrentAction(hash, action, options)`

The wrappers should isolate response shape differences and keep components from knowing raw endpoint details.

## Error And Empty States

Use inline UI, not disruptive modal dialogs, except for destructive confirmation.

Required states:

- Chat request failed: show an error card and allow retry.
- Confirmation failed: keep the candidate card visible and re-enable actions.
- No candidates: show an empty candidate card and ask the user to rephrase.
- qB unavailable: show Downloads empty/error state and Settings disconnected state.
- Torrent list empty: show a calm empty state.
- Delete action: require confirmation before sending the action.

## Responsive Behavior

Desktop:

- Show the left conversation sidebar.
- Show top workspace tabs.
- Chat may include a compact download summary side panel if useful, but full management belongs in Downloads.

Mobile or narrow viewport:

- Hide or collapse the left conversation sidebar.
- Keep top tabs.
- Keep composer sticky.
- Present Downloads as a full panel rather than a cramped side-by-side layout.

## Out Of Scope

The first version does not include:

- Persistent conversation history.
- Multi-user auth.
- assistant-ui Cloud.
- Secret editing.
- Streaming output.
- True refine-state merge.
- Full settings center.
- Frontend-driven real downloads outside the current paused approval path.

## Validation

Implementation should be verified with:

- API wrapper unit tests for `/chat`, `/confirm`, and qB routes.
- Component tests for candidate selection, approval loading state, errors, and download actions.
- Manual browser check against the FastAPI app:
  - Send media request.
  - Render candidate results.
  - Select and approve a candidate.
  - Render receipt.
  - Refresh Downloads.
  - Run a non-destructive qB action where safe.

The existing safety rule remains: qB submissions stay paused by default unless the user explicitly asks otherwise.
