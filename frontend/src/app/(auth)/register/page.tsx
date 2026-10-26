"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/form";
import { Alert } from "@/components/ui/misc";
import { PLANS } from "@/content/plans";
import { api, errorMessage } from "@/lib/api";
import { claimTrial, trialStillValid, validTrialToken } from "@/lib/trial";

const schema = z
  .object({
    name: z.string().trim().min(2, "Informe seu nome."),
    email: z.string().min(1, "Informe seu e-mail.").email("Informe um e-mail válido."),
    workspace_name: z.string().trim().optional(),
    password: z.string().min(8, "A senha deve ter pelo menos 8 caracteres."),
    confirm: z.string(),
  })
  .refine((v) => v.password === v.confirm, { path: ["confirm"], message: "As senhas não conferem." });
type Form = z.infer<typeof schema>;

function RegisterForm() {
  const router = useRouter();
  const params = useSearchParams();
  // veio de um plano pago da página de preços: depois de criar a conta, segue para a assinatura com ele escolhido
  const plan = PLANS.find((p) => p.id === params.get("plano") && p.monthly > 0);
  const cycle = params.get("ciclo") === "mensal" ? "mensal" : "anual";
  // veio do teste grátis da landing: depois do cadastro, o documento testado vira um modelo da conta (D38)
  const trial = params.get("trial");
  const [trialGone, setTrialGone] = useState(false);
  const hasTrial = validTrialToken(trial) && !trialGone;
  useEffect(() => {
    if (validTrialToken(trial)) void trialStillValid(trial).then((ok) => setTrialGone(!ok));
  }, [trial]);
  const qc = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const { register, handleSubmit, formState } = useForm<Form>({ resolver: zodResolver(schema) });

  async function onSubmit(v: Form) {
    setError(null);
    try {
      await api.post("/auth/register", { name: v.name, email: v.email, password: v.password, workspace_name: v.workspace_name || null });
      qc.clear();
      if (hasTrial && trial) {
        try {
          router.replace(await claimTrial(trial));
          return;
        } catch {
          // teste vencido (1 hora) ou já guardado: a conta foi criada; segue para o início
        }
      }
      router.replace(plan ? `/assinatura?plano=${plan.id}&ciclo=${cycle}` : "/dashboard");
    } catch (e) {
      setError(errorMessage(e));
    }
  }

  return (
    <form onSubmit={handleSubmit(onSubmit)} noValidate className="space-y-4">
      <div>
        <h1 className="font-display text-2xl font-extrabold tracking-tight">Criar conta</h1>
        <p className="mt-1 text-sm text-muted">Você terá seu próprio espaço de trabalho, isolado dos demais.</p>
      </div>
      {plan && (
        <Alert tone="primary" title={`Plano ${plan.name} (${cycle})`}>
          Crie a conta e em seguida escolha cartão ou Pix. Até lá, você já usa o plano Grátis.
        </Alert>
      )}
      {trialGone && (
        <Alert tone="warning" title="O documento do teste expirou ou já foi guardado">
          Envie de novo para continuar: <Link href="/#teste" className="underline">testar com o seu documento</Link> ou, depois de entrar, use “Novo modelo”.
        </Alert>
      )}
      {hasTrial && (
        <Alert tone="primary" title="Seu documento está guardado por 1 hora">
          Crie a conta e ele vira um modelo seu, com os campos que a IA encontrou.
        </Alert>
      )}
      {error && <Alert tone="danger">{error}</Alert>}
      <Field label="Nome" error={formState.errors.name?.message} required>
        {(a) => <Input autoComplete="name" autoFocus {...a} {...register("name")} />}
      </Field>
      <Field label="E-mail" error={formState.errors.email?.message} required>
        {(a) => <Input type="email" autoComplete="email" {...a} {...register("email")} />}
      </Field>
      <Field label="Nome do espaço de trabalho" help="Opcional. Ex.: nome da sua empresa." error={formState.errors.workspace_name?.message}>
        {(a) => <Input {...a} {...register("workspace_name")} />}
      </Field>
      <Field label="Senha" help="Mínimo de 8 caracteres." error={formState.errors.password?.message} required>
        {(a) => <Input type="password" autoComplete="new-password" {...a} {...register("password")} />}
      </Field>
      <Field label="Confirmar senha" error={formState.errors.confirm?.message} required>
        {(a) => <Input type="password" autoComplete="new-password" {...a} {...register("confirm")} />}
      </Field>
      <Button type="submit" variant="primary" className="w-full" loading={formState.isSubmitting}>
        Criar conta
      </Button>
      <p className="text-center text-sm">
        Já tem conta?{" "}
        <Link href={hasTrial && trial ? `/login?trial=${encodeURIComponent(trial)}` : "/login"} className="text-primary underline underline-offset-2">
          Entrar
        </Link>
      </p>
    </form>
  );
}

export default function RegisterPage() {
  return (
    <Suspense>
      <RegisterForm />
    </Suspense>
  );
}
