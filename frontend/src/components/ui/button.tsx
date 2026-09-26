"use client";

import { Loader2 } from "lucide-react";
import Link from "next/link";
import { forwardRef, type AnchorHTMLAttributes, type ButtonHTMLAttributes, type ComponentProps } from "react";
import { cn } from "@/lib/utils";

type Variant = "primary" | "secondary" | "ghost" | "danger" | "success";
type Size = "sm" | "md" | "lg" | "icon";

const VARIANTS: Record<Variant, string> = {
  primary: "bg-primary text-primary-fg hover:bg-primary-hover border-transparent",
  secondary: "bg-surface text-fg border-border-strong hover:bg-surface-2",
  ghost: "bg-transparent text-fg border-transparent hover:bg-surface-2",
  danger: "bg-danger text-white border-transparent hover:opacity-90",
  success: "bg-success text-white border-transparent hover:opacity-90",
};
const SIZES: Record<Size, string> = {
  sm: "h-8 px-3 text-sm gap-1.5",
  md: "h-10 px-4 text-sm gap-2",
  lg: "h-11 px-5 text-base gap-2",
  icon: "h-9 w-9 justify-center",
};

/** Classes de botão reutilizáveis — também para links que *parecem* botões (ver ButtonLink). */
export function buttonClass({ variant = "secondary", size = "md", className }: { variant?: Variant; size?: Size; className?: string } = {}) {
  return cn(
    "inline-flex items-center rounded-md border font-medium transition-colors select-none",
    "disabled:cursor-not-allowed disabled:opacity-55 aria-disabled:cursor-not-allowed aria-disabled:opacity-55",
    VARIANTS[variant],
    SIZES[size],
    className,
  );
}

export type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: Size; loading?: boolean };

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "secondary", size = "md", loading, disabled, className, children, type = "button", ...rest },
  ref,
) {
  return (
    <button ref={ref} type={type} disabled={disabled || loading} aria-busy={loading || undefined} className={buttonClass({ variant, size, className })} {...rest}>
      {loading && <Loader2 className="h-4 w-4 animate-spin" aria-hidden />}
      {children}
    </button>
  );
});

/**
 * Link de navegação com aparência de botão. Antes usávamos `<Link><Button/></Link>`, o que criava duas paradas
 * de Tab (link + botão) para uma única ação e um elemento interativo dentro de outro.
 */
export function ButtonLink({ variant = "secondary", size = "md", className, ...rest }: ComponentProps<typeof Link> & { variant?: Variant; size?: Size }) {
  return <Link className={buttonClass({ variant, size, className })} {...rest} />;
}

/** Âncora simples (download, arquivo servido pela API) com aparência de botão. */
export function ButtonAnchor({ variant = "secondary", size = "md", className, ...rest }: AnchorHTMLAttributes<HTMLAnchorElement> & { variant?: Variant; size?: Size }) {
  return <a className={buttonClass({ variant, size, className })} {...rest} />;
}
