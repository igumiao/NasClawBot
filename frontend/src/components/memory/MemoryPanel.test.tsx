import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { MemoryPanel } from "./MemoryPanel";

vi.mock("../../api/chatApi", () => ({
  fetchInbox: vi.fn().mockResolvedValue({ entries: [], entry_count: 0 }),
  fetchCuration: vi.fn(),
  applyCuration: vi.fn(),
}));

describe("MemoryPanel", () => {
  it("shows empty state when inbox is empty", async () => {
    render(<MemoryPanel visible={true} />);
    expect(await screen.findByText(/暂无待整理记忆/)).toBeTruthy();
  });
});
