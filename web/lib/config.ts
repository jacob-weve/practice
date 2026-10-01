export const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1";

export const PROVIDERS = ["kakao", "google", "naver", "apple"] as const;
export type Provider = (typeof PROVIDERS)[number];

export function isProvider(value: string): value is Provider {
  return (PROVIDERS as readonly string[]).includes(value);
}

/** 백엔드 OAUTH_REDIRECT_URIS 화이트리스트와 정확히 일치해야 한다. */
export function redirectUriFor(provider: Provider): string {
  if (provider === "apple") {
    // 애플은 form_post로 백엔드가 직접 받는다.
    return `${API_BASE_URL}/auth/callback/apple`;
  }
  return `${window.location.origin}/auth/callback/${provider}`;
}
