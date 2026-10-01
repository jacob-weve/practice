import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api/client";
import { setAccessToken } from "@/lib/auth/token-store";
import { parseSseBuffer, postSse, type SseMessage } from "@/lib/sse";

function streamOf(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
}

describe("parseSseBuffer", () => {
  it("splits complete events, skips keep-alives, and keeps the partial tail", () => {
    const { messages, rest } = parseSseBuffer(
      'event: meta\ndata: {"a":1}\n\n: keep-alive\n\nevent: variant\ndata: {"b"',
    );
    expect(messages).toEqual([{ event: "meta", data: { a: 1 } }]);
    expect(rest).toBe('event: variant\ndata: {"b"');
  });

  it("handles CRLF and non-JSON data", () => {
    const { messages } = parseSseBuffer("event: x\r\ndata: hello\r\n\r\n");
    expect(messages).toEqual([{ event: "x", data: "hello" }]);
  });
});

describe("postSse", () => {
  beforeEach(() => setAccessToken("tok"));

  it("delivers events across arbitrary chunk boundaries", async () => {
    const body =
      'event: meta\ndata: {"request_id":"r1"}\n\nevent: variant\ndata: {"text":"안녕"}\n\nevent: done\ndata: {}\n\n';
    const chunks = Array.from({ length: Math.ceil(body.length / 7) }, (_, i) =>
      body.slice(i * 7, i * 7 + 7),
    );
    const fetchImpl = vi.fn(async (_url: RequestInfo | URL, init?: RequestInit) => {
      expect(new Headers(init?.headers).get("Authorization")).toBe("Bearer tok");
      expect(new Headers(init?.headers).get("Accept")).toBe("text/event-stream");
      return new Response(streamOf(chunks), { status: 200 });
    }) as unknown as typeof fetch;

    const seen: SseMessage[] = [];
    await postSse("/tone/transform", {}, (m) => seen.push(m), { fetchImpl });
    expect(seen.map((m) => m.event)).toEqual(["meta", "variant", "done"]);
    expect(seen[1]?.data).toEqual({ text: "안녕" });
  });

  it("turns an error event into ApiError", async () => {
    const fetchImpl = vi.fn(
      async () =>
        new Response(
          streamOf([
            'event: meta\ndata: {}\n\nevent: error\ndata: {"code":"INPUT_REJECTED","message":"no","request_id":"r"}\n\n',
          ]),
        ),
    ) as unknown as typeof fetch;
    const err = await postSse("/x", {}, () => undefined, { fetchImpl }).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err).toMatchObject({ code: "INPUT_REJECTED", requestId: "r" });
  });

  it("refreshes once on 401 before the stream starts", async () => {
    const calls: string[] = [];
    const fetchImpl = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
      const u = String(url);
      calls.push(
        u.endsWith("/auth/refresh")
          ? "refresh"
          : (new Headers(init?.headers).get("Authorization") ?? ""),
      );
      if (u.endsWith("/auth/refresh")) {
        return new Response(JSON.stringify({ access_token: "new" }), { status: 200 });
      }
      if (new Headers(init?.headers).get("Authorization") === "Bearer tok") {
        return new Response(JSON.stringify({ error: { code: "AUTH_TOKEN_EXPIRED" } }), {
          status: 401,
        });
      }
      return new Response(streamOf(["event: done\ndata: {}\n\n"]));
    }) as unknown as typeof fetch;
    const seen: string[] = [];
    await postSse("/x", {}, (m) => seen.push(m.event), { fetchImpl });
    expect(calls).toEqual(["Bearer tok", "refresh", "Bearer new"]);
    expect(seen).toEqual(["done"]);
  });

  it("maps non-stream error responses to ApiError", async () => {
    const fetchImpl = vi.fn(
      async () =>
        new Response(JSON.stringify({ error: { code: "INPUT_TOO_LONG", message: "long" } }), {
          status: 413,
        }),
    ) as unknown as typeof fetch;
    await expect(postSse("/x", {}, () => undefined, { fetchImpl })).rejects.toMatchObject({
      status: 413,
      code: "INPUT_TOO_LONG",
    });
  });
});
