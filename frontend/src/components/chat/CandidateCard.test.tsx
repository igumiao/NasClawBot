import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { ConfirmationPayload } from "../../types/api";
import { CandidateCard } from "./CandidateCard";
import { ReceiptCard } from "./ReceiptCard";

const payload: ConfirmationPayload = {
  summary: "已找到两个结果，请确认。",
  recommended_result_id: "r1",
  results: [
    { id: "r1", title: "Dune 4K", resolution: "2160p", size: "60 GB", seeders: 88 },
    { id: "r2", title: "Dune 1080p", resolution: "1080p", size: "22 GB", seeders: 42 }
  ],
  selected_result_id: null,
  qb_category: "movies",
  execution_result: null,
  receipt: null
};

describe("CandidateCard", () => {
  it("renders candidates, allows selection, and approves the selected result", async () => {
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
      />
    );

    expect(screen.getByRole("radio", { name: "Dune 4K" })).toBeChecked();
    expect(screen.getByRole("radio", { name: "Dune 1080p" })).not.toBeChecked();

    await user.click(screen.getByRole("radio", { name: "Dune 1080p" }));
    expect(onSelect).toHaveBeenCalledWith("r2");

    await user.click(screen.getByRole("button", { name: "确认加入 qB" }));
    expect(onApprove).toHaveBeenCalledTimes(1);
  });

  it("disables approval when no result is selected", () => {
    render(
      <CandidateCard
        payload={payload}
        selectedResultId={null}
        isSubmitting={false}
        onSelect={vi.fn()}
        onApprove={vi.fn()}
        onCancel={vi.fn()}
        onRewrite={vi.fn()}
      />
    );

    expect(screen.getByRole("button", { name: "确认加入 qB" })).toBeDisabled();
  });

  it("disables approval and shows submitting text while submitting", () => {
    render(
      <CandidateCard
        payload={payload}
        selectedResultId="r1"
        isSubmitting
        onSelect={vi.fn()}
        onApprove={vi.fn()}
        onCancel={vi.fn()}
        onRewrite={vi.fn()}
      />
    );

    expect(screen.getByRole("button", { name: "提交中" })).toBeDisabled();
  });

  it("keeps radio groups independent when two candidate cards render together", () => {
    render(
      <>
        <CandidateCard
          payload={payload}
          selectedResultId="r1"
          isSubmitting={false}
          onSelect={vi.fn()}
          onApprove={vi.fn()}
          onCancel={vi.fn()}
          onRewrite={vi.fn()}
        />
        <CandidateCard
          payload={payload}
          selectedResultId="r1"
          isSubmitting={false}
          onSelect={vi.fn()}
          onApprove={vi.fn()}
          onCancel={vi.fn()}
          onRewrite={vi.fn()}
        />
      </>
    );

    const selectedCandidates = screen.getAllByRole("radio", { name: "Dune 4K" });
    expect(selectedCandidates).toHaveLength(2);
    expect(selectedCandidates[0]).toBeChecked();
    expect(selectedCandidates[1]).toBeChecked();
    expect(selectedCandidates[0]).not.toHaveAttribute("name", selectedCandidates[1].getAttribute("name"));
  });

  it("uses distinct labelledby targets for repeated receipt cards", () => {
    const { container } = render(
      <>
        <ReceiptCard receipt={{ id: "first" }} />
        <ReceiptCard receipt={{ id: "second" }} />
      </>
    );

    const labelledSections = Array.from(container.querySelectorAll("section[aria-labelledby]"));
    const labelledByIds = labelledSections.map((section) => section.getAttribute("aria-labelledby"));

    expect(labelledByIds).toHaveLength(2);
    expect(new Set(labelledByIds).size).toBe(2);
    labelledByIds.forEach((id) => {
      expect(id).toBeTruthy();
      expect(container.querySelector(`#${CSS.escape(id ?? "")}`)).not.toBeNull();
    });
  });
});
