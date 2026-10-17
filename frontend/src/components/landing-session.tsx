"use client";
import {useEffect} from "react";
import {useRouter} from "next/navigation";
/** A landing é pública; uma sessão válida continua no painel, sem erro de auth global. */
export function LandingSession(){const router=useRouter();useEffect(()=>{const controller=new AbortController();void fetch("/api/auth/me",{credentials:"include",signal:controller.signal,cache:"no-store"}).then(r=>{if(r.ok)router.replace("/home");}).catch(()=>undefined);return()=>controller.abort();},[router]);return null;}
