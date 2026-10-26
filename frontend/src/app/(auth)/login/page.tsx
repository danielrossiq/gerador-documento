"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/form";
import { Alert } from "@/components/ui/misc";
import { api, errorMessage } from "@/lib/api";
import { claimTrial, validTrialToken } from "@/lib/trial";

const schema = z.object({
  email: z.string().min(1, "Informe seu e-mail.").email("Informe um e-mail válido."),
  password: z.string().min(1, "Informe sua senha."),
});
type Form = z.infer<typeof schema>;

function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const qc = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const { register, handleSubmit, formState } = useForm<Form>({ resolver: zodResolver(schema) });

  async function onSubmit(v: Form) {
    setError(null);
    try {
      await api.post("/auth/login", v);
      qc.clear();
      const trial = params.get("trial");
      if (validTrialToken(trial)) {
        try {
          router.replace(await claimTrial(trial)); // documento do teste grátis vira modelo da conta (D38)
          return;
        } catch {
          // teste vencido ou já guardado: segue o login normal
        }
      }
      const next = params.get("next");
      router.replace(next && next.startsWith("/") ? next : "/dashboard");
    } catch (e) {
      setError(errorMessage(e));
    }
  }

  return (
    <form onSubmit={handleSubmit(onSubmit)} noValidate className="space-y-4">
      <div>
        <h1 className="font-display text-2xl font-extrabold tracking-tight">Entrar</h1>
        <p className="mt-1 text-sm text-muted">Acesse seus modelos de documentos.</p>
      </div>
      {error && <Alert tone="danger">{error}</Alert>}
      <Field label="E-mail" error={formState.errors.email?.message} required>
        {(a) => <Input type="email" autoComplete="email" autoFocus {...a} {...register("email")} />}
      </Field>
      <Field label="Senha" error={formState.errors.password?.message} required>
        {(a) => <Input type="password" autoComplete="current-password" {...a} {...register("password")} />}
      </Field>
      <Button type="submit" variant="primary" className="w-full" loading={formState.isSubmitting}>
        Entrar
      </Button>
      <div className="flex justify-between text-sm">
        <Link href="/forgot-password" className="text-primary underline underline-offset-2">
          Esqueci minha senha
        </Link>
        <Link href="/register" className="text-primary underline underline-offset-2">
          Criar conta
        </Link>
      </div>
    </form>
  );
}

export default function LoginPage() {
  return (
    <Suspense>
      <LoginForm />
    </Suspense>
  );
}
