"use client";

import * as DM from "@radix-ui/react-dropdown-menu";
import { MoreVertical } from "lucide-react";
import type { ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export type MenuItem =
  | { label: string; icon?: ReactNode; onSelect: () => void; danger?: boolean; disabled?: boolean }
  | { separator: true };

/** Menu de ações (Radix): navegável por teclado (setas, Enter, Esc) e com foco gerenciado. */
export function ActionMenu({ items, label, trigger }: { items: MenuItem[]; label: string; trigger?: ReactNode }) {
  return (
    <DM.Root>
      <DM.Trigger asChild>
        {trigger ?? (
          <Button variant="ghost" size="icon" aria-label={label}>
            <MoreVertical className="h-4 w-4" aria-hidden />
          </Button>
        )}
      </DM.Trigger>
      <DM.Portal>
        <DM.Content align="end" sideOffset={6} className="z-50 min-w-48 rounded-md border border-border bg-surface p-1 shadow-md">
          {items.map((it, i) =>
            "separator" in it ? (
              <DM.Separator key={i} className="my-1 h-px bg-border" />
            ) : (
              <DM.Item
                key={it.label}
                disabled={it.disabled}
                onSelect={it.onSelect}
                className={cn(
                  "flex cursor-pointer items-center gap-2 rounded px-3 py-2 text-sm outline-none data-[disabled]:opacity-50",
                  "data-[highlighted]:bg-surface-2",
                  it.danger && "text-danger",
                )}
              >
                {it.icon}
                {it.label}
              </DM.Item>
            ),
          )}
        </DM.Content>
      </DM.Portal>
    </DM.Root>
  );
}
