"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import type { FeedbackRequest } from "@/lib/api/types";
import { copyText, sendFeedback, shareText } from "@/lib/feedback";

type VariantKind = NonNullable<FeedbackRequest["variant_kind"]>;

interface Props {
  kind: VariantKind;
  title: string;
  text: string;
  note?: string | null;
  meta?: string;
  requestId?: string;
  onFocus?: () => void;
}

export function VariantCard({ kind, title, text, note, meta, requestId, onFocus }: Props) {
  const t = useTranslations("common");
  const [copied, setCopied] = useState(false);

  async function handle(action: "copied" | "shared") {
    const ok = action === "copied" ? await copyText(text) : await shareText(text);
    if (!ok) return;
    if (action === "copied") {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    }
    if (requestId) sendFeedback({ request_id: requestId, action, variant_kind: kind });
  }

  return (
    <article
      onMouseEnter={onFocus}
      onFocus={onFocus}
      className="animate-[fadein_300ms_ease-out] rounded-2xl border border-neutral-200 bg-white p-4 dark:border-neutral-800 dark:bg-neutral-900"
    >
      <header className="flex items-center justify-between text-xs text-neutral-500">
        <span className="font-semibold text-rose-600 dark:text-rose-400">{title}</span>
        {meta && <span className="tabular-nums">{meta}</span>}
      </header>
      <p className="mt-2 leading-7 whitespace-pre-wrap">{text}</p>
      {note && <p className="mt-2 text-xs text-neutral-500">{note}</p>}
      <div className="mt-3 flex gap-2">
        <button
          type="button"
          onClick={() => handle("copied")}
          className="h-9 rounded-lg bg-rose-500 px-3 text-sm font-semibold text-white"
        >
          {copied ? t("copied") : t("copy")}
        </button>
        <button
          type="button"
          onClick={() => handle("shared")}
          className="h-9 rounded-lg border border-neutral-300 px-3 text-sm dark:border-neutral-700"
        >
          {t("share")}
        </button>
      </div>
    </article>
  );
}
