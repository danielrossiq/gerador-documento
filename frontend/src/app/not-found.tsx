import Link from "next/link";
import {Brand} from "@/components/brand";
export default function NotFound(){return <main id="main" className="grid min-h-screen place-items-center p-8 text-center"><div><Brand/><img src="/assets/empty.svg" alt="" width="360" height="230" className="mx-auto my-8"/><p className="eyebrow justify-center">PÁGINA NÃO ENCONTRADA</p><h1 className="text-3xl">Esse caminho ficou em branco.</h1><p className="my-5 text-sm text-muted">A página pode ter mudado. Seu próximo passo está aqui.</p><Link href="/" className="cta">Voltar ao início →</Link></div></main>}
