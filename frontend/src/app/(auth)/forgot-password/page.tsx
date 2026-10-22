"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import Link from "next/link";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/form";
import { Alert } from "@/components/ui/misc";
import { api, errorMessage } from "@/lib/api";

const schema = z.object({ email: z.string().min(1, "Informe seu e-mail.").email("Informe um e-mail válido.") });
type Form = z.infer<typeof schema>;

export default function ForgotPasswordPage() {
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { register, handleSubmit, formState } = useForm<Form>({ resolver: zodResolver(schema) });

  async function onSubmit(v: Form) {
    setError(null);
    try {
      await api.post("/auth/forgot-password", v);
      setDone(true);
    } catch (e) {
      setError(errorMessage(e));
    }
  }

  return (
    <form onSubmit={handleSubmit(onSubmit)} noValidate className="space-y-4">
      <div>
        <h1 className="font-display text-2xl font-extrabold tracking-tight">Recuperar senha</h1>
        <p className="mt-1 text-sm text-muted">Enviaremos um link para você criar uma nova senha.</p>
      </div>
      {error && <Alert tone="danger">{error}</Alert>}
      {done ? (
        <Alert tone="success" title="Verifique seu e-mail">
          Se o endereço estiver cadastrado, você receberá as instruções em instantes. O link vale por 1 hora.
        </Alert>
      ) : (
        <>
          <Field label="E-mail" error={formState.errors.email?.message} required>
            {(a) => <Input type="email" autoComplete="email" autoFocus {...a} {...register("email")} />}
          </Field>
          <Button type="submit" variant="primary" className="w-full" loading={formState.isSubmitting}>
            Enviar link
          </Button>
        </>
      )}
      <p className="text-center text-sm">
        <Link href="/login" className="text-primary underline underline-offset-2">
          Voltar para o login
        </Link>
      </p>
    </form>
  );
}
