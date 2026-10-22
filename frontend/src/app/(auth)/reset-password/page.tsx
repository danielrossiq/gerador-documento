"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/form";
import { Alert } from "@/components/ui/misc";
import { api, errorMessage } from "@/lib/api";

const schema = z
  .object({ password: z.string().min(8, "A senha deve ter pelo menos 8 caracteres."), confirm: z.string() })
  .refine((v) => v.password === v.confirm, { path: ["confirm"], message: "As senhas não conferem." });
type Form = z.infer<typeof schema>;

function ResetForm() {
  const router = useRouter();
  const token = useSearchParams().get("token") ?? "";
  const [error, setError] = useState<string | null>(null);
  const { register, handleSubmit, formState } = useForm<Form>({ resolver: zodResolver(schema) });

  async function onSubmit(v: Form) {
    setError(null);
    try {
      await api.post("/auth/reset-password", { token, password: v.password });
      router.replace("/login");
    } catch (e) {
      setError(errorMessage(e));
    }
  }

  if (!token) return <Alert tone="danger">Link inválido. Peça um novo em “Esqueci minha senha”.</Alert>;
  return (
    <form onSubmit={handleSubmit(onSubmit)} noValidate className="space-y-4">
      <h1 className="font-display text-2xl font-extrabold tracking-tight">Nova senha</h1>
      {error && <Alert tone="danger">{error}</Alert>}
      <Field label="Nova senha" error={formState.errors.password?.message} required>
        {(a) => <Input type="password" autoComplete="new-password" autoFocus {...a} {...register("password")} />}
      </Field>
      <Field label="Confirmar nova senha" error={formState.errors.confirm?.message} required>
        {(a) => <Input type="password" autoComplete="new-password" {...a} {...register("confirm")} />}
      </Field>
      <Button type="submit" variant="primary" className="w-full" loading={formState.isSubmitting}>
        Salvar nova senha
      </Button>
      <p className="text-center text-sm">
        <Link href="/login" className="text-primary underline underline-offset-2">
          Voltar para o login
        </Link>
      </p>
    </form>
  );
}

export default function ResetPasswordPage() {
  return (
    <Suspense>
      <ResetForm />
    </Suspense>
  );
}
