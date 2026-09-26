"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { FileText, History, LayoutDashboard, Layers, LogOut, User } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import type { ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { ActionMenu } from "@/components/ui/menu";
import { api } from "@/lib/api";
import type { Me } from "@/lib/types";
import { APP_NAME, cn } from "@/lib/utils";

export function useMe() {
  return useQuery({ queryKey: ["me"], queryFn: () => api.get<Me>("/auth/me"), staleTime: 60_000 });
}

const NAV = [
  { href: "/dashboard", label: "Painel", icon: LayoutDashboard },
  { href: "/kits", label: "Kits", icon: Layers },
  { href: "/history", label: "Histórico", icon: History },
];

export function AppShell({ children, wide }: { children: ReactNode; wide?: boolean }) {
  const pathname = usePathname();
  const router = useRouter();
  const qc = useQueryClient();
  const me = useMe().data;

  async function logout() {
    await api.post("/auth/logout").catch(() => undefined);
    qc.clear();
    router.replace("/login");
  }

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-30 border-b border-border bg-surface">
        <div className={cn("mx-auto flex h-14 items-center gap-6 px-4", wide ? "max-w-[1600px]" : "max-w-6xl")}>
          <Link href="/dashboard" className="flex items-center gap-2 font-bold text-primary">
            <FileText className="h-5 w-5" aria-hidden />
            {APP_NAME}
          </Link>
          <nav aria-label="Principal" className="flex gap-1">
            {NAV.map((n) => {
              const active = pathname.startsWith(n.href);
              return (
                <Link
                  key={n.href}
                  href={n.href}
                  aria-current={active ? "page" : undefined}
                  className={cn(
                    "flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium",
                    active ? "bg-primary-soft text-primary" : "text-muted hover:bg-surface-2 hover:text-fg",
                  )}
                >
                  <n.icon className="h-4 w-4" aria-hidden />
                  {n.label}
                </Link>
              );
            })}
          </nav>
          <div className="ml-auto">
            <ActionMenu
              label="Menu do usuário"
              trigger={
                <Button variant="ghost" className="gap-2" aria-label={`Conta de ${me?.user.name ?? "usuário"}`}>
                  <User className="h-4 w-4" aria-hidden />
                  <span className="hidden max-w-40 truncate sm:inline">{me?.user.name}</span>
                </Button>
              }
              items={[
                { label: `${me?.workspace.name ?? ""} (${me?.workspace.role === "owner" ? "proprietário" : "membro"})`, onSelect: () => {}, disabled: true },
                { separator: true },
                { label: "Sair", icon: <LogOut className="h-4 w-4" aria-hidden />, onSelect: logout },
              ]}
            />
          </div>
        </div>
      </header>
      <main id="main" className={cn("mx-auto px-4 py-8", wide ? "max-w-[1600px]" : "max-w-6xl")}>
        {children}
      </main>
    </div>
  );
}

export function PageHeader({ title, description, actions }: { title: string; description?: string; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">{title}</h1>
        {description && <p className="mt-1 text-sm text-muted">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}
