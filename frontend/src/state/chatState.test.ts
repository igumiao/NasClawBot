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
