import { describe, expect, it } from "vitest";
import { downloadsInitialState, downloadsReducer, visibleTorrents } from "./downloadsState";

const torrent = {
  hash: "hash-1",
  name: "Dune",
  category: "movies",
  tags: ["mteam"],
  state: "pausedDL",
  progress: 0,
  download_speed: 0,
  upload_speed: 0,
  eta: 0,
  save_path: "/downloads",
  size: 100,
  total_size: 100
};

function torrentWith(overrides: Partial<typeof torrent>) {
  return { ...torrent, ...overrides };
}

describe("downloadsState", () => {
  it("stores torrent lists and selects the first item", () => {
    const state = downloadsReducer(downloadsInitialState, {
      type: "list_loaded",
      items: [torrent]
    });

    expect(state.torrentItems).toHaveLength(1);
    expect(state.selectedTorrentHash).toBe("hash-1");
  });

  it("filters paused torrents", () => {
    const state = { ...downloadsInitialState, torrentItems: [torrent], filter: "paused" as const };

    expect(visibleTorrents(state)).toHaveLength(1);
  });

  it("moves selection to a refreshed item and clears stale detail when the selected hash disappears", () => {
    const staleDetail = { ...torrent, comment: "", total_uploaded: 0, share_ratio: 0, creation_date: 0 };
    const refreshed = torrentWith({ hash: "hash-2", name: "Blade Runner" });

    const state = downloadsReducer(
      {
        ...downloadsInitialState,
        torrentItems: [torrent],
        selectedTorrentHash: "hash-1",
        torrentDetail: staleDetail
      },
      {
        type: "list_loaded",
        items: [refreshed]
      }
    );

    expect(state.selectedTorrentHash).toBe("hash-2");
    expect(state.torrentDetail).toBeNull();
  });

  it("clears selection and detail when refreshed list is empty", () => {
    const staleDetail = { ...torrent, comment: "", total_uploaded: 0, share_ratio: 0, creation_date: 0 };

    const state = downloadsReducer(
      {
        ...downloadsInitialState,
        torrentItems: [torrent],
        selectedTorrentHash: "hash-1",
        torrentDetail: staleDetail
      },
      {
        type: "list_loaded",
        items: []
      }
    );

    expect(state.selectedTorrentHash).toBeNull();
    expect(state.torrentDetail).toBeNull();
  });

  it("filters torrents using explicit qBittorrent paused, completed, and downloading states", () => {
    const paused = [
      torrentWith({ hash: "stopped-dl", state: "stoppedDL" }),
      torrentWith({ hash: "stopped-up", state: "stoppedUP" }),
      torrentWith({ hash: "paused-dl", state: "pausedDL" })
    ];
    const completed = [
      torrentWith({ hash: "uploading", state: "uploading", progress: 1 }),
      torrentWith({ hash: "stalled-up", state: "stalledUP", progress: 1 })
    ];
    const downloading = [
      torrentWith({ hash: "queued-dl", state: "queuedDL" }),
      torrentWith({ hash: "stalled-dl", state: "stalledDL" }),
      torrentWith({ hash: "forced-dl", state: "forcedDL" }),
      torrentWith({ hash: "meta-dl", state: "metaDL" }),
      torrentWith({ hash: "downloading", state: "downloading" })
    ];
    const ambiguous = torrentWith({ hash: "contains-download", state: "downloadWaiting" });
    const torrentItems = [...paused, ...completed, ...downloading, ambiguous];

    expect(visibleTorrents({ ...downloadsInitialState, torrentItems, filter: "paused" }).map((item) => item.hash)).toEqual([
      "stopped-dl",
      "stopped-up",
      "paused-dl"
    ]);
    expect(
      visibleTorrents({ ...downloadsInitialState, torrentItems, filter: "completed" }).map((item) => item.hash)
    ).toEqual(["uploading", "stalled-up"]);
    expect(
      visibleTorrents({ ...downloadsInitialState, torrentItems, filter: "downloading" }).map((item) => item.hash)
    ).toEqual(["queued-dl", "stalled-dl", "forced-dl", "meta-dl", "downloading"]);
  });
});
