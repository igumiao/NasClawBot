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
});
