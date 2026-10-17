"use client";
import Link from "next/link";
import {AppShell,PageHeader,useMe} from "@/components/layout/app-shell";
import {ThemeToggle} from "@/components/theme-toggle";
export default function AccountPage(){const {data:me}=useMe();return <AppShell><PageHeader title="Seu espaço, do seu jeito." description="Informações da conta e preferências de visualização."/><div className="usage-detail"><h2>Minha conta</h2><dl><div><dt>Nome</dt><dd>{me?.user.name??"—"}</dd></div><div><dt>E-mail</dt><dd>{me?.user.email??"—"}</dd></div><div><dt>Espaço de trabalho</dt><dd>{me?.workspace.name??"—"}</dd></div><div><dt>Permissão</dt><dd>{me?.workspace.role==="owner"?"Proprietário":"Membro"}</dd></div><div><dt>Aparência</dt><dd><ThemeToggle/></dd></div></dl><p className="demo-note">Os dados acima são os dados reais da sessão. A edição de perfil não está disponível nesta versão.</p><Link href="/billing" className="text-cta">Consultar plano e uso →</Link></div></AppShell>}
