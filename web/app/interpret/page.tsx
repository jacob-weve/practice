"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { AppShell, Card, ErrorNotice } from "@/components/AppShell";
import { EmotionThermometer } from "@/components/EmotionThermometer";
import { RelationSelector } from "@/components/Selectors";
import { VariantCard } from "@/components/VariantCard";
import type { Relation } from "@/lib/api/types";
import { parseConversation } from "@/lib/conversation";
import { useReplyInterpret } from "@/lib/hooks/useReplyInterpret";
import { useRequireUser } from "@/lib/hooks/useRequireUser";

export default function InterpretPage() {
  const t = useTranslations("interpret");
  const { user } = useRequireUser();
  const { state, run } = useReplyInterpret();
  const [message, setMessage] = useState("");
  const [conversation, setConversation] = useState("");
  const [concern, setConcern] = useState("");
  const [relation, setRelation] = useState<Relation>("partner");

  if (!user) return null;
  const busy = state.status === "streaming";

  function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!message.trim()) return;
    void run({
      message,
      conversation: parseConversation(conversation, t("mePrefixes").split(",")),
      relation,
      my_concern: concern.trim() || null,
      target_lang: (user?.default_target_lang as "ko" | "en" | "ja") ?? "ko",
    });
  }

  return (
    <AppShell>
      <form onSubmit={submit} className="flex flex-col gap-4">
        <Card className="flex flex-col gap-3">
          <label htmlFor="message" className="text-sm font-semibold">
            {t("message")}
          </label>
          <textarea
            id="message"
            required
            maxLength={1000}
            rows={2}
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            placeholder={t("messagePlaceholder")}
            className="rounded-xl border border-neutral-300 bg-transparent p-3 dark:border-neutral-700"
          />
          <label htmlFor="conversation" className="text-sm font-semibold">
            {t("conversation")}
          </label>
          <textarea
            id="conversation"
            rows={4}
            maxLength={3000}
            value={conversation}
            onChange={(e) => setConversation(e.target.value)}
            placeholder={t("conversationPlaceholder")}
            className="rounded-xl border border-neutral-300 bg-transparent p-3 dark:border-neutral-700"
          />
          <label htmlFor="concern" className="text-sm font-semibold">
            {t("concern")}
          </label>
          <input
            id="concern"
            maxLength={300}
            value={concern}
            onChange={(e) => setConcern(e.target.value)}
            placeholder={t("concernPlaceholder")}
            className="h-10 rounded-xl border border-neutral-300 bg-transparent px-3 dark:border-neutral-700"
          />
          <RelationSelector value={relation} onChange={setRelation} />
        </Card>
        <button
          type="submit"
          disabled={busy || !message.trim()}
          className="h-12 rounded-xl bg-rose-500 font-semibold text-white disabled:opacity-40"
        >
          {busy ? t("working") : t("submit")}
        </button>
      </form>

      <section aria-live="polite" className="mt-6 flex flex-col gap-4">
        {state.status === "error" && state.errorCode && <ErrorNotice code={state.errorCode} />}
        {state.emotion && (
          <Card>
            <EmotionThermometer emotion={state.emotion} />
          </Card>
        )}
        {state.interpretations.length > 0 && (
          <Card className="flex flex-col gap-3">
            <h2 className="text-sm font-semibold">{t("interpretations")}</h2>
            {state.interpretations.map((item, i) => (
              <div key={i}>
                <div className="flex items-center justify-between text-sm">
                  <p>{item.summary}</p>
                  <span className="text-neutral-500 tabular-nums">
                    {Math.round(item.likelihood * 100)}%
                  </span>
                </div>
                <div className="mt-1 h-1.5 rounded-full bg-neutral-200 dark:bg-neutral-800">
                  <div
                    className="h-full rounded-full bg-rose-400"
                    style={{ width: `${Math.round(item.likelihood * 100)}%` }}
                  />
                </div>
                <p className="mt-1 text-xs text-neutral-500">{item.signals.join(" · ")}</p>
              </div>
            ))}
          </Card>
        )}
        {state.guide && (
          <Card className="flex flex-col gap-2 text-sm">
            <h2 className="font-semibold">{t("guide")}</h2>
            <p>{state.guide.summary}</p>
            {state.guide.overthinking_warning && (
              <p className="rounded-lg bg-amber-50 p-2 text-amber-800 dark:bg-amber-950/40 dark:text-amber-300">
                {t("overthinking")}
              </p>
            )}
            {state.guide.avoid.length > 0 && (
              <p className="text-neutral-600 dark:text-neutral-400">
                {t("avoid")}: {state.guide.avoid.join(", ")}
              </p>
            )}
            {state.guide.check_points.length > 0 && (
              <p className="text-neutral-600 dark:text-neutral-400">
                {t("checkPoints")}: {state.guide.check_points.join(", ")}
              </p>
            )}
          </Card>
        )}
        {state.replies.map((reply) => (
          <VariantCard
            key={reply.style}
            kind={reply.style}
            title={t(`style.${reply.style}`)}
            text={reply.text}
            note={reply.rationale}
            requestId={state.requestId}
          />
        ))}
        {state.disclaimer && (
          <p className="text-center text-xs text-neutral-500">{state.disclaimer}</p>
        )}
      </section>
    </AppShell>
  );
}
