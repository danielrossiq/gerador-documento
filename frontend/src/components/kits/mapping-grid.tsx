"use client";

import { useState } from "react";
import { Badge } from "@/components/ui/misc";
import { useToast } from "@/components/ui/toast";
import { api, errorMessage } from "@/lib/api";
import { typeLabel } from "@/lib/fields/meta";
import type { KitFieldOut, KitItemOut } from "@/lib/types";

/**
 * Grade de mapeamento: uma linha por campo compartilhado do kit, uma coluna por documento membro. Cada célula
 * escolhe qual campo DAQUELE documento recebe o valor do campo do kit (só campos do mesmo tipo aparecem).
 */
export function MappingGrid({ kitId, fields, items, onChanged }: {
  kitId: string;
  fields: KitFieldOut[];
  items: KitItemOut[];
  onChanged: () => void;
}) {
  const toast = useToast();
  const [busy, setBusy] = useState<string | null>(null);
  const usableItems = items.filter((it) => it.usable);

  async function setCell(item: KitItemOut, kitFieldName: string, memberFieldName: string) {
    const key = `${item.id}:${kitFieldName}`;
    setBusy(key);
    const mapping = { ...item.field_mapping, [kitFieldName]: memberFieldName || null };
    try {
      await api.put(`/kits/${kitId}/items/${item.id}/mapping`, { mapping });
      onChanged();
    } catch (e) {
      toast.push({ tone: "danger", title: "Não foi possível mapear", description: errorMessage(e) });
    } finally {
      setBusy(null);
    }
  }

  if (fields.length === 0 || usableItems.length === 0) return null;

  return (
    <div className="relative overflow-x-auto rounded-md border border-border">
      <table className="w-full min-w-[480px] text-left text-sm">
        <caption className="sr-only">De qual campo de cada documento vem cada dado em comum</caption>
        <thead className="bg-surface-2 text-xs uppercase tracking-wide text-muted">
          <tr>
            <th scope="col" className="px-3 py-2">Campo do kit</th>
            {usableItems.map((it) => (
              <th key={it.id} scope="col" className="px-3 py-2">{it.generator_name}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {fields.map((kf) => (
            <tr key={kf.id} className="border-t border-border">
              <th scope="row" className="px-3 py-2 font-medium">
                {kf.label}
                <Badge className="ml-2 align-middle">{typeLabel(kf.type)}</Badge>
              </th>
              {usableItems.map((it) => {
                const options = it.fields.filter((f) => f.type === kf.type);
                const value = it.field_mapping[kf.name] ?? "";
                const key = `${it.id}:${kf.name}`;
                return (
                  <td key={it.id} className="px-3 py-2">
                    <select
                      aria-label={`Campo de “${it.generator_name}” para “${kf.label}”`}
                      className="h-9 w-full rounded-md border border-border-strong bg-surface px-2 text-sm disabled:opacity-60"
                      value={value}
                      disabled={busy === key}
                      onChange={(e) => setCell(it, kf.name, e.target.value)}
                    >
                      <option value="">— Nenhum —</option>
                      {options.map((f) => (
                        <option key={f.name} value={f.name}>{f.label}</option>
                      ))}
                    </select>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
