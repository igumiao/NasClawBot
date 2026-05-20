import { afterEach, describe, expect, it, vi } from "vitest";
import { chatInitialState, chatReducer, createSessionId } from "./chatState";

const confirmationPayload = {
  summary: "Review candidates",
  recommended_result_id: "r1",
  results: [{ id: "r1", title: "Dune", seeders: 10, resolution: "2160p", size: "60 GB" }],
  selected_result_id: null,
  qb_category: "movies",
  execution_result: null,
  receipt: null
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
        confirmation_payload: confirmationPayload,
        receipt: null,
        error: null
      }
    });

    expect(withResponse.messages.map((message) => message.kind)).toEqual(["user", "assistant", "candidate"]);
    expect(withResponse.selectedResultId).toBe("r1");
    expect(withResponse.pendingConfirmation?.summary).toBe("Review candidates");
  });

  it("clears selected result when confirm response has no confirmation payload", () => {
    const state = chatReducer(
      {
        ...chatInitialState("session-1"),
        pendingConfirmation: confirmationPayload,
        selectedResultId: "r1"
      },
      {
        type: "confirm_response_received",
        response: {
          session_id: "session-1",
          status: "accepted",
          confirmation_payload: null,
          receipt: { ok: true },
          error: null,
          messages: []
        }
      }
    );

    expect(state.pendingConfirmation).toBeNull();
    expect(state.selectedResultId).toBeNull();
  });

  it("recomputes selected result from confirm response payload", () => {
    const state = chatReducer(
      {
        ...chatInitialState("session-1"),
        selectedResultId: "stale"
      },
      {
        type: "confirm_response_received",
        response: {
          session_id: "session-1",
          status: "awaiting_confirmation",
          confirmation_payload: {
            ...confirmationPayload,
            recommended_result_id: null,
            results: [
              { id: "fallback", title: "Dune 1984", seeders: 4, resolution: "1080p", size: "12 GB" },
              { id: "second", title: "Dune 2021", seeders: 10, resolution: "2160p", size: "60 GB" }
            ]
          },
          receipt: null,
          error: null,
          messages: []
        }
      }
    );

    expect(state.selectedResultId).toBe("fallback");
  });
});
