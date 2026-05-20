import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { ConfirmationPayload } from "../../types/api";
import { CandidateCard } from "./CandidateCard";

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
});
