// Access Token은 메모리에만 둔다 (CLAUDE.md §4.1). 새로고침 시 HttpOnly 쿠키로 재발급받는다.
let accessToken: string | null = null;

export function getAccessToken(): string | null {
  return accessToken;
}

export function setAccessToken(token: string | null): void {
  accessToken = token;
}
