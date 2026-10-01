import { describe, expect, it } from "vitest";
import type { RedFlagOut } from "@/lib/api/types";
import { parseConversation } from "@/lib/conversation";
import { segmentDraft } from "@/lib/highlight";
import { reduceInterpret } from "@/lib/hooks/useReplyInterpret";
import { reduceTransform, type TransformState } from "@/lib/hooks/useToneTransform";

function flag(start: number, end: number, text: string): RedFlagOut {
  return { start, end, text, type: "blame", severity: "high", reason: "r", suggestion: "s" };
}

describe("segmentDraft", () => {
  it("uses UTF-16 offsets from the server as-is (emoji takes two units)", () => {
    const draft = "😡 진짜 왜 그래";
    const segments = segmentDraft(draft, [flag(6, 10, "왜 그래")]);
    expect(segments).toEqual([
      { text: "😡 진짜 " },
      { text: "왜 그래", flag: flag(6, 10, "왜 그래") },
    ]);
  });

  it("skips overlapping, out-of-range and stale flags", () => {
    const draft = "abcdef";
    const segments = segmentDraft(draft, [
      flag(0, 2, "ab"),
      flag(1, 3, "bc"), // 겹침
      flag(4, 9, "ef"), // 범위 밖
      flag(3, 4, "x"), // 초안이 바뀐 뒤의 결과
    ]);
    expect(segments.filter((s) => s.flag).map((s) => s.text)).toEqual(["ab"]);
    expect(segments.map((s) => s.text).join("")).toBe(draft);
  });
});

describe("reducers", () => {
  it("builds transform state from SSE events", () => {
    const events = [
      { event: "meta", data: { request_id: "r1", model_tier: "light" } },
      {
        event: "analysis",
        data: {
          intent: { label: "decline", confidence: 0.9 },
          emotion: { temperature: 80, zone: "warning", labels: [] },
        },
      },
      { event: "red_flags", data: { red_flags: [flag(0, 1, "a")] } },
      {
        event: "variant",
        data: { index: 0, kind: "primary", text: "t", expected_temperature: 40, rationale: null },
      },
      { event: "done", data: {} },
    ];
    const state = events.reduce<TransformState>(reduceTransform, {
      status: "streaming",
      redFlags: [],
      variants: [],
    });
    expect(state).toMatchObject({ status: "done", requestId: "r1", tier: "light" });
    expect(state.emotion?.zone).toBe("warning");
    expect(state.redFlags).toHaveLength(1);
    expect(state.variants[0]?.text).toBe("t");
  });

  it("builds interpret state from SSE events", () => {
    const state = [
      { event: "interpretation", data: { summary: "a", likelihood: 0.6, signals: [] } },
      { event: "reply", data: { style: "confirm", text: "ok", rationale: "r" } },
      { event: "done", data: { disclaimer: "d" } },
    ].reduce(reduceInterpret, { status: "streaming", interpretations: [], replies: [] });
    expect(state).toMatchObject({ status: "done", disclaimer: "d" });
    expect(state.interpretations).toHaveLength(1);
    expect(state.replies[0]?.text).toBe("ok");
  });
});

describe("parseConversation", () => {
  it("assigns speakers by prefix and keeps the last 20 lines", () => {
    const raw = ["나: 영화 볼래?", "상대: ㅇㅇ", "", "그냥 텍스트"].join("\n");
    expect(parseConversation(raw, ["나", "me"])).toEqual([
      { speaker: "me", text: "영화 볼래?" },
      { speaker: "them", text: "ㅇㅇ" },
      { speaker: "them", text: "그냥 텍스트" },
    ]);
    const many = Array.from({ length: 30 }, (_, i) => `me: ${i}`).join("\n");
    const turns = parseConversation(many, ["me"]);
    expect(turns).toHaveLength(20);
    expect(turns[0]?.text).toBe("10");
  });
});
