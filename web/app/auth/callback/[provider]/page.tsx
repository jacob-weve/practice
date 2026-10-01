"use client";

import { useEffect, useRef, useState } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { ConsentModal } from "@/components/ConsentModal";
import { ApiError } from "@/lib/api/client";
import { completeLogin, submitConsents, type ConsentDecision } from "@/lib/auth/login-flow";
import type { RequiredConsent } from "@/lib/auth/types";
import { isProvider } from "@/lib/config";

export default function OAuthCallbackPage() {
  const t = useTranslations();
  const router = useRouter();
  const { provider } = useParams<{ provider: string }>();
  const searchParams = useSearchParams();
  const started = useRef(false);
  const [errorCode, setErrorCode] = useState<string | null>(null);
  const [required, setRequired] = useState<RequiredConsent[] | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    // 인가 코드와 state는 1회용이므로 StrictMode의 이중 실행에서도 한 번만 보낸다.
    if (started.current) return;
    started.current = true;
    if (!isProvider(provider)) {
      setErrorCode("AUTH_UNSUPPORTED_PROVIDER");
      return;
    }
    const params = new URLSearchParams(searchParams.toString());
    // 인가 코드가 주소창·방문 기록에 남지 않도록 바로 지운다.
    window.history.replaceState(null, "", window.location.pathname);
    completeLogin(provider, params)
      .then((res) => {
        if (res.user.status === "pending_consent") setRequired(res.required_consents);
        else router.replace("/");
      })
      .catch((err: unknown) => {
        setErrorCode(err instanceof ApiError ? err.code : "INTERNAL_ERROR");
      });
  }, [provider, router, searchParams]);

  async function handleConsents(decisions: ConsentDecision[]) {
    setSubmitting(true);
    try {
      await submitConsents(decisions);
      router.replace("/");
    } catch (err) {
      setErrorCode(err instanceof ApiError ? err.code : "INTERNAL_ERROR");
      setSubmitting(false);
    }
  }

  return (
    <main className="mx-auto flex min-h-dvh max-w-sm flex-col items-center justify-center gap-4 px-4 text-center">
      {errorCode ? (
        <>
          <p role="alert" className="font-semibold">
            {t("auth.failed")}
          </p>
          <p className="text-sm text-neutral-500">{t(`errors.${errorCode}`)}</p>
          <button
            type="button"
            onClick={() => router.replace("/login")}
            className="h-11 rounded-xl bg-rose-500 px-6 font-semibold text-white"
          >
            {t("auth.retry")}
          </button>
        </>
      ) : (
        <p aria-live="polite">{t("auth.processing")}</p>
      )}
      {required && !errorCode && (
        <ConsentModal required={required} submitting={submitting} onSubmit={handleConsents} />
      )}
    </main>
  );
}
