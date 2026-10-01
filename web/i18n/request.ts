import { cookies, headers } from "next/headers";
import { getRequestConfig } from "next-intl/server";

export const LOCALES = ["ko", "en", "ja"] as const;
export type Locale = (typeof LOCALES)[number];
export const DEFAULT_LOCALE: Locale = "ko";
export const LOCALE_COOKIE = "NEXT_LOCALE";

function isLocale(value: string | undefined): value is Locale {
  return value !== undefined && (LOCALES as readonly string[]).includes(value);
}

export function negotiateLocale(acceptLanguage: string | null): Locale {
  for (const part of (acceptLanguage ?? "").split(",")) {
    const tag = part.split(";")[0]?.trim().toLowerCase();
    const base = tag?.split("-")[0];
    if (isLocale(tag)) return tag;
    if (isLocale(base)) return base;
  }
  return DEFAULT_LOCALE;
}

// URL에 로케일을 넣지 않는다. OAuth Redirect URI를 로케일과 무관하게 고정하기 위해서다.
export default getRequestConfig(async () => {
  const cookieLocale = (await cookies()).get(LOCALE_COOKIE)?.value;
  const locale = isLocale(cookieLocale)
    ? cookieLocale
    : negotiateLocale((await headers()).get("accept-language"));

  const [common, auth, errors] = await Promise.all([
    import(`../locales/${locale}/common.json`),
    import(`../locales/${locale}/auth.json`),
    import(`../locales/${locale}/errors.json`),
  ]);
  return {
    locale,
    messages: { common: common.default, auth: auth.default, errors: errors.default },
  };
});
