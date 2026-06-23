import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ApprovalCard, type PendingApprovalLike } from "./ApprovalCard";

const pendingApproval: PendingApprovalLike = {
  approval_id: "approval-1",
  tool_name: "qb_add_torrent",
  arguments: {
    torrent_id: "123",
    qb_category: "movie",
    completion_action: "notify"
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
            completion_action: "notify",
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

  it("does not offer session authorization for organize downloads", () => {
    render(
      <ApprovalCard
        approval={{
          ...pendingApproval,
          arguments: { ...pendingApproval.arguments, completion_action: "organize" },
          authorization: { eligible: true }
        }}
        status="pending"
        isSubmitting={false}
        onApprove={vi.fn()}
        onApproveWithGrant={vi.fn()}
        onDeny={vi.fn()}
      />,
    );

    expect(screen.getByText("完成后整理")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "本会话内允许" })).not.toBeInTheDocument();
  });

  it.each([
    ["once", "notify", "检查一次", "完成后通知", "通知并结束"],
    ["once", "organize", "检查一次", "完成后整理", "通知并结束"],
    ["until_complete", "notify", "持续监督至完成", "完成后通知", "继续动态监督"],
    ["until_complete", "organize", "持续监督至完成", "完成后整理", "继续动态监督"]
  ] as const)(
    "renders monitor_download %s / %s semantics",
    (mode, onCompleted, modeLabel, actionLabel, incompleteLabel) => {
      render(
        <ApprovalCard
          approval={{
            ...pendingApproval,
            tool_name: "monitor_download",
            arguments: {
              torrent_hash: "qb-hash-1",
              start_at: "2099-06-23T19:00:00+08:00",
              mode,
              on_completed: onCompleted
            }
          }}
          status="pending"
          isSubmitting={false}
          onApprove={vi.fn()}
          onDeny={vi.fn()}
        />,
      );

      expect(screen.getByRole("heading", { name: "创建下载监督" })).toBeInTheDocument();
      expect(screen.getByText("qb-hash-1")).toBeInTheDocument();
      expect(screen.getByText(modeLabel)).toBeInTheDocument();
      expect(screen.getByText(actionLabel)).toBeInTheDocument();
      expect(screen.getByText(incompleteLabel)).toBeInTheDocument();
      expect(screen.getByText("首次检查时间").parentElement?.querySelector("time")).toHaveAttribute(
        "datetime",
        "2099-06-23T19:00:00+08:00",
      );
    },
  );

  it("renders immediate monitor start and an atomic monitor update", () => {
    const { rerender } = render(
      <ApprovalCard
        approval={{
          ...pendingApproval,
          tool_name: "monitor_download",
          arguments: {
            torrent_hash: "qb-hash-2",
            mode: "once",
            on_completed: "notify"
          }
        }}
        status="pending"
        isSubmitting={false}
        onApprove={vi.fn()}
        onDeny={vi.fn()}
      />,
    );

    expect(screen.getByText("立即开始")).toBeInTheDocument();

    rerender(
      <ApprovalCard
        approval={{
          ...pendingApproval,
          tool_name: "update_download_monitor",
          arguments: {
            task_id: "task-1",
            start_at: "2099-06-24T09:30:00+08:00",
            mode: "until_complete",
            on_completed: "organize"
          }
        }}
        status="pending"
        isSubmitting={false}
        onApprove={vi.fn()}
        onDeny={vi.fn()}
      />,
    );

    expect(screen.getByRole("heading", { name: "修改下载监督" })).toBeInTheDocument();
    expect(screen.getByText("task-1")).toBeInTheDocument();
    expect(screen.getByText(/可能改变任务性质/)).toBeInTheDocument();
    expect(screen.getByText("持续监督至完成")).toBeInTheDocument();
    expect(screen.getByText("完成后整理")).toBeInTheDocument();
    expect(screen.getByText("继续动态监督")).toBeInTheDocument();
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
