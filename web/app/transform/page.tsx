"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { AppShell, Card, ErrorNotice } from "@/components/AppShell";
import { EmotionThermometer } from "@/components/EmotionThermometer";
import { RedFlagPreview } from "@/components/RedFlagPreview";
import { ScreenshotOcrButton } from "@/components/ScreenshotOcrButton";
import { LanguageSelector, PersonaSelector, RelationSelector } from "@/components/Selectors";
import { VariantCard } from "@/components/VariantCard";
import { apiFetch } from "@/lib/api/client";
import type {
  Lang,
  Persona,
  PersonaOut,
  RedFlagOut,
  Relation,
  ToneOptionsResponse,
} from "@/lib/api/types";
import { useRequireUser } from "@/lib/hooks/useRequireUser";
import { useToneTransform } from "@/lib/hooks/useToneTransform";

const CONTEXT_LIMIT = 2000;
const DRAFT_LIMIT = 1000;

export default function TransformPage() {
  const t = useTranslations("tone");
  const { user } = useRequireUser();
  const { state, run, cancel } = useToneTransform();
  const [personas, setPersonas] = useState<PersonaOut[]>([]);
  const [context, setContext] = useState("");
  const [draft, setDraft] = useState("");
  const [submittedDraft, setSubmittedDraft] = useState("");
  const [persona, setPersona] = useState<Persona>("polite");
  const [relation, setRelation] = useState<Relation>("work_superior");
  const [targetLang, setTargetLang] = useState<Lang>("ko");
  const [focusedTemp, setFocusedTemp] = useState<number | undefined>();

  useEffect(() => {
    if (!user) return;
    setTargetLang((user.default_target_lang as Lang) ?? "ko");
    apiFetch<ToneOptionsResponse>("/tone/options")
      .then((res) => setPersonas(res.personas))
      .catch(() => setPersonas([]));
  }, [user]);

  function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!draft.trim()) return;
    setSubmittedDraft(draft);
    setFocusedTemp(undefined);
    void run({
      context: context.trim() || null,
      draft,
      persona,
      relation,
      target_lang: targetLang,
    });
  }

  function applySuggestion(flag: RedFlagOut) {
    // 서버 오프셋은 UTF-16 기준이라 JavaScript slice와 그대로 맞는다.
    if (draft.slice(flag.start, flag.end) !== flag.text) return;
    setDraft(draft.slice(0, flag.start) + flag.suggestion + draft.slice(flag.end));
  }

  if (!user) return null;
  const busy = state.status === "streaming";

  return (
    <AppShell>
      <form onSubmit={submit} className="flex flex-col gap-4">
        <Card className="flex flex-col gap-3">
          <div className="flex items-center justify-between">
            <label htmlFor="context" className="text-sm font-semibold">
              {t("context")}
            </label>
            <ScreenshotOcrButton onText={(text) => setContext(text.slice(0, CONTEXT_LIMIT))} />
          </div>
          <textarea
            id="context"
            value={context}
            maxLength={CONTEXT_LIMIT}
            onChange={(e) => setContext(e.target.value)}
            placeholder={t("contextPlaceholder")}
            rows={3}
            className="resize-y rounded-xl border border-neutral-300 bg-transparent p-3 dark:border-neutral-700"
          />
          <label htmlFor="draft" className="text-sm font-semibold">
            {t("draft")}
          </label>
          <textarea
            id="draft"
            value={draft}
            maxLength={DRAFT_LIMIT}
            required
            onChange={(e) => setDraft(e.target.value)}
            placeholder={t("draftPlaceholder")}
            rows={4}
            className="resize-y rounded-xl border border-neutral-300 bg-transparent p-3 dark:border-neutral-700"
          />
          <p className="text-right text-xs text-neutral-500 tabular-nums">
            {draft.length}/{DRAFT_LIMIT}
          </p>
        </Card>

        <Card className="flex flex-col gap-4">
          <PersonaSelector
            personas={personas}
            value={persona}
            onChange={(k) => setPersona(k as Persona)}
          />
          <div className="grid grid-cols-2 gap-3">
            <RelationSelector value={relation} onChange={setRelation} />
            <LanguageSelector value={targetLang} onChange={setTargetLang} label={t("targetLang")} />
          </div>
        </Card>

        <div className="flex gap-2">
          <button
            type="submit"
            disabled={busy || !draft.trim()}
            className="h-12 flex-1 rounded-xl bg-rose-500 font-semibold text-white disabled:opacity-40"
          >
            {busy ? t("working") : t("submit")}
          </button>
          {busy && (
            <button
              type="button"
              onClick={cancel}
              className="h-12 rounded-xl border border-neutral-300 px-4 dark:border-neutral-700"
            >
              {t("cancel")}
            </button>
          )}
        </div>
      </form>

      <section aria-live="polite" className="mt-6 flex flex-col gap-4">
        {state.status === "error" && state.errorCode && <ErrorNotice code={state.errorCode} />}
        {state.emotion && (
          <Card>
            <EmotionThermometer emotion={state.emotion} after={focusedTemp} />
          </Card>
        )}
        {state.status !== "idle" && state.emotion && (
          <Card>
            <h2 className="mb-3 text-sm font-semibold">{t("redFlags.title")}</h2>
            <RedFlagPreview
              draft={submittedDraft}
              flags={state.redFlags}
              onApply={applySuggestion}
            />
          </Card>
        )}
        {state.variants.map((v) => (
          <VariantCard
            key={v.index}
            kind={v.kind}
            title={t(`variant.${v.kind}`)}
            text={v.text}
            note={v.rationale}
            meta={`${v.expected_temperature}°C`}
            requestId={state.requestId}
            onFocus={() => setFocusedTemp(v.expected_temperature)}
          />
        ))}
      </section>
    </AppShell>
  );
}
