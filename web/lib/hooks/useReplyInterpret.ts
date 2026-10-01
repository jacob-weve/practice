"use client";

import { useCallback, useRef, useState } from "react";
import { ApiError } from "@/lib/api/client";
import type {
  EmotionOut,
  Guide,
  Interpretation,
  ReplyInterpretRequest,
  SuggestedReplyOut,
} from "@/lib/api/types";
import { addHistory } from "@/lib/history-db";
import { postSse, type SseMessage } from "@/lib/sse";
import type { StreamStatus } from "@/lib/hooks/useToneTransform";

export interface InterpretState {
  status: StreamStatus;
  requestId?: string;
  emotion?: EmotionOut;
  interpretations: Interpretation[];
  guide?: Guide;
  replies: SuggestedReplyOut[];
  disclaimer?: string;
  errorCode?: string;
}

const INITIAL: InterpretState = { status: "idle", interpretations: [], replies: [] };

export function reduceInterpret(state: InterpretState, message: SseMessage): InterpretState {
  const data = message.data as Record<string, unknown>;
  switch (message.event) {
    case "meta":
      return { ...state, requestId: data.request_id as string };
    case "analysis":
      return { ...state, emotion: data.message_emotion as EmotionOut };
    case "interpretation":
      return {
        ...state,
        interpretations: [...state.interpretations, data as unknown as Interpretation],
      };
    case "guide":
      return { ...state, guide: data as unknown as Guide };
    case "reply":
      return { ...state, replies: [...state.replies, data as unknown as SuggestedReplyOut] };
    case "done":
      return { ...state, status: "done", disclaimer: data.disclaimer as string };
    default:
      return state;
  }
}

export function useReplyInterpret() {
  const [state, setState] = useState<InterpretState>(INITIAL);
  const abortRef = useRef<AbortController | null>(null);

  const run = useCallback(async (req: ReplyInterpretRequest) => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    let latest: InterpretState = { ...INITIAL, status: "streaming" };
    setState(latest);
    try {
      await postSse(
        "/reply/interpret",
        req,
        (message) => {
          latest = reduceInterpret(latest, message);
          setState(latest);
        },
        { signal: controller.signal },
      );
      if (latest.status === "done") {
        await addHistory({ kind: "reply_interpret", draft: req.message, result: latest }).catch(
          () => undefined,
        );
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

  return { state, run };
}
