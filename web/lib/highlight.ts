import type { RedFlagOut } from "@/lib/api/types";

export interface Segment {
  text: string;
  flag?: RedFlagOut;
}

/**
 * 서버 오프셋(UTF-16 code unit)으로 초안을 조각낸다. JavaScript 문자열 인덱스도 UTF-16이라
 * slice를 그대로 쓸 수 있다. 겹치거나 범위를 벗어난 항목은 건너뛴다.
 */
export function segmentDraft(draft: string, flags: RedFlagOut[]): Segment[] {
  const sorted = [...flags].sort((a, b) => a.start - b.start);
  const segments: Segment[] = [];
  let cursor = 0;
  for (const flag of sorted) {
    if (flag.start < cursor || flag.end > draft.length || flag.end <= flag.start) continue;
    if (draft.slice(flag.start, flag.end) !== flag.text) continue; // 초안이 바뀐 뒤의 오래된 결과
    if (flag.start > cursor) segments.push({ text: draft.slice(cursor, flag.start) });
    segments.push({ text: draft.slice(flag.start, flag.end), flag });
    cursor = flag.end;
  }
  if (cursor < draft.length) segments.push({ text: draft.slice(cursor) });
  return segments;
}
