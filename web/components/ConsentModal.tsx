"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import type { ConsentDecision } from "@/lib/auth/login-flow";
import type { ConsentType, RequiredConsent } from "@/lib/api/types";

const OPTIONAL: ConsentType[] = ["marketing", "quality_log_collection"];

interface Props {
  required: RequiredConsent[];
  submitting: boolean;
  onSubmit: (decisions: ConsentDecision[]) => void;
}

export function ConsentModal({ required, submitting, onSubmit }: Props) {
  const t = useTranslations("auth.consent");
  const version = required[0]?.version ?? "";
  const items: { type: ConsentType; url: string | null; isRequired: boolean }[] = [
    ...required.map((c) => ({ type: c.type, url: c.url, isRequired: true })),
    ...OPTIONAL.map((type) => ({ type, url: null, isRequired: false })),
  ];
  const [checked, setChecked] = useState<Record<string, boolean>>({});

  const allChecked = items.every((item) => checked[item.type]);
  const requiredChecked = items.filter((i) => i.isRequired).every((i) => checked[i.type]);

  function toggleAll() {
    const next = !allChecked;
    setChecked(Object.fromEntries(items.map((i) => [i.type, next])));
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="consent-title"
      className="fixed inset-0 z-50 flex items-end justify-center bg-black/40 sm:items-center"
    >
      <div className="w-full max-w-md rounded-t-2xl bg-white p-6 sm:rounded-2xl dark:bg-neutral-900">
        <h2 id="consent-title" className="text-xl font-bold">
          {t("title")}
        </h2>
        <p className="mt-1 text-sm text-neutral-500">{t("description")}</p>

        <label className="mt-5 flex items-center gap-3 border-b pb-3 font-semibold">
          <input type="checkbox" checked={allChecked} onChange={toggleAll} className="size-5" />
          {t("all")}
        </label>
        <ul className="mt-3 flex flex-col gap-3">
          {items.map((item) => (
            <li key={item.type} className="flex items-center justify-between gap-3">
              <label className="flex items-center gap-3 text-sm">
                <input
                  type="checkbox"
                  className="size-5"
                  checked={Boolean(checked[item.type])}
                  onChange={(e) => setChecked({ ...checked, [item.type]: e.target.checked })}
                />
                {t(item.type)}
              </label>
              {item.url && (
                <a
                  href={item.url}
                  target="_blank"
                  rel="noreferrer"
                  className="text-xs text-neutral-500 underline"
                >
                  {t("view")}
                </a>
              )}
            </li>
          ))}
        </ul>

        <button
          type="button"
          disabled={!requiredChecked || submitting}
          onClick={() =>
            onSubmit(
              items.map((i) => ({ type: i.type, version, agreed: Boolean(checked[i.type]) })),
            )
          }
          className="mt-6 h-12 w-full rounded-xl bg-rose-500 font-semibold text-white disabled:opacity-40"
        >
          {t("submit")}
        </button>
      </div>
    </div>
  );
}
