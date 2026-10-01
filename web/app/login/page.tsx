"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { SocialLoginButton } from "@/components/SocialLoginButton";
import { ApiError } from "@/lib/api/client";
import { startLogin } from "@/lib/auth/login-flow";
import { PROVIDERS, type Provider } from "@/lib/config";

export default function LoginPage() {
  const t = useTranslations();
  const [busy, setBusy] = useState(false);
  const [errorCode, setErrorCode] = useState<string | null>(null);

  async function handleLogin(provider: Provider) {
    setBusy(true);
    setErrorCode(null);
    try {
      await startLogin(provider);
    } catch (err) {
      setErrorCode(err instanceof ApiError ? err.code : "INTERNAL_ERROR");
      setBusy(false);
    }
  }

  return (
    <main className="mx-auto flex min-h-dvh max-w-sm flex-col justify-center gap-8 px-4">
      <header className="text-center">
        <h1 className="text-3xl font-bold">{t("common.appName")}</h1>
        <p className="mt-2 text-neutral-500">{t("common.tagline")}</p>
      </header>
      <section className="flex flex-col gap-3" aria-label={t("auth.title")}>
        {PROVIDERS.map((provider) => (
          <SocialLoginButton
            key={provider}
            provider={provider}
            disabled={busy}
            onClick={handleLogin}
          />
        ))}
      </section>
      {errorCode && (
        <p role="alert" className="text-center text-sm text-red-600">
          {t(`errors.${errorCode}`)}
        </p>
      )}
    </main>
  );
}
