"use client";

import { useTranslations } from "next-intl";
import type { Lang, PersonaOut, Relation } from "@/lib/api/types";

export const RELATIONS: Relation[] = [
  "work_superior",
  "work_peer",
  "client",
  "partner",
  "family",
  "friend",
  "acquaintance",
];
export const LANGS: Lang[] = ["ko", "en", "ja"];

export function PersonaSelector({
  personas,
  value,
  onChange,
}: {
  personas: PersonaOut[];
  value: string;
  onChange: (key: string) => void;
}) {
  const t = useTranslations("tone");
  return (
    <fieldset>
      <legend className="mb-2 text-sm font-semibold">{t("persona")}</legend>
      <div className="flex flex-wrap gap-2">
        {personas.map((p) => (
          <label
            key={p.key}
            title={p.description}
            className={`cursor-pointer rounded-full border px-3 py-1.5 text-sm transition-colors has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-rose-400 ${
              value === p.key
                ? "border-rose-500 bg-rose-500 text-white"
                : "border-neutral-300 dark:border-neutral-700"
            }`}
          >
            <input
              type="radio"
              name="persona"
              value={p.key}
              checked={value === p.key}
              onChange={() => onChange(p.key)}
              className="sr-only"
            />
            {p.display_name}
          </label>
        ))}
      </div>
    </fieldset>
  );
}

export function RelationSelector({
  value,
  onChange,
}: {
  value: Relation;
  onChange: (value: Relation) => void;
}) {
  const t = useTranslations("tone");
  return (
    <label className="flex flex-col gap-1 text-sm">
      <span className="font-semibold">{t("relation")}</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value as Relation)}
        className="h-10 rounded-lg border border-neutral-300 bg-transparent px-2 dark:border-neutral-700"
      >
        {RELATIONS.map((r) => (
          <option key={r} value={r}>
            {t(`relations.${r}`)}
          </option>
        ))}
      </select>
    </label>
  );
}

export function LanguageSelector({
  value,
  onChange,
  label,
}: {
  value: Lang;
  onChange: (value: Lang) => void;
  label: string;
}) {
  const t = useTranslations("common.languages");
  return (
    <label className="flex flex-col gap-1 text-sm">
      <span className="font-semibold">{label}</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value as Lang)}
        className="h-10 rounded-lg border border-neutral-300 bg-transparent px-2 dark:border-neutral-700"
      >
        {LANGS.map((l) => (
          <option key={l} value={l}>
            {t(l)}
          </option>
        ))}
      </select>
    </label>
  );
}
