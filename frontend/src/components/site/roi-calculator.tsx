"use client";

import Link from "next/link";
import { useId, useState } from "react";
import { brl, PLANS } from "@/content/plans";

/** Quanto tempo (e dinheiro) sai do copiar-e-colar. Premissa explícita: ~1 min por documento no DocFeito. */
export function RoiCalculator() {
  const id = useId();
  const [docs, setDocs] = useState(60);
  const [minutes, setMinutes] = useState(15);
  const [hourly, setHourly] = useState(120);

  const minutesSaved = docs * Math.max(0, minutes - 1);
  const hours = minutesSaved / 60;
  const money = hours * hourly;
  const pro = PLANS.find((p) => p.id === "profissional")!;
  const plan = docs > pro.limits.docs_per_month ? PLANS.find((p) => p.id === "escritorio")! : pro;
  const ratio = plan.monthly ? money / plan.monthly : 0;

  const slider = (label: string, value: number, set: (n: number) => void, min: number, max: number, step: number, fmt: (n: number) => string, suffix: string) => (
    <label className="block" htmlFor={`${id}-${label}`}>
      <span className="flex items-baseline justify-between text-sm">
        <span className="font-medium text-zinc-700">{label}</span>
        <span className="font-display text-lg font-bold text-zinc-900 tabular-nums">{fmt(value)}<span className="ml-1 text-xs font-medium text-zinc-500">{suffix}</span></span>
      </span>
      <input id={`${id}-${label}`} type="range" min={min} max={max} step={step} value={value} onChange={(e) => set(Number(e.target.value))} className="site-range mt-2 w-full" />
    </label>
  );

  return (
    <div className="grid overflow-hidden rounded-2xl border border-zinc-200 bg-white shadow-xl shadow-zinc-900/5 lg:grid-cols-2" data-testid="roi">
      <div className="space-y-6 p-6 sm:p-8">
        {slider("Documentos por mês", docs, setDocs, 5, 1500, 5, (n) => n.toLocaleString("pt-BR"), "docs")}
        {slider("Minutos por documento hoje", minutes, setMinutes, 3, 60, 1, (n) => String(n), "min")}
        {slider("Quanto vale sua hora", hourly, setHourly, 30, 600, 10, (n) => brl(n).replace(",00", ""), "/h")}
        <p className="text-xs text-zinc-500">Estimativa: considera cerca de 1 minuto por documento no DocFeito (revisar e baixar). Em lote, é menos ainda.</p>
      </div>
      <div className="flex flex-col justify-center gap-4 bg-ink p-6 text-white sm:p-8">
        <p className="text-sm text-zinc-400">Todo mês você recupera</p>
        <p className="font-display text-5xl font-extrabold tracking-tight tabular-nums sm:text-6xl" aria-live="polite">
          {hours >= 10 ? Math.round(hours).toLocaleString("pt-BR") : hours.toFixed(1).replace(".", ",")} horas
        </p>
        <p className="text-lg text-zinc-300">
          ≈ <strong className="text-white">{brl(Math.round(money))}</strong> de trabalho que deixa de ser copiar e colar.
        </p>
        {ratio >= 1 && (
          <p className="rounded-lg bg-white/5 px-4 py-3 text-sm text-zinc-300 ring-1 ring-white/10">
            O plano {plan.name} custa {brl(plan.monthly)}/mês: <strong className="text-brand-bright">retorno de {Math.round(ratio).toLocaleString("pt-BR")}×</strong> o valor.
          </p>
        )}
        <Link href="/register" className="mt-2 inline-flex w-fit items-center rounded-full bg-highlight px-5 py-2.5 text-sm font-semibold text-ink transition hover:bg-[#ffe066]">
          Quero essas horas de volta
        </Link>
      </div>
    </div>
  );
}
