"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/form";
import { Alert } from "@/components/ui/misc";
import { api, errorMessage } from "@/lib/api";

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

export default function RegisterPage() {
  const router = useRouter();
  const qc = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const { register, handleSubmit, formState } = useForm<Form>({ resolver: zodResolver(schema) });

  async function onSubmit(v: Form) {
    setError(null);
    try {
      await api.post("/auth/register", { name: v.name, email: v.email, password: v.password, workspace_name: v.workspace_name || null });
      qc.clear();
      router.replace("/dashboard");
    } catch (e) {
      setError(errorMessage(e));
    }
  }

  return (
    <form onSubmit={handleSubmit(onSubmit)} noValidate className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold">Criar conta</h1>
        <p className="mt-1 text-sm text-muted">Você terá seu próprio espaço de trabalho, isolado dos demais.</p>
      </div>
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
        <Link href="/login" className="text-primary underline underline-offset-2">
          Entrar
        </Link>
      </p>
    </form>
  );
}
