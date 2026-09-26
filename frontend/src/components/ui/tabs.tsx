"use client";

import * as RT from "@radix-ui/react-tabs";
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

export function Tabs({ value, onValueChange, tabs, className, children }: {
  value: string;
  onValueChange: (v: string) => void;
  tabs: { value: string; label: ReactNode }[];
  className?: string;
  children?: ReactNode;
}) {
  return (
    <RT.Root value={value} onValueChange={onValueChange} className={className}>
      <RT.List className="flex gap-1 border-b border-border" aria-label="Seções">
        {tabs.map((t) => (
          <RT.Trigger
            key={t.value}
            value={t.value}
            className={cn(
              "-mb-px border-b-2 border-transparent px-3 py-2 text-sm font-medium text-muted",
              "data-[state=active]:border-primary data-[state=active]:text-fg hover:text-fg",
            )}
          >
            {t.label}
          </RT.Trigger>
        ))}
      </RT.List>
      {children}
    </RT.Root>
  );
}
export const TabPanel = RT.Content;
