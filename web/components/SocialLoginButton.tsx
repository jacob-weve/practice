"use client";

import { useTranslations } from "next-intl";
import type { Provider } from "@/lib/config";

// 각 제공자 브랜드 가이드라인의 기본 색상. 로고 에셋은 공식 배포본으로 교체한다(PLAN Step 7).
const STYLES: Record<Provider, string> = {
  kakao: "bg-[#FEE500] text-black/85",
  google: "border border-neutral-300 bg-white text-neutral-800",
  naver: "bg-[#03C75A] text-white",
  apple: "bg-black text-white dark:bg-white dark:text-black",
};

interface Props {
  provider: Provider;
  disabled?: boolean;
  onClick: (provider: Provider) => void;
}

export function SocialLoginButton({ provider, disabled, onClick }: Props) {
  const t = useTranslations("auth.continueWith");
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={() => onClick(provider)}
      className={`h-12 w-full rounded-xl text-[15px] font-semibold transition-opacity disabled:opacity-50 ${STYLES[provider]}`}
    >
      {t(provider)}
    </button>
  );
}
