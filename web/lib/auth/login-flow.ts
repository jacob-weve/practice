import { ApiError, apiFetch } from "@/lib/api/client";
import { setAccessToken } from "@/lib/auth/token-store";
import {
  codeChallengeS256,
  generateCodeVerifier,
  savePendingLogin,
  takePendingLogin,
} from "@/lib/auth/pkce";
import type { AuthTokenResponse, AuthorizeResponse, ConsentType } from "@/lib/auth/types";
import { redirectUriFor, type Provider } from "@/lib/config";

export async function startLogin(provider: Provider): Promise<void> {
  const verifier = generateCodeVerifier();
  const params = new URLSearchParams({
    code_challenge: await codeChallengeS256(verifier),
    code_challenge_method: "S256",
    redirect_uri: redirectUriFor(provider),
  });
  const res = await apiFetch<AuthorizeResponse>(`/auth/authorize/${provider}?${params}`, {
    auth: false,
  });
  savePendingLogin(provider, { verifier, state: res.state });
  window.location.assign(res.authorize_url);
}

export async function completeLogin(
  provider: Provider,
  params: URLSearchParams,
): Promise<AuthTokenResponse> {
  const pending = takePendingLogin(provider);
  if (params.get("error")) throw new ApiError(401, "AUTH_PROVIDER_DENIED", "denied");
  if (!pending) throw new ApiError(400, "AUTH_INVALID_STATE", "missing pending login");

  const handoff = params.get("handoff");
  const code = params.get("code");
  const state = params.get("state");
  let body: Record<string, string>;
  if (provider === "apple" && handoff) {
    body = { handoff };
  } else {
    // 서버도 검증하지만, 다른 탭에서 시작된 콜백을 먼저 걸러낸다.
    if (!code || !state || state !== pending.state) {
      throw new ApiError(400, "AUTH_INVALID_STATE", "state mismatch");
    }
    body = { code, state };
  }

  const res = await apiFetch<AuthTokenResponse>(`/auth/login/${provider}`, {
    method: "POST",
    auth: false,
    body: JSON.stringify({
      ...body,
      code_verifier: pending.verifier,
      redirect_uri: redirectUriFor(provider),
    }),
  });
  setAccessToken(res.access_token);
  return res;
}

export interface ConsentDecision {
  type: ConsentType;
  version: string;
  agreed: boolean;
}

export async function submitConsents(consents: ConsentDecision[]) {
  return apiFetch<{ user: AuthTokenResponse["user"] }>("/auth/consents", {
    method: "POST",
    body: JSON.stringify({ consents }),
  });
}

export async function logout(): Promise<void> {
  try {
    await apiFetch<void>("/auth/logout", { method: "POST" });
  } finally {
    setAccessToken(null);
  }
}
