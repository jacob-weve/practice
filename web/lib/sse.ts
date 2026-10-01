import { ApiError, refreshAccessToken, toApiError } from "@/lib/api/client";
import { getAccessToken } from "@/lib/auth/token-store";
import { API_BASE_URL } from "@/lib/config";

export interface SseMessage {
  event: string;
  data: unknown;
}

/** 버퍼에서 완성된 이벤트(빈 줄로 끝나는 블록)만 꺼내고 나머지는 돌려준다. */
export function parseSseBuffer(buffer: string): { messages: SseMessage[]; rest: string } {
  const normalized = buffer.replace(/\r\n/g, "\n");
  const blocks = normalized.split("\n\n");
  const rest = blocks.pop() ?? "";
  const messages: SseMessage[] = [];
  for (const block of blocks) {
    let event = "message";
    const dataLines: string[] = [];
    for (const line of block.split("\n")) {
      if (line.startsWith(":")) continue; // keep-alive 주석
      if (line.startsWith("event:")) event = line.slice(6).trim();
      else if (line.startsWith("data:")) dataLines.push(line.slice(5).replace(/^ /, ""));
    }
    if (dataLines.length === 0) continue;
    const raw = dataLines.join("\n");
    let data: unknown = raw;
    try {
      data = JSON.parse(raw);
    } catch {
      // JSON이 아닌 데이터는 문자열 그대로 넘긴다.
    }
    messages.push({ event, data });
  }
  return { messages, rest };
}

interface SseErrorData {
  code?: string;
  message?: string;
  request_id?: string;
}

/**
 * 인증이 필요한 POST SSE 요청. EventSource는 헤더를 못 보내므로 fetch 스트림을 쓴다.
 * 스트림 시작 전 401이면 토큰을 갱신해 한 번 재시도한다. `error` 이벤트는 ApiError로 던진다.
 */
export async function postSse(
  path: string,
  body: unknown,
  onMessage: (message: SseMessage) => void,
  { signal, fetchImpl = fetch }: { signal?: AbortSignal; fetchImpl?: typeof fetch } = {},
): Promise<void> {
  const send = (token: string | null) =>
    fetchImpl(`${API_BASE_URL}${path}`, {
      method: "POST",
      credentials: "include",
      signal,
      headers: {
        "Content-Type": "application/json",
        Accept: "text/event-stream",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify(body),
    });

  let res = await send(getAccessToken());
  if (res.status === 401) {
    const token = await refreshAccessToken(fetchImpl);
    if (token) res = await send(token);
  }
  if (!res.ok || !res.body) throw await toApiError(res);

  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    const parsed = parseSseBuffer(buffer + value);
    buffer = parsed.rest;
    for (const message of parsed.messages) {
      if (message.event === "error") {
        const err = message.data as SseErrorData;
        throw new ApiError(500, err.code ?? "INTERNAL_ERROR", err.message ?? "", err.request_id);
      }
      onMessage(message);
    }
  }
}
