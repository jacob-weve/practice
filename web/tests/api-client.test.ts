import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, apiFetch } from "@/lib/api/client";
import { getAccessToken, setAccessToken } from "@/lib/auth/token-store";

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const expired = () => json(401, { error: { code: "AUTH_TOKEN_EXPIRED", message: "expired" } });

describe("apiFetch", () => {
  beforeEach(() => setAccessToken("old"));

  it("refreshes once for concurrent 401s and retries with the new token", async () => {
    let refreshCalls = 0;
    const fetchImpl = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/auth/refresh")) {
        refreshCalls += 1;
        expect(new Headers(init?.headers).get("X-Requested-With")).toBe("talksoft");
        await new Promise((r) => setTimeout(r, 5));
        return json(200, { access_token: "new" });
      }
      const auth = new Headers(init?.headers).get("Authorization");
      return auth === "Bearer new" ? json(200, { ok: true }) : expired();
    }) as unknown as typeof fetch;

    const results = await Promise.all([
      apiFetch<{ ok: boolean }>("/a", {}, fetchImpl),
      apiFetch<{ ok: boolean }>("/b", {}, fetchImpl),
    ]);
    expect(results).toEqual([{ ok: true }, { ok: true }]);
    expect(refreshCalls).toBe(1);
    expect(getAccessToken()).toBe("new");
  });

  it("clears the token and throws when refresh fails", async () => {
    const fetchImpl = vi.fn(async (input: RequestInfo | URL) =>
      String(input).endsWith("/auth/refresh")
        ? json(401, { error: { code: "AUTH_REFRESH_INVALID", message: "x" } })
        : expired(),
    ) as unknown as typeof fetch;

    await expect(apiFetch("/a", {}, fetchImpl)).rejects.toMatchObject({
      code: "AUTH_TOKEN_EXPIRED",
    });
    expect(getAccessToken()).toBeNull();
  });

  it("maps the error envelope to ApiError", async () => {
    const fetchImpl = vi.fn(async () =>
      json(429, { error: { code: "RATE_LIMITED", message: "slow", request_id: "r1" } }),
    ) as unknown as typeof fetch;
    const err = await apiFetch("/a", {}, fetchImpl).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err).toMatchObject({ status: 429, code: "RATE_LIMITED", requestId: "r1" });
  });
});
