"use client";

import { useRef, useState } from "react";
import { useTranslations } from "next-intl";

interface Props {
  onText: (text: string) => void;
}

/**
 * 스크린샷을 기기 안에서 OCR한다. 이미지는 서버로 보내지 않는다 (PRD F-TONE-02).
 * tesseract.js는 무겁기 때문에 버튼을 처음 쓸 때만 불러온다.
 */
export function ScreenshotOcrButton({ onText }: Props) {
  const t = useTranslations("tone.ocr");
  const inputRef = useRef<HTMLInputElement>(null);
  const [state, setState] = useState<"idle" | "working" | "error">("idle");

  async function handleFile(file: File) {
    setState("working");
    try {
      const { createWorker } = await import("tesseract.js");
      const worker = await createWorker(["kor", "eng", "jpn"]);
      try {
        const { data } = await worker.recognize(file);
        onText(data.text.trim());
        setState("idle");
      } finally {
        await worker.terminate();
      }
    } catch {
      setState("error");
    } finally {
      if (inputRef.current) inputRef.current.value = "";
    }
  }

  return (
    <div className="flex items-center gap-2">
      <input
        ref={inputRef}
        type="file"
        accept="image/*"
        className="sr-only"
        id="screenshot-input"
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) void handleFile(file);
        }}
      />
      <label
        htmlFor="screenshot-input"
        aria-disabled={state === "working"}
        className="cursor-pointer rounded-lg border border-neutral-300 px-3 py-1.5 text-xs dark:border-neutral-700"
      >
        {state === "working" ? t("working") : t("button")}
      </label>
      {state === "error" && (
        <span role="alert" className="text-xs text-red-600">
          {t("failed")}
        </span>
      )}
      <span className="text-xs text-neutral-500">{t("privacy")}</span>
    </div>
  );
}
