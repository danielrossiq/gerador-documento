"use client";

import { CheckCircle2, Info, X, XCircle } from "lucide-react";
import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from "react";
import { cn } from "@/lib/utils";

type Tone = "success" | "danger" | "info";
type Toast = { id: number; tone: Tone; title: string; description?: string };
type Ctx = { push: (t: Omit<Toast, "id">) => void };

const ToastContext = createContext<Ctx>({ push: () => {} });
export const useToast = () => useContext(ToastContext);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Toast[]>([]);
  const seq = useRef(0);
  const dismiss = useCallback((id: number) => setItems((l) => l.filter((t) => t.id !== id)), []);
  const push = useCallback(
    (t: Omit<Toast, "id">) => {
      const id = ++seq.current;
      setItems((l) => [...l.slice(-3), { ...t, id }]);
      setTimeout(() => dismiss(id), t.tone === "danger" ? 9000 : 5000);
    },
    [dismiss],
  );
  const value = useMemo(() => ({ push }), [push]);
  return (
    <ToastContext.Provider value={value}>
      {children}
      <div aria-live="polite" aria-atomic="false" className="pointer-events-none fixed bottom-4 right-4 z-[60] flex w-[min(24rem,calc(100vw-2rem))] flex-col gap-2">
        {items.map((t) => {
          const Icon = t.tone === "success" ? CheckCircle2 : t.tone === "danger" ? XCircle : Info;
          return (
            <div
              key={t.id}
              role={t.tone === "danger" ? "alert" : "status"}
              className={cn(
                "pointer-events-auto flex gap-3 rounded-md border bg-surface p-3 text-sm shadow-md",
                t.tone === "success" && "border-success/40",
                t.tone === "danger" && "border-danger/40",
              )}
            >
              <Icon className={cn("mt-0.5 h-4 w-4 shrink-0", t.tone === "success" ? "text-success" : t.tone === "danger" ? "text-danger" : "text-primary")} aria-hidden />
              <div className="min-w-0 flex-1">
                <p className="font-medium">{t.title}</p>
                {t.description && <p className="mt-0.5 text-muted">{t.description}</p>}
              </div>
              <button type="button" aria-label="Fechar aviso" onClick={() => dismiss(t.id)} className="text-muted hover:text-fg">
                <X className="h-4 w-4" aria-hidden />
              </button>
            </div>
          );
        })}
      </div>
    </ToastContext.Provider>
  );
}
