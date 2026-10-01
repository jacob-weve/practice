"use client";

import { useCallback, useRef, useState } from "react";
import { ApiError } from "@/lib/api/client";
import type {
  EmotionOut,
  Intent,
  RedFlagOut,
  ToneTransformRequest,
  VariantOut,
} from "@/lib/api/types";
import { addHistory } from "@/lib/history-db";
import { postSse, type SseMessage } from "@/lib/sse";

export type StreamStatus = "idle" | "streaming" | "done" | "error";

export interface IndexedVariant extends VariantOut {
  index: number;
}

export interface TransformState {
  status: StreamStatus;
  requestId?: string;
  tier?: string;
  intent?: Intent;
  emotion?: EmotionOut;
  redFlags: RedFlagOut[];
  variants: IndexedVariant[];
  errorCode?: string;
}

const INITIAL: TransformState = { status: "idle", redFlags: [], variants: [] };

/** SSE 이벤트를 화면 상태로 바꾼다. 테스트를 위해 순수 함수로 둔다. */
export function reduceTransform(state: TransformState, message: SseMessage): TransformState {
  const data = message.data as Record<string, unknown>;
  switch (message.event) {
    case "meta":
      return {
        ...state,
        requestId: data.request_id as string,
        tier: data.model_tier as string,
      };
    case "analysis":
      return { ...state, intent: data.intent as Intent, emotion: data.emotion as EmotionOut };
    case "red_flags":
      return { ...state, redFlags: data.red_flags as RedFlagOut[] };
    case "variant":
      return { ...state, variants: [...state.variants, data as unknown as IndexedVariant] };
    case "done":
      return { ...state, status: "done" };
    default:
      return state;
  }
}

export function useToneTransform() {
  const [state, setState] = useState<TransformState>(INITIAL);
  const abortRef = useRef<AbortController | null>(null);

  const run = useCallback(async (req: ToneTransformRequest) => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    let latest: TransformState = { ...INITIAL, status: "streaming" };
    setState(latest);
    try {
      await postSse(
        "/tone/transform",
        req,
        (message) => {
          latest = reduceTransform(latest, message);
          setState(latest);
        },
        { signal: controller.signal },
      );
      if (latest.status === "done") {
        await addHistory({
          kind: "tone_transform",
          context: req.context ?? undefined,
          draft: req.draft,
          persona: req.persona,
          targetLang: req.target_lang,
          result: latest,
        }).catch(() => undefined); // 저장소를 못 쓰는 환경(사생활 보호 모드)에서도 결과는 보여준다.
      }
    } catch (err) {
      if (controller.signal.aborted) return;
      setState({
        ...latest,
        status: "error",
        errorCode: err instanceof ApiError ? err.code : "INTERNAL_ERROR",
      });
    }
  }, []);

  const cancel = useCallback(() => {
    abortRef.current?.abort();
    setState((s) => (s.status === "streaming" ? { ...s, status: "idle" } : s));
  }, []);

  return { state, run, cancel };
}
