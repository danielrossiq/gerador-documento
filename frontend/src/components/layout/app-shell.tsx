"use client";
import {useQuery,useQueryClient} from "@tanstack/react-query";
import {FileStack,History,Home,Layers,LogOut,User,Sparkles,CreditCard,Menu,X,ArrowUpRight,ChevronRight} from "lucide-react";
import Link from "next/link";
import {usePathname,useRouter} from "next/navigation";
import {useEffect,useState,type ReactNode} from "react";
import {api} from "@/lib/api";
import type {Me} from "@/lib/types";
import {Brand} from "@/components/brand";
import {ThemeToggle} from "@/components/theme-toggle";
export function useMe(){return useQuery({queryKey:["me"],queryFn:()=>api.get<Me>("/auth/me"),staleTime:60_000});}
const NAV=[
 {href:"/dashboard",label:"Visão geral",icon:Home,also:["/home"]},
 {href:"/models",label:"Meus modelos",icon:FileStack,also:["/generators"]},
 {href:"/kits",label:"Kits de documentos",icon:Layers,also:[]},
 {href:"/history",label:"Histórico",icon:History,also:[]},
 {href:"/assistant",label:"Assistente IA",icon:Sparkles,also:[]},
 {href:"/billing",label:"Plano e uso",icon:CreditCard,also:[]},
 {href:"/account",label:"Minha conta",icon:User,also:[]},
];
export function AppShell({children,wide=false}:{children:ReactNode;wide?:boolean}){
 const pathname=usePathname();const router=useRouter();const qc=useQueryClient();const {data:me}=useMe();const [open,setOpen]=useState(false);
 useEffect(()=>{setOpen(false);},[pathname]);
 useEffect(()=>{if(!open)return;const onKey=(e:KeyboardEvent)=>{if(e.key==="Escape"){setOpen(false);document.getElementById("workspace-menu")?.focus();}};document.addEventListener("keydown",onKey);return()=>document.removeEventListener("keydown",onKey);},[open]);
 async function logout(){await api.post("/auth/logout").catch(()=>undefined);qc.clear();router.replace("/login");}
 function active(n:typeof NAV[number]){return pathname===n.href||pathname.startsWith(n.href+"/")||n.also.some(p=>pathname===p||pathname.startsWith(p+"/"));}
 const current=NAV.find(active)?.label??"Espaço de trabalho";
 return <div className="workspace">{open&&<button className="workspace-overlay" onClick={()=>setOpen(false)} aria-label="Fechar navegação" tabIndex={-1}/>}
 <aside className="workspace-sidebar" data-open={open} aria-label="Espaço de trabalho"><Brand href="/dashboard"/><button className="theme-toggle workspace-mobile-close" onClick={()=>setOpen(false)} aria-label="Fechar menu"><X size={17}/></button><p className="workspace-label">SEU ESPAÇO DE TRABALHO</p><nav className="workspace-nav" aria-label="Navegação principal">{NAV.map(n=><Link href={n.href} key={n.href} aria-current={active(n)?"page":undefined}><n.icon size={17} strokeWidth={1.6} aria-hidden/><span>{n.label}</span>{n.href==="/assistant"&&<small className="nav-ai-tag">IA</small>}</Link>)}</nav><div className="workspace-sidebar-bottom"><div className="workspace-tip"><p>Um modelo.<br/>Novas possibilidades.</p><Link href="/generators/new">Criar meu próximo modelo <ArrowUpRight size={13}/></Link></div><button onClick={logout} className="workspace-logout"><LogOut size={16}/> Sair da conta</button></div></aside>
 <header className="workspace-topbar"><div className="workspace-breadcrumb"><button id="workspace-menu" className="theme-toggle workspace-menu-trigger" onClick={()=>setOpen(!open)} aria-expanded={open} aria-label="Abrir navegação"><Menu size={18}/></button><span>Espaço de trabalho</span><ChevronRight size={12} aria-hidden/><strong>{current}</strong></div><div className="workspace-topbar-right"><ThemeToggle/><Link className="workspace-user" href="/account" aria-label="Minha conta"><span className="workspace-user-email">{me?.user.email??"Minha conta"}</span><span className="workspace-avatar" aria-hidden>{me?.user.email?.slice(0,2).toUpperCase()??"M"}</span></Link></div></header>
 <main id="main" className={"workspace-main"+(wide?" workspace-main-wide":"")}>{children}</main></div>;
}
export function PageHeader({title,description,actions}:{title:string;description?:string;actions?:ReactNode}){return <div className="page-header"><div><h1>{title}</h1>{description&&<p>{description}</p>}</div>{actions&&<div className="page-header-actions">{actions}</div>}</div>}
