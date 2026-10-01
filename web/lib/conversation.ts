import type { Turn } from "@/lib/api/types";

/** "나: ..." / "상대: ..." 형식의 붙여넣기를 화자별 턴으로 나눈다. 접두어가 없으면 상대 말로 본다. */
export function parseConversation(raw: string, mePrefixes: string[]): Turn[] {
  return raw
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .slice(-20)
    .map((line) => {
      const me = mePrefixes.find((p) => line.startsWith(`${p}:`));
      const text = line.replace(/^[^:]{1,10}:\s*/, "");
      return { speaker: me ? "me" : "them", text: text.slice(0, 500) } as Turn;
    });
}
