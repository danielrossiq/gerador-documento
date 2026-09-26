"use client";

import { createContext } from "react";
import type { FieldOut } from "@/lib/types";

export type FieldsCtx = {
  fields: Record<string, FieldOut>;
  selectedId: string | null;
  select: (fieldId: string) => void;
};

/** Os chips de campo (NodeView) leem rótulo/tipo/estado daqui: renomear um campo atualiza todas as ocorrências. */
export const FieldsContext = createContext<FieldsCtx>({ fields: {}, selectedId: null, select: () => {} });
