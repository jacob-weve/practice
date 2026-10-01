import { API_BASE_URL } from "@/lib/config";
import { getAccessToken, setAccessToken } from "@/lib/auth/token-store";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly requestId?: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

interface ErrorEnvelope {
  error?: { code?: string; message?: string; request_id?: string };
}

export async function toApiError(res: Response): Promise<ApiError> {
  let body: ErrorEnvelope = {};
  try {
    body = (await res.json()) as ErrorEnvelope;
  } catch {
    // JSON이 아닌 응답(프록시 오류 등)
  }
  return new ApiError(
    res.status,
    body.error?.code ?? "HTTP_ERROR",
    body.error?.message ?? res.statusText,
    body.error?.request_id,
  );
}

interface RefreshResponse {
  access_token: string;
}

let refreshInFlight: Promise<string | null> | null = null;

/** 동시에 여러 요청이 401을 받아도 refresh는 한 번만 호출한다(single-flight). */
export function refreshAccessToken(fetchImpl: typeof fetch = fetch): Promise<string | null> {
  refreshInFlight ??= (async () => {
    try {
      const res = await fetchImpl(`${API_BASE_URL}/auth/refresh`, {
        method: "POST",
        credentials: "include",
        headers: { "X-Requested-With": "talksoft" },
      });
      if (!res.ok) {
        setAccessToken(null);
        return null;
      }
      const body = (await res.json()) as RefreshResponse;
      setAccessToken(body.access_token);
      return body.access_token;
    } finally {
      refreshInFlight = null;
    }
  })();
  return refreshInFlight;
}

const RETRYABLE_AUTH_CODES = new Set(["AUTH_TOKEN_EXPIRED", "AUTH_TOKEN_INVALID"]);

export async function apiFetch<T>(
  path: string,
  init: RequestInit & { auth?: boolean } = {},
  fetchImpl: typeof fetch = fetch,
): Promise<T> {
  const { auth = true, ...rest } = init;

  const send = (token: string | null) => {
    const headers = new Headers(rest.headers);
    if (rest.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
    if (auth && token) headers.set("Authorization", `Bearer ${token}`);
    return fetchImpl(`${API_BASE_URL}${path}`, { ...rest, headers, credentials: "include" });
  };

  let res = await send(getAccessToken());
  if (res.status === 401 && auth) {
    const error = await toApiError(res.clone());
    if (RETRYABLE_AUTH_CODES.has(error.code)) {
      const token = await refreshAccessToken(fetchImpl);
      if (token) res = await send(token);
    }
  }
  if (!res.ok) throw await toApiError(res);
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}
