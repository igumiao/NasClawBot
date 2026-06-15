import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { SearchResultCard } from "./SearchResultCard";

const result = {
  id: "123",
  title: "Dune Part Two 2160p",
  media_type: "movie",
  year: 2024,
  resolution: "2160p",
  seeders: 88,
  leechers: 12,
  discount: "FREE",
  imdb: "tt15239678",
  douban: "35575567",
  size: "42 GB",
  size_bytes: 42_000_000_000,
  source: "mteam",
  small_description: "中英双语特效字幕",
  subtitle_flags: ["中字", "中英", "特效"],
  labels_new: ["中字"],
};

describe("SearchResultCard", () => {
  it("shows Agent search metadata and requests the selected torrent", async () => {
    const user = userEvent.setup();
    const onDownload = vi.fn();

    render(<SearchResultCard results={[result]} isSubmitting={false} onDownload={onDownload} />);

    // Card is collapsed by default — expand first.
    await user.click(screen.getByRole("button", { name: "展开 ▼" }));

    expect(screen.getByText("2160p")).toBeInTheDocument();
    expect(screen.getByText("42 GB")).toBeInTheDocument();
    expect(screen.getByText("88 seeders")).toBeInTheDocument();
    expect(screen.getByText("12 leechers")).toBeInTheDocument();
    expect(screen.getByText("FREE")).toBeInTheDocument();
    expect(screen.getByText("IMDb tt15239678")).toBeInTheDocument();
    expect(screen.getByText("豆瓣 35575567")).toBeInTheDocument();
    expect(screen.getByText("Torrent ID 123")).toBeInTheDocument();
    expect(screen.getByText("中字")).toBeInTheDocument();
    expect(screen.getByText("中英")).toBeInTheDocument();
    expect(screen.getByText("特效")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "请求下载" }));

    expect(onDownload).toHaveBeenCalledWith("123");
  });

  it("disables download requests while another request is submitting", async () => {
    const user = userEvent.setup();
    render(<SearchResultCard results={[result]} isSubmitting onDownload={vi.fn()} />);

    // Card is collapsed by default — expand first.
    await user.click(screen.getByRole("button", { name: "展开 ▼" }));

    expect(screen.getByRole("button", { name: "请求中" })).toBeDisabled();
  });
});
