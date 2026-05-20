import { afterEach, describe, expect, it, vi } from "vitest";
import { downloadsApi } from "./downloadsApi";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("downloadsApi", () => {
  it("lists qB torrents", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          items: [
            {
              hash: "hash-1",
              name: "Dune",
              category: "movies",
              tags: ["mteam"],
              state: "pausedDL",
              progress: 0.42,
              download_speed: 0,
              upload_speed: 0,
              eta: 3600,
              save_path: "/downloads",
              size: 100,
              total_size: 100
            }
          ]
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );

    const result = await downloadsApi.listTorrents();

    expect(result.items).toHaveLength(1);
    expect(result.items[0]?.hash).toBe("hash-1");
  });

  it("runs a torrent action", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ ok: true, status: "paused", qb_hash: "hash-1" }), {
        status: 200,
        headers: { "Content-Type": "application/json" }
      }),
    );

    const result = await downloadsApi.runTorrentAction("hash-1", "pause");

    expect(fetchMock).toHaveBeenCalledWith(
      "/qb/torrents/hash-1/actions",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ action: "pause", delete_files: false })
      }),
    );
    expect(result.ok).toBe(true);
  });

  it("encodes torrent hashes when running torrent actions", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ ok: true, status: "paused", qb_hash: "abc/def?x=1" }), {
        status: 200,
        headers: { "Content-Type": "application/json" }
      }),
    );

    await downloadsApi.runTorrentAction("abc/def?x=1", "pause");

    expect(fetchMock).toHaveBeenCalledWith(
      "/qb/torrents/abc%2Fdef%3Fx%3D1/actions",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ action: "pause", delete_files: false })
      }),
    );
  });

  it("encodes torrent hashes when fetching torrent details", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          hash: "abc/def?x=1",
          name: "Dune",
          category: "movies",
          tags: [],
          state: "downloading",
          progress: 0.5,
          download_speed: 10,
          upload_speed: 1,
          eta: 120,
          save_path: "/downloads",
          size: 100,
          total_size: 200
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );

    await downloadsApi.getTorrent("abc/def?x=1");

    expect(fetchMock).toHaveBeenCalledWith("/qb/torrents/abc%2Fdef%3Fx%3D1", expect.any(Object));
  });
});
