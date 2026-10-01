"use client";

import { useTranslations } from "next-intl";
import type { EmotionOut } from "@/lib/api/types";

const ZONE_COLOR: Record<EmotionOut["zone"], string> = {
  cold: "bg-sky-500",
  calm: "bg-emerald-500",
  warning: "bg-amber-500",
  danger: "bg-red-500",
};

interface Props {
  emotion: EmotionOut;
  /** 변환 후 예상 온도 (선택한 문장의 expected_temperature) */
  after?: number;
}

export function EmotionThermometer({ emotion, after }: Props) {
  const t = useTranslations("tone.thermometer");
  const temp = Math.min(100, Math.max(0, emotion.temperature));
  return (
    <figure aria-label={t("label")} className="flex flex-col gap-2">
      <div className="flex items-baseline justify-between">
        <figcaption className="text-sm font-semibold">{t("label")}</figcaption>
        <p className="text-sm">
          <span className="text-2xl font-bold tabular-nums">{temp}°C</span>{" "}
          <span className="text-neutral-500">{t(`zone.${emotion.zone}`)}</span>
          {after !== undefined && (
            <span className="ml-2 text-emerald-600 dark:text-emerald-400">→ {after}°C</span>
          )}
        </p>
      </div>
      <div
        role="meter"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={temp}
        aria-valuetext={`${temp}°C ${t(`zone.${emotion.zone}`)}`}
        className="relative h-3 overflow-hidden rounded-full bg-neutral-200 dark:bg-neutral-800"
      >
        <div
          className={`h-full rounded-full transition-[width] duration-700 ${ZONE_COLOR[emotion.zone]}`}
          style={{ width: `${temp}%` }}
        />
        {after !== undefined && (
          <div
            aria-hidden
            className="absolute top-0 h-full w-0.5 bg-neutral-900 dark:bg-white"
            style={{ left: `${Math.min(100, Math.max(0, after))}%` }}
          />
        )}
      </div>
      {emotion.labels.length > 0 && (
        <ul className="flex flex-wrap gap-2 text-xs">
          {emotion.labels.map((label) => (
            <li
              key={label.name}
              className="rounded-full bg-neutral-100 px-2 py-1 dark:bg-neutral-800"
            >
              {t(`emotion.${label.name}`)} {Math.round(label.score * 100)}%
            </li>
          ))}
        </ul>
      )}
    </figure>
  );
}
