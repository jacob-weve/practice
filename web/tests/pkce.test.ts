import { describe, expect, it } from "vitest";
import {
  codeChallengeS256,
  generateCodeVerifier,
  savePendingLogin,
  takePendingLogin,
} from "@/lib/auth/pkce";

describe("pkce", () => {
  it("matches the RFC 7636 appendix B test vector", async () => {
    const verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk";
    expect(await codeChallengeS256(verifier)).toBe("E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM");
  });

  it("generates 43-char unreserved verifiers", () => {
    const a = generateCodeVerifier();
    expect(a).toMatch(/^[A-Za-z0-9_-]{43}$/);
    expect(generateCodeVerifier()).not.toBe(a);
  });

  it("pending login is read once and then removed", () => {
    savePendingLogin("google", { verifier: "v", state: "s" });
    expect(takePendingLogin("google")).toEqual({ verifier: "v", state: "s" });
    expect(takePendingLogin("google")).toBeNull();
  });
});
