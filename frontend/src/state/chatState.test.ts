import { afterEach, describe, expect, it, vi } from "vitest";
import { chatInitialState, chatReducer, createSessionId } from "./chatState";

const searchResult = {
  id: "r1",
  title: "Dune",
  media_type: "movie",
  year: null,
  seeders: 10,
  resolution: "2160p",
  size: "60 GB",
  size_bytes: null,
  source: "mteam"
};

describe("chatState", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("creates stable session ids with the app prefix", () => {
    expect(createSessionId()).toMatch(/^nasclaw-/);
  });

  it("uses random UUIDs with stable app prefixes when available", () => {
    vi.stubGlobal("crypto", { randomUUID: () => "uuid-123" });

    const state = chatReducer(chatInitialState(), {
      type: "user_submitted",
      text: "Dune tonight"
    });

    expect(state.sessionId).toBe("nasclaw-uuid-123");
    expect(state.messages[0].id).toBe("user-uuid-123");
  });

  it("adds user messages and stores search result messages", () => {
    const withUser = chatReducer(chatInitialState("session-1"), {
      type: "user_submitted",
      text: "Dune tonight"
    });
    const withResponse = chatReducer(withUser, {
      type: "chat_response_received",
      response: {
        session_id: "session-1",
        status: "completed",
        message: "找到 1 个搜索结果。",
        results: [searchResult],
        tool_calls: [],
        error: null
      }
    });

    expect(withResponse.messages.map((message) => message.kind)).toEqual(["user", "assistant", "search_results"]);
  });

  it("adds receipt messages after explicit download responses", () => {
    const state = chatReducer(chatInitialState("session-1"), {
      type: "download_response_received",
      response: {
        status: "completed",
        receipt: { ok: true },
        error: null
      }
    });

    expect(state.messages.map((message) => message.kind)).toEqual(["assistant", "receipt"]);
  });
});
