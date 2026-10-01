"use client";

import { useCallback, useEffect, useState } from "react";
import { useFormatter, useTranslations } from "next-intl";
import { AppShell, Card } from "@/components/AppShell";
import type { TransformState } from "@/lib/hooks/useToneTransform";
import type { InterpretState } from "@/lib/hooks/useReplyInterpret";
import { useRequireUser } from "@/lib/hooks/useRequireUser";
import {
  clearHistory,
  deleteHistory,
  listHistory,
  setPinned,
  type HistoryItem,
} from "@/lib/history-db";
import { copyText } from "@/lib/feedback";

function firstResult(item: HistoryItem): string {
  if (item.kind === "tone_transform") {
    return (item.result as TransformState).variants?.[0]?.text ?? "";
  }
  return (item.result as InterpretState).replies?.[0]?.text ?? "";
}

export default function HistoryPage() {
  const t = useTranslations("history");
  const format = useFormatter();
  const { user } = useRequireUser();
  const [items, setItems] = useState<HistoryItem[] | null>(null);
  const [unavailable, setUnavailable] = useState(false);

  const load = useCallback(async () => {
    try {
      setItems(await listHistory());
    } catch {
      setUnavailable(true);
      setItems([]);
    }
  }, []);

  useEffect(() => {
    if (user) void load();
  }, [user, load]);

  if (!user || items === null) return null;

  return (
    <AppShell>
      <div className="mb-4 flex items-center justify-between">
        <h1 className="text-lg font-bold">{t("title")}</h1>
        {items.length > 0 && (
          <button
            type="button"
            onClick={async () => {
              if (!window.confirm(t("confirmClear"))) return;
              await clearHistory();
              await load();
            }}
            className="text-sm text-red-600 underline"
          >
            {t("clear")}
          </button>
        )}
      </div>
      <p className="mb-4 text-xs text-neutral-500">{t("localOnly")}</p>
      {unavailable && <p className="text-sm text-neutral-500">{t("unavailable")}</p>}
      {items.length === 0 && !unavailable && (
        <p className="text-sm text-neutral-500">{t("empty")}</p>
      )}
      <ul className="flex flex-col gap-3">
        {items.map((item) => (
          <li key={item.id}>
            <Card className="flex flex-col gap-2 text-sm">
              <div className="flex items-center justify-between text-xs text-neutral-500">
                <span>
                  {t(`kind.${item.kind}`)} ·{" "}
                  {format.dateTime(new Date(item.createdAt), {
                    dateStyle: "medium",
                    timeStyle: "short",
                  })}
                </span>
                <div className="flex gap-3">
                  <button
                    type="button"
                    onClick={async () => {
                      await setPinned(item.id, !item.pinned);
                      await load();
                    }}
                  >
                    {item.pinned ? t("unpin") : t("pin")}
                  </button>
                  <button
                    type="button"
                    onClick={async () => {
                      await deleteHistory(item.id);
                      await load();
                    }}
                  >
                    {t("delete")}
                  </button>
                </div>
              </div>
              {item.draft && (
                <p className="text-neutral-500 line-through decoration-neutral-300">{item.draft}</p>
              )}
              <p className="whitespace-pre-wrap">{firstResult(item)}</p>
              <button
                type="button"
                onClick={() => void copyText(firstResult(item))}
                className="self-start rounded-lg border border-neutral-300 px-2 py-1 text-xs dark:border-neutral-700"
              >
                {t("copy")}
              </button>
            </Card>
          </li>
        ))}
      </ul>
    </AppShell>
  );
}
