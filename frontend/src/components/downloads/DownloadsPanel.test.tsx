import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DownloadsPanel } from "./DownloadsPanel";

type Deferred<T> = {
  promise: Promise<T>;
  resolve: (value: T) => void;
  reject: (reason?: unknown) => void;
};

function createDeferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((innerResolve, innerReject) => {
    resolve = innerResolve;
    reject = innerReject;
  });
  return { promise, resolve, reject };
}

function torrentSummary(hash: string, name: string, state = "downloading") {
  return {
    hash,
    name,
    category: "movies",
    tags: ["uhd"],
    state,
    progress: 0.62,
    download_speed: 1024,
    upload_speed: 64,
    eta: 1200,
    save_path: `/downloads/${hash}`,
    size: 10,
    total_size: 20
  };
}

function torrentDetail(hash: string, name: string, savePath: string) {
  return {
    ...torrentSummary(hash, name),
    save_path: savePath,
    comment: "",
    total_uploaded: 5,
    share_ratio: 1.25,
    creation_date: 1
  };
}

function rowButtonFor(name: string): HTMLButtonElement {
  const row = screen.getByText(name).closest("button");
  if (!(row instanceof HTMLButtonElement)) {
    throw new Error(`Row button not found for ${name}`);
  }
  return row;
}

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

  it("ignores stale detail responses after the user switches selection", async () => {
    const user = userEvent.setup();
    const firstDetail = createDeferred<Response>();
    const secondDetail = createDeferred<Response>();

    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url === "/qb/torrents") {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              items: [torrentSummary("hash-1", "Dune 2160p"), torrentSummary("hash-2", "Arrival 1080p")]
            }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          ),
        );
      }
      if (url === "/qb/torrents/hash-1") {
        return firstDetail.promise;
      }
      if (url === "/qb/torrents/hash-2") {
        return secondDetail.promise;
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });

    render(<DownloadsPanel id="workspace-panel-downloads" labelledBy="workspace-tab-downloads" refreshSignal={0} />);

    expect(await screen.findByText("Dune 2160p")).toBeInTheDocument();
    await user.click(rowButtonFor("Arrival 1080p"));

    secondDetail.resolve(
      new Response(JSON.stringify(torrentDetail("hash-2", "Arrival 1080p", "/downloads/arrival")), {
        status: 200,
        headers: { "Content-Type": "application/json" }
      }),
    );

    expect(await screen.findByText("/downloads/arrival")).toBeInTheDocument();

    firstDetail.resolve(
      new Response(JSON.stringify(torrentDetail("hash-1", "Dune 2160p", "/downloads/dune")), {
        status: 200,
        headers: { "Content-Type": "application/json" }
      }),
    );

    await waitFor(() => {
      expect(screen.getByText("/downloads/arrival")).toBeInTheDocument();
      expect(screen.queryByText("/downloads/dune")).not.toBeInTheDocument();
    });
  });

  it("clears stale detail when switching rows and keeps it cleared if the new detail load fails", async () => {
    const user = userEvent.setup();
    const secondDetail = createDeferred<Response>();

    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url === "/qb/torrents") {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              items: [torrentSummary("hash-1", "Dune 2160p"), torrentSummary("hash-2", "Arrival 1080p")]
            }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          ),
        );
      }
      if (url === "/qb/torrents/hash-1") {
        return Promise.resolve(
          new Response(JSON.stringify(torrentDetail("hash-1", "Dune 2160p", "/downloads/dune")), {
            status: 200,
            headers: { "Content-Type": "application/json" }
          }),
        );
      }
      if (url === "/qb/torrents/hash-2") {
        return secondDetail.promise;
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });

    render(<DownloadsPanel id="workspace-panel-downloads" labelledBy="workspace-tab-downloads" refreshSignal={0} />);

    expect(await screen.findByText("/downloads/dune")).toBeInTheDocument();

    await user.click(rowButtonFor("Arrival 1080p"));

    await waitFor(() => {
      expect(screen.queryByText("/downloads/dune")).not.toBeInTheDocument();
    });
    expect(screen.getByText("选择一个任务以查看详情。")).toBeInTheDocument();

    secondDetail.reject(new Error("detail failed"));

    expect(await screen.findByText("detail failed")).toBeInTheDocument();
    expect(screen.queryByText("/downloads/dune")).not.toBeInTheDocument();
  });
});
