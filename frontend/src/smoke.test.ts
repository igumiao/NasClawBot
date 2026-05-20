import { describe, expect, it } from "vitest";

describe("frontend test harness", () => {
  it("runs vitest in jsdom", () => {
    expect(document.createElement("div")).toBeInstanceOf(HTMLDivElement);
  });
});
