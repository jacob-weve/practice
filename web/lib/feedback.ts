import { apiFetch } from "@/lib/api/client";
import type { FeedbackRequest } from "@/lib/api/types";

/** 품질 지표용 신호. 실패해도 사용자 흐름을 막지 않는다. */
export function sendFeedback(body: FeedbackRequest): void {
  void apiFetch<void>("/feedback", { method: "POST", body: JSON.stringify(body) }).catch(
    () => undefined,
  );
}

export async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

export async function shareText(text: string): Promise<boolean> {
  if (typeof navigator.share !== "function") return copyText(text);
  try {
    await navigator.share({ text });
    return true;
  } catch {
    return false;
  }
}
