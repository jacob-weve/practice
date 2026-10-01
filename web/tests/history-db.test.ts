import "fake-indexeddb/auto";
import { beforeEach, describe, expect, it } from "vitest";
import {
  HISTORY_LIMIT,
  addHistory,
  clearHistory,
  deleteHistory,
  listHistory,
  setPinned,
} from "@/lib/history-db";

describe("history-db", () => {
  beforeEach(async () => {
    await clearHistory();
  });

  it("adds, lists newest first, pins and deletes", async () => {
    const a = await addHistory({ kind: "tone_transform", draft: "a", result: {} });
    await new Promise((r) => setTimeout(r, 2));
    const b = await addHistory({ kind: "reply_interpret", draft: "b", result: {} });
    expect((await listHistory()).map((h) => h.id)).toEqual([b.id, a.id]);

    await setPinned(a.id, true);
    expect((await listHistory()).find((h) => h.id === a.id)?.pinned).toBe(true);

    await deleteHistory(b.id);
    expect((await listHistory()).map((h) => h.id)).toEqual([a.id]);
  });

  it(`keeps at most ${HISTORY_LIMIT} items and never evicts pinned ones`, async () => {
    const first = await addHistory({ kind: "tone_transform", draft: "first", result: {} });
    await setPinned(first.id, true);
    for (let i = 0; i < HISTORY_LIMIT; i += 1) {
      await addHistory({ kind: "tone_transform", draft: String(i), result: {} });
    }
    const items = await listHistory();
    expect(items).toHaveLength(HISTORY_LIMIT);
    expect(items.some((h) => h.id === first.id)).toBe(true);
    expect(items.some((h) => h.draft === "0")).toBe(false);
  });
});
