"use client";
import { useSyncExternalStore } from "react";
import { Moon, Sun } from "lucide-react";
const subscribe = (listener: () => void) => {
 window.addEventListener("minuta-theme-change", listener);
 return () => window.removeEventListener("minuta-theme-change", listener);
};
export function ThemeToggle() {
 const dark = useSyncExternalStore(subscribe, () => document.documentElement.dataset.theme === "dark", () => false);
 function toggle(){const next=!dark;document.documentElement.dataset.theme=next?"dark":"light";try{localStorage.setItem("minuta-theme",next?"dark":"light");}catch{}window.dispatchEvent(new Event("minuta-theme-change"));}
 return <button type="button" onClick={toggle} className="theme-toggle" aria-label={dark?"Ativar tema claro":"Ativar tema escuro"} title={dark?"Tema claro":"Tema escuro"}>{dark?<Sun size={18} aria-hidden/>:<Moon size={18} aria-hidden/>}</button>;
}
