import { describe, expect, it } from "vitest";
import { readJson } from "./http";

describe("readJson", () => {
  it("returns parsed JSON for OK responses", async () => {
    const response = new Response(JSON.stringify({ ok: true }), {
      status: 200,
      headers: { "Content-Type": "application/json" }
    });

    await expect(readJson<{ ok: boolean }>(response)).resolves.toEqual({ ok: true });
  });

  it("rejects OK responses with invalid JSON", async () => {
    const response = new Response("not json", {
      status: 200,
      headers: { "Content-Type": "application/json" }
    });

    await expect(readJson<{ ok: boolean }>(response)).rejects.toBeInstanceOf(SyntaxError);
  });

  it("throws FastAPI detail with HTTP fields for non-ok responses", async () => {
    const response = new Response(JSON.stringify({ detail: "torrent not found" }), {
      status: 404,
      statusText: "Not Found",
      headers: { "Content-Type": "application/json" }
    });

    await expect(readJson(response)).rejects.toMatchObject({
      message: expect.stringContaining("torrent not found"),
      status: 404,
      statusText: "Not Found"
    });
  });

  it("throws status text for non-ok empty responses", async () => {
    const response = new Response(null, {
      status: 503,
      statusText: "Service Unavailable"
    });

    await expect(readJson(response)).rejects.toMatchObject({
      message: expect.stringContaining("Service Unavailable"),
      status: 503,
      statusText: "Service Unavailable"
    });
  });

  it("throws HTTP status for non-ok invalid JSON responses without status text", async () => {
    const response = new Response("not json", {
      status: 500,
      headers: { "Content-Type": "application/json" }
    });

    await expect(readJson(response)).rejects.toMatchObject({
      message: expect.stringContaining("HTTP 500"),
      status: 500
    });
  });
});
