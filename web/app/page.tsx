"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { apiFetch, refreshAccessToken } from "@/lib/api/client";
import { logout } from "@/lib/auth/login-flow";
import { getAccessToken } from "@/lib/auth/token-store";
import type { UserProfile } from "@/lib/auth/types";

type SessionState = { kind: "loading" } | { kind: "guest" } | { kind: "user"; user: UserProfile };

export default function HomePage() {
  const t = useTranslations("common");
  const router = useRouter();
  const [session, setSession] = useState<SessionState>({ kind: "loading" });

  useEffect(() => {
    (async () => {
      // 새로고침하면 메모리의 Access Token이 사라지므로 HttpOnly 쿠키로 재발급받는다.
      const token = getAccessToken() ?? (await refreshAccessToken());
      if (!token) return setSession({ kind: "guest" });
      try {
        const { user } = await apiFetch<{ user: UserProfile }>("/users/me");
        setSession({ kind: "user", user });
      } catch {
        setSession({ kind: "guest" });
      }
    })();
  }, []);

  async function handleLogout() {
    await logout();
    router.replace("/login");
  }

  return (
    <main className="mx-auto flex min-h-dvh max-w-md flex-col items-center justify-center gap-6 px-4 text-center">
      <h1 className="text-3xl font-bold">{t("appName")}</h1>
      {session.kind === "loading" && <p aria-live="polite">{t("loading")}</p>}
      {session.kind === "guest" && (
        <Link href="/login" className="h-11 rounded-xl bg-rose-500 px-6 leading-[2.75rem] font-semibold text-white">
          {t("goLogin")}
        </Link>
      )}
      {session.kind === "user" && (
        <>
          <p className="text-lg">{t("greeting", { name: session.user.display_name ?? t("guest") })}</p>
          <button type="button" onClick={handleLogout} className="text-sm text-neutral-500 underline">
            {t("logout")}
          </button>
        </>
      )}
    </main>
  );
}
