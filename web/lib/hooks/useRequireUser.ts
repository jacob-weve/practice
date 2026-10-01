"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { apiFetch, refreshAccessToken } from "@/lib/api/client";
import type { UserProfile, UserResponse } from "@/lib/api/types";
import { getAccessToken } from "@/lib/auth/token-store";

/** 로그인·동의를 마친 사용자만 화면을 보게 한다. 아니면 /login으로 보낸다. */
export function useRequireUser() {
  const router = useRouter();
  const [user, setUser] = useState<UserProfile | null>(null);

  const load = useCallback(async () => {
    // 새로고침하면 메모리의 Access Token이 사라지므로 HttpOnly 쿠키로 재발급받는다.
    const token = getAccessToken() ?? (await refreshAccessToken());
    if (!token) {
      router.replace("/login");
      return;
    }
    try {
      const res = await apiFetch<UserResponse>("/users/me");
      if (res.user.status !== "active") {
        router.replace("/login");
        return;
      }
      setUser(res.user);
    } catch {
      router.replace("/login");
    }
  }, [router]);

  useEffect(() => {
    void load();
  }, [load]);

  return { user, reload: load };
}
