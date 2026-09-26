"use client";

import { useQuery } from "@tanstack/react-query";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";
import { Skeleton } from "@/components/ui/misc";
import { api, ApiError, AUTH_EXPIRED_EVENT } from "@/lib/api";
import type { Me } from "@/lib/types";

/** Guarda de autenticação: sem sessão válida, vai para /login preservando o destino. */
export default function AppLayout({ children }: { children: ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const me = useQuery({ queryKey: ["me"], queryFn: () => api.get<Me>("/auth/me"), retry: false, staleTime: 60_000 });

  useEffect(() => {
    const toLogin = () => router.replace(`/login?next=${encodeURIComponent(pathname)}`);
    window.addEventListener(AUTH_EXPIRED_EVENT, toLogin);
    if (me.error instanceof ApiError && me.error.status === 401) toLogin();
    return () => window.removeEventListener(AUTH_EXPIRED_EVENT, toLogin);
  }, [me.error, pathname, router]);

  if (me.isLoading || me.error) {
    return (
      <main id="main" className="mx-auto max-w-5xl space-y-4 p-8" aria-busy="true">
        <Skeleton className="h-10 w-64" />
        <Skeleton className="h-40 w-full" />
        <Skeleton className="h-40 w-full" />
      </main>
    );
  }
  return <>{children}</>;
}
