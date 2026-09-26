import {
  AtSign, Calendar, CheckSquare, ChevronDown, CircleDollarSign, Fingerprint, Hash, MapPin, Phone, ToggleLeft, Type, AlignLeft, Building2,
  type LucideIcon,
} from "lucide-react";
import type { FieldType } from "@/lib/types";

export const FIELD_TYPE_META: Record<FieldType, { label: string; icon: LucideIcon; hint: string }> = {
  text_short: { label: "Texto curto", icon: Type, hint: "Nomes, títulos, cargos" },
  text_long: { label: "Texto longo", icon: AlignLeft, hint: "Descrições e parágrafos" },
  number: { label: "Número", icon: Hash, hint: "Quantidades, percentuais" },
  currency: { label: "Moeda (R$)", icon: CircleDollarSign, hint: "Valores em reais" },
  date: { label: "Data", icon: Calendar, hint: "dd/mm/aaaa" },
  cpf: { label: "CPF", icon: Fingerprint, hint: "Validado com dígitos verificadores" },
  cnpj: { label: "CNPJ", icon: Building2, hint: "Numérico e alfanumérico" },
  cep: { label: "CEP", icon: MapPin, hint: "00000-000" },
  email: { label: "E-mail", icon: AtSign, hint: "nome@empresa.com" },
  phone: { label: "Telefone", icon: Phone, hint: "(11) 91234-5678" },
  select: { label: "Lista suspensa", icon: ChevronDown, hint: "Uma opção entre várias" },
  yes_no: { label: "Sim/Não", icon: ToggleLeft, hint: "Resposta binária" },
  checkbox: { label: "Checkbox", icon: CheckSquare, hint: "Marcado ou desmarcado" },
};

export const FIELD_TYPE_LIST = (Object.keys(FIELD_TYPE_META) as FieldType[]).map((value) => ({ value, ...FIELD_TYPE_META[value] }));

export function typeLabel(t: FieldType): string {
  return FIELD_TYPE_META[t]?.label ?? t;
}
