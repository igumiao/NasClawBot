import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DownloadsPanel } from "./DownloadsPanel";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("DownloadsPanel", () => {
  it("loads torrents, loads the selected detail, and pauses a torrent", async () => {
    const user = userEvent.setup();

    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            items: [
              {
                hash: "hash-1",
                name: "Dune 2160p",
                category: "movies",
                tags: ["uhd"],
                state: "downloading",
                progress: 0.62,
                download_speed: 1024,
                upload_speed: 64,
                eta: 1200,
                save_path: "/downloads/dune",
                size: 10,
                total_size: 20
              }
            ]
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            hash: "hash-1",
            name: "Dune 2160p",
            category: "movies",
            tags: ["uhd"],
            state: "downloading",
            progress: 0.62,
            download_speed: 1024,
            upload_speed: 64,
            eta: 1200,
            save_path: "/downloads/dune",
            size: 10,
            total_size: 20,
            comment: "",
            total_uploaded: 5,
            share_ratio: 1.25,
            creation_date: 1
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            ok: true,
            status: "paused",
            qb_hash: "hash-1"
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            items: [
              {
                hash: "hash-1",
                name: "Dune 2160p",
                category: "movies",
                tags: ["uhd"],
                state: "pausedDL",
                progress: 0.62,
                download_speed: 0,
                upload_speed: 0,
                eta: 0,
                save_path: "/downloads/dune",
                size: 10,
                total_size: 20
              }
            ]
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            hash: "hash-1",
            name: "Dune 2160p",
            category: "movies",
            tags: ["uhd"],
            state: "pausedDL",
            progress: 0.62,
            download_speed: 0,
            upload_speed: 0,
            eta: 0,
            save_path: "/downloads/dune",
            size: 10,
            total_size: 20,
            comment: "",
            total_uploaded: 5,
            share_ratio: 1.25,
            creation_date: 1
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      );

    render(<DownloadsPanel id="workspace-panel-downloads" labelledBy="workspace-tab-downloads" refreshSignal={0} />);

    expect(await screen.findByText("Dune 2160p")).toBeInTheDocument();
    expect(await screen.findByText("/downloads/dune")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "暂停" }));

    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledWith(
        "/qb/torrents/hash-1/actions",
        expect.objectContaining({ method: "POST" }),
      );
    });
  });
});
