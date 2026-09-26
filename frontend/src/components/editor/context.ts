"use client";

import { createContext } from "react";
import type { FieldIssue } from "@/lib/fields/issues";
import type { FieldOut } from "@/lib/types";

export type FieldsCtx = {
  fields: Record<string, FieldOut>;
  issues: Record<string, FieldIssue[]>;
  selectedId: string | null;
  select: (fieldId: string) => void;
};

/** Os chips de campo (NodeView) leem rótulo/tipo/estado daqui: renomear um campo atualiza todas as ocorrências. */
export const FieldsContext = createContext<FieldsCtx>({ fields: {}, issues: {}, selectedId: null, select: () => {} });
