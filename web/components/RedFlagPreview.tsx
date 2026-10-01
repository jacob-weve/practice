"use client";

import { useTranslations } from "next-intl";
import type { RedFlagOut } from "@/lib/api/types";
import { segmentDraft } from "@/lib/highlight";

const SEVERITY: Record<RedFlagOut["severity"], string> = {
  low: "decoration-amber-400 bg-amber-100/60 dark:bg-amber-900/30",
  medium: "decoration-orange-500 bg-orange-100/70 dark:bg-orange-900/40",
  high: "decoration-red-500 bg-red-100/80 dark:bg-red-900/40",
};

interface Props {
  draft: string;
  flags: RedFlagOut[];
  onApply: (flag: RedFlagOut) => void;
}

/** 초안 위에 오해를 부를 수 있는 표현을 표시하고, 표현마다 대체 문구를 적용할 수 있게 한다. */
export function RedFlagPreview({ draft, flags, onApply }: Props) {
  const t = useTranslations("tone.redFlags");
  const segments = segmentDraft(draft, flags);
  const shown = segments.filter((s) => s.flag);
  if (shown.length === 0) {
    return <p className="text-sm text-neutral-500">{t("none")}</p>;
  }
  return (
    <div className="flex flex-col gap-3">
      <p className="rounded-xl bg-neutral-50 p-3 leading-7 whitespace-pre-wrap dark:bg-neutral-950">
        {segments.map((segment, i) =>
          segment.flag ? (
            <mark
              key={i}
              className={`rounded px-0.5 text-inherit underline decoration-2 underline-offset-4 ${SEVERITY[segment.flag.severity]}`}
              title={segment.flag.reason}
            >
              {segment.text}
            </mark>
          ) : (
            <span key={i}>{segment.text}</span>
          ),
        )}
      </p>
      <ul className="flex flex-col gap-2">
        {shown.map(({ flag }) =>
          flag ? (
            <li
              key={`${flag.start}-${flag.end}`}
              className="rounded-xl border border-neutral-200 p-3 text-sm dark:border-neutral-800"
            >
              <p>
                <span className="font-semibold">“{flag.text}”</span>{" "}
                <span className="text-xs text-neutral-500">
                  {t(`type.${flag.type}`)} · {t(`severity.${flag.severity}`)}
                </span>
              </p>
              <p className="mt-1 text-neutral-600 dark:text-neutral-400">{flag.reason}</p>
              <div className="mt-2 flex items-center justify-between gap-2">
                <p className="text-emerald-700 dark:text-emerald-400">→ {flag.suggestion}</p>
                <button
                  type="button"
                  onClick={() => onApply(flag)}
                  className="shrink-0 rounded-lg border border-neutral-300 px-2 py-1 text-xs dark:border-neutral-700"
                >
                  {t("apply")}
                </button>
              </div>
            </li>
          ) : null,
        )}
      </ul>
    </div>
  );
}
