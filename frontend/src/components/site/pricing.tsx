"use client";

import { Check } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { annualDiscountPct, brl, PLANS } from "@/content/plans";
import { cn } from "@/lib/utils";

export function Pricing() {
  const [annual, setAnnual] = useState(true);
  const maxOff = Math.max(...PLANS.map(annualDiscountPct));

  return (
    <div data-testid="pricing">
      <div className="mb-10 flex justify-center">
        <div role="radiogroup" aria-label="Forma de cobrança" className="inline-flex rounded-full border border-zinc-200 bg-white p-1 shadow-sm">
          {[
            { v: false, label: "Mensal" },
            { v: true, label: `Anual · ${maxOff}% off` },
          ].map((o) => (
            <button
              key={String(o.v)}
              role="radio"
              aria-checked={annual === o.v}
              onClick={() => setAnnual(o.v)}
              className={cn("rounded-full px-5 py-2 text-sm font-semibold transition", annual === o.v ? "bg-zinc-900 text-white" : "text-zinc-600 hover:text-zinc-900")}
            >
              {o.label}
            </button>
          ))}
        </div>
      </div>

      <div className="grid items-stretch gap-6 lg:grid-cols-3">
        {PLANS.map((p) => {
          const price = annual ? p.annualMonthly : p.monthly;
          return (
            <div
              key={p.id}
              data-plan={p.id}
              className={cn(
                "relative flex flex-col rounded-2xl border bg-white p-7",
                p.highlight ? "border-indigo-500 shadow-2xl shadow-indigo-500/20 ring-1 ring-indigo-500 lg:-my-4 lg:py-11" : "border-zinc-200 shadow-sm",
              )}
            >
              {p.highlight && (
                <span className="absolute -top-3 left-1/2 -translate-x-1/2 rounded-full bg-indigo-600 px-3 py-1 text-xs font-bold uppercase tracking-wide text-white">Mais escolhido</span>
              )}
              <h3 className="font-display text-xl font-bold text-zinc-900">{p.name}</h3>
              <p className="mt-1 text-sm text-zinc-500">{p.tagline}</p>
              <p className="mt-6 flex items-baseline gap-1">
                <span className="font-display text-4xl font-extrabold tracking-tight text-zinc-900">{price ? brl(price) : "R$ 0"}</span>
                <span className="text-sm text-zinc-500">{price ? "/mês" : "para sempre"}</span>
              </p>
              <p className="mt-1 h-5 text-xs text-zinc-500">
                {price && annual ? `${brl(price * 12)} por ano, em uma cobrança` : price ? "Cobrado todo mês, cancele quando quiser" : "Sem cartão de crédito"}
              </p>
              <Link
                href={`/register?plano=${p.id}${price ? (annual ? "&ciclo=anual" : "&ciclo=mensal") : ""}`}
                className={cn(
                  "mt-6 rounded-full py-3 text-center text-sm font-semibold transition",
                  p.highlight ? "bg-indigo-600 text-white hover:bg-indigo-500" : "bg-zinc-900 text-white hover:bg-zinc-700",
                )}
                data-testid={`plan-cta-${p.id}`}
              >
                {price ? `Assinar o ${p.name}` : "Começar grátis"}
              </Link>
              <ul className="mt-7 space-y-3 text-sm text-zinc-700">
                {p.features.map((f) => (
                  <li key={f} className="flex gap-2.5">
                    <Check className="mt-0.5 h-4 w-4 shrink-0 text-indigo-600" aria-hidden />
                    {f}
                  </li>
                ))}
              </ul>
            </div>
          );
        })}
      </div>
      <p className="mt-10 text-center text-sm text-zinc-500">Pague com cartão de crédito ou Pix. Sem fidelidade: cancele quando quiser, direto no app.</p>
    </div>
  );
}
