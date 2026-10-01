function base64Url(bytes: Uint8Array): string {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

/** RFC 7636: 43~128자의 unreserved 문자. 32바이트 난수 → 43자. */
export function generateCodeVerifier(): string {
  const bytes = new Uint8Array(32);
  crypto.getRandomValues(bytes);
  return base64Url(bytes);
}

export async function codeChallengeS256(verifier: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier));
  return base64Url(new Uint8Array(digest));
}

const STORAGE_PREFIX = "ts_pkce:";

interface PendingLogin {
  verifier: string;
  state: string;
}

// code_verifier는 토큰이 아니지만 탭을 벗어나지 않도록 sessionStorage에만 두고, 콜백에서 즉시 지운다.
export function savePendingLogin(provider: string, pending: PendingLogin): void {
  sessionStorage.setItem(STORAGE_PREFIX + provider, JSON.stringify(pending));
}

export function takePendingLogin(provider: string): PendingLogin | null {
  const key = STORAGE_PREFIX + provider;
  const raw = sessionStorage.getItem(key);
  sessionStorage.removeItem(key);
  if (!raw) return null;
  try {
    const parsed: unknown = JSON.parse(raw);
    if (
      typeof parsed === "object" &&
      parsed !== null &&
      typeof (parsed as PendingLogin).verifier === "string" &&
      typeof (parsed as PendingLogin).state === "string"
    ) {
      return parsed as PendingLogin;
    }
  } catch {
    // 손상된 값은 무시한다.
  }
  return null;
}
