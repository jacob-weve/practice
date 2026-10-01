"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTranslations } from "next-intl";

const NAV = [
  { href: "/transform", key: "transform" },
  { href: "/interpret", key: "interpret" },
  { href: "/history", key: "history" },
  { href: "/settings", key: "settings" },
] as const;

export function AppShell({ children }: { children: React.ReactNode }) {
  const t = useTranslations();
  const pathname = usePathname();
  return (
    <div className="mx-auto flex min-h-dvh max-w-2xl flex-col px-4">
      <header className="flex items-center justify-between py-4">
        <Link href="/transform" className="text-lg font-bold text-rose-600 dark:text-rose-400">
          {t("common.appName")}
        </Link>
        <nav aria-label={t("nav.label")}>
          <ul className="flex gap-1 text-sm">
            {NAV.map((item) => {
              const active = pathname.startsWith(item.href);
              return (
                <li key={item.href}>
                  <Link
                    href={item.href}
                    aria-current={active ? "page" : undefined}
                    className={`rounded-lg px-3 py-2 ${
                      active
                        ? "bg-rose-100 font-semibold text-rose-700 dark:bg-rose-900/40 dark:text-rose-200"
                        : "text-neutral-600 hover:bg-neutral-100 dark:text-neutral-300 dark:hover:bg-neutral-800"
                    }`}
                  >
                    {t(`nav.${item.key}`)}
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>
      </header>
      <main className="flex-1 pb-16">{children}</main>
    </div>
  );
}

export function Card({
  children,
  className = "",
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section
      className={`rounded-2xl border border-neutral-200 bg-white p-4 shadow-sm dark:border-neutral-800 dark:bg-neutral-900 ${className}`}
    >
      {children}
    </section>
  );
}

export function ErrorNotice({ code }: { code: string }) {
  const t = useTranslations("errors");
  return (
    <p
      role="alert"
      className="rounded-xl bg-red-50 p-3 text-sm text-red-700 dark:bg-red-950/50 dark:text-red-300"
    >
      {t.has(code) ? t(code) : t("INTERNAL_ERROR")}
    </p>
  );
}
