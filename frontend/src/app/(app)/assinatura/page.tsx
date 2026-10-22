"use client";

import { useQuery } from "@tanstack/react-query";
import { Check, CreditCard, QrCode, Sparkles } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { AppShell, PageHeader, useMe } from "@/components/layout/app-shell";
import { Button } from "@/components/ui/button";
import { Alert, Badge, Card, ProgressBar, Skeleton } from "@/components/ui/misc";
import { useToast } from "@/components/ui/toast";
import { annualDiscountPct, brl, PLANS, type PlanId } from "@/content/plans";
import { api, errorMessage } from "@/lib/api";
import { cn } from "@/lib/utils";

type Cycle = "mensal" | "anual";
type BillingOut = {
  billing_enabled: boolean;
  checkout: { card: boolean; pix: boolean };
  plan: PlanId;
  plan_name: string;
  subscription: null | {
    plan: PlanId;
    cycle: Cycle;
    status: "active" | "past_due" | "canceled" | "incomplete" | "expired";
    method: "card" | "pix";
    current_period_end: string | null;
    cancel_at_period_end: boolean;
    can_manage: boolean;
  };
  usage: { docs_this_month: number; ai_actions_this_month: number; models: number };
  limits: { docs_per_month: number; models: number; batch_rows: number; ai_actions_per_month: number };
};

const UNLIMITED = 10_000;
const date = (iso: string | null) => (iso ? new Date(iso).toLocaleDateString("pt-BR", { day: "2-digit", month: "long", year: "numeric" }) : "");

function Meter({ label, used, limit, testid, unlimitable }: { label: string; used: number; limit: number; testid: string; unlimitable?: boolean }) {
  const unlimited = !!unlimitable && limit >= UNLIMITED;
  const ratio = unlimited ? 0 : Math.min(1, used / Math.max(1, limit));
  return (
    <div className="space-y-1" data-testid={testid}>
      <div className="flex items-baseline justify-between gap-2 text-sm">
        <span className="font-medium">{label}</span>
        <span className="tabular-nums text-muted">{unlimited ? `${used.toLocaleString("pt-BR")} · ilimitado` : `${used.toLocaleString("pt-BR")} de ${limit.toLocaleString("pt-BR")}`}</span>
      </div>
      {!unlimited && <ProgressBar value={ratio} label={label} tone={ratio >= 0.9 ? "danger" : "primary"} />}
    </div>
  );
}

function Billing() {
  const params = useSearchParams();
  const toast = useToast();
  const me = useMe();
  const status = params.get("status");
  const [cycle, setCycle] = useState<Cycle>(params.get("ciclo") === "mensal" ? "mensal" : "anual");
  const wanted = params.get("plano");
  const [going, setGoing] = useState<string | null>(null);
  const q = useQuery({
    queryKey: ["billing"],
    queryFn: () => api.get<BillingOut>("/billing"),
    // voltando do pagamento: a confirmação chega pelo webhook em alguns segundos; atualiza até o plano mudar
    refetchInterval: (query) => (status === "sucesso" && query.state.data?.plan === "gratis" && query.state.dataUpdateCount < 20 ? 3000 : false),
  });
  const owner = me.data?.workspace.role === "owner";

  async function go(path: "/billing/checkout" | "/billing/portal", body?: object, key: string = path) {
    setGoing(key);
    try {
      const r = await api.post<{ url: string }>(path, body);
      window.location.assign(r.url);
    } catch (e) {
      toast.push({ tone: "danger", title: "Não foi possível abrir o pagamento", description: errorMessage(e) });
      setGoing(null);
    }
  }

  if (q.isLoading) return <div className="space-y-4"><Skeleton className="h-40" /><Skeleton className="h-80" /></div>;
  if (q.error || !q.data) return <Alert tone="danger" title="Não foi possível carregar a assinatura">{errorMessage(q.error)}</Alert>;
  const b = q.data;
  const sub = b.subscription;
  const payable = b.checkout.card || b.checkout.pix;

  return (
    <div className="space-y-8">
      {status === "sucesso" && (
        <Alert tone="success" title={b.plan === "gratis" ? "Pagamento recebido. Ativando seu plano…" : `Tudo certo! Você está no plano ${b.plan_name}.`}>
          {b.plan === "gratis" ? "A confirmação costuma chegar em poucos segundos (no Pix, logo depois do pagamento). Esta página atualiza sozinha." : "Obrigado por assinar. Os novos limites já valem."}
        </Alert>
      )}
      {status === "cancelado" && <Alert tone="neutral" title="Pagamento não concluído">Nada foi cobrado. Você pode tentar de novo quando quiser.</Alert>}
      {!b.billing_enabled && (
        <Alert tone="primary" title="Período de lançamento">
          Os pagamentos ainda estão sendo ativados. Enquanto isso, sua conta usa limites ampliados, sem custo.
        </Alert>
      )}

      <div className="grid gap-4 lg:grid-cols-[minmax(0,22rem)_minmax(0,1fr)]">
        <Card className="space-y-3 p-5" data-testid="current-plan">
          <p className="text-xs font-semibold uppercase tracking-wide text-muted">Seu plano</p>
          <p className="text-2xl font-bold">{b.plan_name}</p>
          {sub && b.plan !== "gratis" ? (
            <div className="space-y-1 text-sm text-muted">
              <p>
                {sub.method === "pix" ? "Pago com Pix" : "Cartão de crédito"} · {sub.cycle === "anual" ? "anual" : "mensal"}
                {sub.status === "past_due" && <Badge tone="warning" className="ml-2">pagamento pendente</Badge>}
              </p>
              {sub.current_period_end && (
                <p>
                  {sub.method === "pix" || sub.cancel_at_period_end ? "Vale até " : "Renova em "}
                  <span className="font-medium text-fg">{date(sub.current_period_end)}</span>
                </p>
              )}
              {sub.method === "pix" && <p>Para continuar, pague um novo Pix antes dessa data: o período novo soma ao atual.</p>}
            </div>
          ) : (
            <p className="text-sm text-muted">Para conhecer o Minuta. Quando precisar de mais documentos, modelos ou IA, escolha um plano ao lado.</p>
          )}
          {sub?.can_manage && owner && (
            <Button onClick={() => go("/billing/portal")} loading={going === "/billing/portal"} data-testid="manage-subscription">
              <CreditCard className="h-4 w-4" aria-hidden /> Gerenciar assinatura
            </Button>
          )}
        </Card>
        <Card className="space-y-4 p-5" data-testid="usage">
          <p className="text-xs font-semibold uppercase tracking-wide text-muted">Uso neste mês</p>
          <Meter label="Documentos gerados" used={b.usage.docs_this_month} limit={b.limits.docs_per_month} testid="meter-docs" />
          <Meter label="Modelos" used={b.usage.models} limit={b.limits.models} testid="meter-models" unlimitable />
          <Meter label="Usos de IA" used={b.usage.ai_actions_this_month} limit={b.limits.ai_actions_per_month} testid="meter-ai" />
          <p className="text-xs text-muted">Geração em lote: até {b.limits.batch_rows.toLocaleString("pt-BR")} linhas por planilha. A contagem recomeça no dia 1º.</p>
        </Card>
      </div>

      <section aria-labelledby="planos" className="space-y-4">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 id="planos" className="text-lg font-semibold">Planos</h2>
            <p className="text-sm text-muted">Cancele quando quiser. No cartão a renovação é automática; no Pix você paga cada período.</p>
          </div>
          <div role="radiogroup" aria-label="Ciclo de cobrança" className="inline-flex rounded-full border border-border bg-surface-2 p-1 text-sm">
            {(["mensal", "anual"] as const).map((c) => (
              <button
                key={c}
                type="button"
                role="radio"
                aria-checked={cycle === c}
                onClick={() => setCycle(c)}
                className={cn("rounded-full px-3 py-1 font-medium", cycle === c ? "bg-surface text-fg shadow-sm" : "text-muted")}
                data-testid={`cycle-${c}`}
              >
                {c === "mensal" ? "Mensal" : `Anual · ${Math.max(...PLANS.map(annualDiscountPct))}% off`}
              </button>
            ))}
          </div>
        </div>
        {!owner && me.data && <Alert tone="neutral">Só o proprietário do espaço de trabalho pode assinar ou trocar o plano.</Alert>}
        {b.billing_enabled && !payable && <Alert tone="warning" title="Pagamentos em configuração">Em breve você poderá assinar por aqui.</Alert>}
        <div className="grid gap-4 md:grid-cols-3">
          {PLANS.map((p) => {
            const current = b.plan === p.id;
            const price = cycle === "anual" ? p.annualMonthly : p.monthly;
            const highlight = wanted ? wanted === p.id : p.highlight;
            const disabled = !owner || !b.billing_enabled || !!going || current;
            return (
              <Card key={p.id} className={cn("flex flex-col gap-4 p-5", highlight && "ring-2 ring-primary")} data-testid={`plan-${p.id}`}>
                <div>
                  <div className="flex items-center justify-between gap-2">
                    <p className="text-base font-semibold">{p.name}</p>
                    {current ? <Badge tone="success">Seu plano</Badge> : p.highlight && <Badge tone="primary">Mais escolhido</Badge>}
                  </div>
                  <p className="mt-1 text-sm text-muted">{p.tagline}</p>
                </div>
                <p>
                  <span className="text-3xl font-bold tabular-nums">{p.monthly ? brl(price) : "R$ 0"}</span>
                  {p.monthly > 0 && <span className="text-sm text-muted"> /mês</span>}
                  {p.monthly > 0 && cycle === "anual" && (
                    <span className="block text-xs text-muted">{brl(price * 12)} por ano · economia de {annualDiscountPct(p)}%</span>
                  )}
                </p>
                <ul className="flex-1 space-y-1.5 text-sm">
                  {p.features.map((f) => (
                    <li key={f} className="flex gap-2"><Check className="mt-0.5 h-4 w-4 shrink-0 text-success" aria-hidden />{f}</li>
                  ))}
                </ul>
                {p.monthly > 0 && (
                  <div className="space-y-2">
                    {(b.checkout.card || !b.billing_enabled) && (
                      <Button
                        variant={highlight ? "primary" : "secondary"}
                        className="w-full"
                        disabled={disabled || !b.checkout.card || sub?.method === "card"}
                        loading={going === `card-${p.id}`}
                        onClick={() => go("/billing/checkout", { plan: p.id, cycle, method: "card" }, `card-${p.id}`)}
                        data-testid={`checkout-card-${p.id}`}
                      >
                        <CreditCard className="h-4 w-4" aria-hidden /> {current ? "Plano atual" : "Assinar no cartão"}
                      </Button>
                    )}
                    {b.checkout.pix && (
                      <Button
                        className="w-full"
                        disabled={!owner || !!going || (sub?.method === "card" && b.plan !== "gratis")}
                        loading={going === `pix-${p.id}`}
                        onClick={() => go("/billing/checkout", { plan: p.id, cycle, method: "pix" }, `pix-${p.id}`)}
                        data-testid={`checkout-pix-${p.id}`}
                      >
                        <QrCode className="h-4 w-4" aria-hidden /> {current ? "Renovar com Pix" : "Pagar com Pix"}
                      </Button>
                    )}
                    {sub?.method === "card" && !current && b.plan !== "gratis" && <p className="text-xs text-muted">Para trocar de plano, use “Gerenciar assinatura”.</p>}
                  </div>
                )}
              </Card>
            );
          })}
        </div>
        <p className="flex items-center gap-1.5 text-xs text-muted">
          <Sparkles className="h-3.5 w-3.5" aria-hidden /> “Usos de IA”: cada análise de documento, preenchimento a partir de texto colado ou revisão conta um uso.
          Pagamento processado pela Stripe; o Minuta não vê nem guarda os dados do seu cartão.
        </p>
      </section>
    </div>
  );
}

export default function AssinaturaPage() {
  return (
    <AppShell>
      <PageHeader title="Plano e uso" description="Acompanhe o uso do mês e escolha o plano que cabe no seu volume de documentos." />
      <Suspense>
        <Billing />
      </Suspense>
    </AppShell>
  );
}
