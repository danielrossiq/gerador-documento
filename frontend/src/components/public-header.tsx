"use client";
import {useState} from "react";
import Link from "next/link";
import {Menu,X} from "lucide-react";
import {Brand} from "@/components/brand";
import {ThemeToggle} from "@/components/theme-toggle";
export function PublicHeader(){const [open,setOpen]=useState(false);return <header className="public-header"><div className="public-header-inner"><Brand/><nav className="desktop-public-nav" aria-label="Principal"><Link href="/#como-funciona">Como funciona</Link><Link href="/#recursos">Recursos</Link><Link href="/#planos">Planos</Link></nav><div className="public-header-actions"><ThemeToggle/><Link className="public-login" href="/login">Entrar</Link><Link className="cta cta-small" href="/register">Começar agora <span aria-hidden>↗</span></Link><button className="theme-toggle mobile-menu-trigger" aria-label={open?"Fechar menu":"Abrir menu"} aria-expanded={open} aria-controls="public-mobile-menu" onClick={()=>setOpen(!open)}>{open?<X size={20}/>:<Menu size={20}/>}</button></div></div>{open&&<nav id="public-mobile-menu" className="mobile-public-nav" aria-label="Navegação móvel"><Link onClick={()=>setOpen(false)} href="/#como-funciona">Como funciona</Link><Link onClick={()=>setOpen(false)} href="/#recursos">Recursos</Link><Link onClick={()=>setOpen(false)} href="/#planos">Planos</Link><Link href="/login">Entrar na minha conta</Link></nav>}</header>}
