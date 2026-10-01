"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { AppShell, Card, ErrorNotice } from "@/components/AppShell";
import { LanguageSelector } from "@/components/Selectors";
import { ApiError, apiFetch } from "@/lib/api/client";
import type { ConsentListResponse, Lang, UserResponse } from "@/lib/api/types";
import { logout } from "@/lib/auth/login-flow";
import { setAccessToken } from "@/lib/auth/token-store";
import { clearHistory } from "@/lib/history-db";
import { useRequireUser } from "@/lib/hooks/useRequireUser";

const LOCALE_COOKIE = "NEXT_LOCALE";
const CONSENT_VERSION = "2026-10-01";

export default function SettingsPage() {
  const t = useTranslations("settings");
  const tp = useTranslations("auth.continueWith");
  const router = useRouter();
  const { user, reload } = useRequireUser();
  const [qualityLog, setQualityLog] = useState<boolean | null>(null);
  const [errorCode, setErrorCode] = useState<string | null>(null);

  useEffect(() => {
    if (!user) return;
    apiFetch<ConsentListResponse>("/auth/consents")
      .then((res) =>
        setQualityLog(
          res.consents.find((c) => c.type === "quality_log_collection")?.agreed ?? false,
        ),
      )
      .catch(() => setQualityLog(false));
  }, [user]);

  if (!user) return null;

  async function guard(action: () => Promise<void>) {
    setErrorCode(null);
    try {
      await action();
    } catch (err) {
      setErrorCode(err instanceof ApiError ? err.code : "INTERNAL_ERROR");
    }
  }

  async function changeUiLocale(locale: Lang) {
    await guard(async () => {
      await apiFetch<UserResponse>("/users/me", {
        method: "PATCH",
        body: JSON.stringify({ ui_locale: locale }),
      });
      document.cookie = `${LOCALE_COOKIE}=${locale}; path=/; max-age=31536000; samesite=lax`;
      await reload();
      router.refresh();
    });
  }

  async function changeTargetLang(lang: Lang) {
    await guard(async () => {
      await apiFetch<UserResponse>("/users/me", {
        method: "PATCH",
        body: JSON.stringify({ default_target_lang: lang }),
      });
      await reload();
    });
  }

  async function toggleQualityLog(agreed: boolean) {
    await guard(async () => {
      await apiFetch<UserResponse>("/auth/consents", {
        method: "POST",
        body: JSON.stringify({
          consents: [{ type: "quality_log_collection", version: CONSENT_VERSION, agreed }],
        }),
      });
      setQualityLog(agreed);
    });
  }

  async function withdraw() {
    if (!window.confirm(t("confirmDelete"))) return;
    await guard(async () => {
      await apiFetch<void>("/users/me", { method: "DELETE" });
      setAccessToken(null);
      await clearHistory().catch(() => undefined);
      router.replace("/login");
    });
  }

  return (
    <AppShell>
      <h1 className="mb-4 text-lg font-bold">{t("title")}</h1>
      <div className="flex flex-col gap-4">
        {errorCode && <ErrorNotice code={errorCode} />}
        <Card className="grid grid-cols-2 gap-3">
          <LanguageSelector
            value={user.ui_locale as Lang}
            onChange={changeUiLocale}
            label={t("uiLanguage")}
          />
          <LanguageSelector
            value={user.default_target_lang as Lang}
            onChange={changeTargetLang}
            label={t("targetLanguage")}
          />
        </Card>

        <Card>
          <label className="flex items-start justify-between gap-4 text-sm">
            <span>
              <span className="font-semibold">{t("qualityLog")}</span>
              <span className="mt-1 block text-xs text-neutral-500">{t("qualityLogHelp")}</span>
            </span>
            <input
              type="checkbox"
              role="switch"
              className="mt-1 size-5"
              disabled={qualityLog === null}
              checked={Boolean(qualityLog)}
              onChange={(e) => void toggleQualityLog(e.target.checked)}
            />
          </label>
        </Card>

        <Card className="text-sm">
          <h2 className="font-semibold">{t("linkedAccounts")}</h2>
          <ul className="mt-2 flex flex-col gap-1">
            {user.linked_providers.map((p) => (
              <li key={p}>{tp(p)}</li>
            ))}
          </ul>
          {user.email && (
            <p className="mt-2 text-xs text-neutral-500">
              {user.email}
              {user.is_private_email && ` (${t("privateEmail")})`}
            </p>
          )}
        </Card>

        <Card className="flex flex-col items-start gap-3 text-sm">
          <button
            type="button"
            onClick={async () => {
              await logout();
              router.replace("/login");
            }}
            className="underline"
          >
            {t("logout")}
          </button>
          <button type="button" onClick={withdraw} className="text-red-600 underline">
            {t("delete")}
          </button>
        </Card>
      </div>
    </AppShell>
  );
}
