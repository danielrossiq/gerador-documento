// Planos exibidos na landing e na tela de assinatura. Fonte única do lado do site; os limites que o servidor aplica
// ficam em backend/app/modules/billing/plans.json — um teste do backend confere que os dois arquivos batem.
import plansJson from "./plans.json";

export type PlanId = "gratis" | "profissional" | "escritorio";

export type Plan = {
  id: PlanId;
  name: string;
  tagline: string;
  /** preço mensal em reais (0 = grátis) */
  monthly: number;
  /** preço por mês no plano anual (cobrado de uma vez: 12 × este valor) */
  annualMonthly: number;
  highlight: boolean;
  limits: {
    docs_per_month: number;
    models: number | null;
    batch_rows: number;
    ai_analyses_per_month: number;
    /** envios para assinatura eletrônica por mês (D40) */
    signatures_per_month: number;
  };
  features: string[];
};

export const PLANS = plansJson.plans as Plan[];

export const brl = (n: number) => n.toLocaleString("pt-BR", { style: "currency", currency: "BRL", minimumFractionDigits: 2 });

export const annualDiscountPct = (p: Plan) => (p.monthly ? Math.round((1 - p.annualMonthly / p.monthly) * 100) : 0);
