import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ApprovalCard, type PendingApprovalLike } from "./ApprovalCard";

const pendingApproval: PendingApprovalLike = {
  approval_id: "approval-1",
  tool_name: "qb_add_torrent",
  arguments: {
    torrent_id: "123",
    qb_category: "movie"
  },
  status: "pending",
  expires_at: "2099-06-05T20:00:00",
  risk: {
    level: "side_effect",
    summary: "Submit torrent to qBittorrent in paused state"
  }
};

describe("ApprovalCard", () => {
  it("shows approval details and sends the approval id to both actions", async () => {
    const user = userEvent.setup();
    const onApprove = vi.fn();
    const onDeny = vi.fn();

    render(
      <ApprovalCard
        approval={pendingApproval}
        status="pending"
        isSubmitting={false}
        onApprove={onApprove}
        onDeny={onDeny}
      />,
    );

    expect(screen.getByText("123")).toBeInTheDocument();
    expect(screen.getByText("movie")).toBeInTheDocument();
    expect(screen.getByText("Submit torrent to qBittorrent in paused state")).toBeInTheDocument();
    expect(screen.getByText("等待确认")).toBeInTheDocument();
    expect(screen.getByText(/2099/).closest("time")).toHaveAttribute("datetime", pendingApproval.expires_at);

    await user.click(screen.getByRole("button", { name: "仅批准本次" }));
    await user.click(screen.getByRole("button", { name: "拒绝" }));

    expect(onApprove).toHaveBeenCalledWith("approval-1");
    expect(onDeny).toHaveBeenCalledWith("approval-1");
  });

  it("disables approval actions while busy", () => {
    render(
      <ApprovalCard
        approval={pendingApproval}
        status="pending"
        isSubmitting
        onApprove={vi.fn()}
        onDeny={vi.fn()}
      />,
    );

    expect(screen.getByRole("button", { name: "处理中..." })).toBeDisabled();
    expect(screen.getByRole("button", { name: "拒绝" })).toBeDisabled();
  });

  it("renders batch approval items", () => {
    render(
      <ApprovalCard
        approval={{
          ...pendingApproval,
          tool_name: "qb_add_torrents",
          arguments: {
            items: [
              { torrent_id: "101", qb_category: "电视剧", save_path: "/downloads/tv" },
              { torrent_id: "102", qb_category: "电视剧" }
            ]
          }
        }}
        status="pending"
        isSubmitting={false}
        onApprove={vi.fn()}
        onDeny={vi.fn()}
      />,
    );

    expect(screen.getByText("2 个 torrent")).toBeInTheDocument();
    expect(screen.getByText("101")).toBeInTheDocument();
    expect(screen.getByText("102")).toBeInTheDocument();
    expect(screen.getByText("/downloads/tv")).toBeInTheDocument();
  });

  it("shows session authorization action only when eligible", async () => {
    const user = userEvent.setup();
    const onApproveWithGrant = vi.fn();

    render(
      <ApprovalCard
        approval={{
          ...pendingApproval,
          authorization: { eligible: true }
        }}
        status="pending"
        isSubmitting={false}
        onApprove={vi.fn()}
        onApproveWithGrant={onApproveWithGrant}
        onDeny={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("button", { name: "本会话内允许" }));
    expect(onApproveWithGrant).toHaveBeenCalledWith("approval-1");
  });

  it("hides actions and displays an expired state", () => {
    render(
      <ApprovalCard
        approval={pendingApproval}
        status="expired"
        isSubmitting={false}
        onApprove={vi.fn()}
        onDeny={vi.fn()}
      />,
    );

    expect(screen.getByText("已过期")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("此审批已过期");
    expect(screen.queryByRole("button", { name: "仅批准本次" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "拒绝" })).not.toBeInTheDocument();
  });

  it.each([
    ["approved", "已批准"],
    ["denied", "已拒绝"],
    ["failed", "执行失败"]
  ] as const)("renders the resolved %s status without actions", (status, label) => {
    render(
      <ApprovalCard
        approval={pendingApproval}
        status={status}
        isSubmitting={false}
        onApprove={vi.fn()}
        onDeny={vi.fn()}
      />,
    );

    expect(screen.getByText(label)).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});
