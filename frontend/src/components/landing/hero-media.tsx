"use client";

import { Pause, Play } from "lucide-react";
import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { Picture } from "./site-image";
import { canLoadVideo, PAUSE_KEY, type Variant, type VideoEntry } from "./site-media";

const SIZES = "(max-width: 767px) 134vw, (max-width: 1199px) 100vw, 980px"; // o recorte 4:3 pede fonte 16:9 mais larga
const STALL_MS = 5000;
const MEDIA_EVENTS_OK = ["progress", "playing", "timeupdate"] as const;

type Connection = { saveData?: boolean; effectiveType?: string } & Partial<EventTarget>;
const connection = () => (navigator as Navigator & { connection?: Connection }).connection;

/** Media query como estado externo (sem setState em efeito). No servidor: false, então nada de vídeo no HTML. */
function useMedia(query: string): boolean {
  return useSyncExternalStore(
    (onChange) => {
      const mq = window.matchMedia(query);
      mq.addEventListener("change", onChange);
      return () => mq.removeEventListener("change", onChange);
    },
    () => window.matchMedia(query).matches,
    () => false,
  );
}

/** Save-Data e tipo de conexão (Network Information API, quando existe). */
function useConnection(): string {
  return useSyncExternalStore(
    (onChange) => {
      connection()?.addEventListener?.("change", onChange);
      return () => connection()?.removeEventListener?.("change", onChange);
    },
    () => `${Boolean(connection()?.saveData)}|${connection()?.effectiveType ?? ""}`,
    () => "false|",
  );
}

/**
 * Palco do hero (landing-spec-v2 §8). O pôster vem no HTML do servidor: é o candidato a LCP e reserva o espaço.
 * O <video> decorativo só é criado no cliente, depois do `load`, em requestIdleCallback, e só com largura ≥ 768,
 * sem reduzir movimento, sem Save-Data e fora de 2g/3g. Toca mudo em loop; pausa fora da tela (< 25% visível) e
 * com a aba oculta. Botão visível de pausar/reproduzir (WCAG 2.2.2); se a pessoa pausar, não volta sozinho nesta
 * sessão. Com erro ou travado por mais de 5 s, o vídeo sai e fica o pôster.
 */
export function HeroMedia({ poster, video }: { poster: Variant[]; video?: VideoEntry }) {
  const stage = useRef<HTMLDivElement>(null);
  const el = useRef<HTMLVideoElement>(null);
  const wide = useMedia("(min-width: 768px)");
  const reducedMotion = useMedia("(prefers-reduced-motion: reduce)");
  const [saveData, effectiveType] = useConnection().split("|");
  const allowed = Boolean(video) && canLoadVideo({ wide, reducedMotion, saveData: saveData === "true", effectiveType });

  const [userPaused, setUserPaused] = useState(
    () => typeof window !== "undefined" && window.sessionStorage.getItem(PAUSE_KEY) === "1",
  );
  const [mounted, setMounted] = useState(false); // já passou o load + idle
  const [failed, setFailed] = useState(false);
  const [ready, setReady] = useState(false);
  const [inView, setInView] = useState(true);
  const [tabVisible, setTabVisible] = useState(true);
  // O ambiente deixou de permitir (reduzir movimento, tela estreita): o vídeo sai e volta o pôster.
  const active = mounted && allowed && !failed;
  const playing = active && !userPaused && inView && tabVisible;

  // Cria o <video> depois do load da página, em requestIdleCallback (timeout de 2 s). Pausado pela pessoa: só se ela pedir.
  useEffect(() => {
    if (!allowed || mounted || failed || userPaused) return;
    let cancelled = false;
    let idle: number | undefined;
    const hasIdle = "requestIdleCallback" in window;
    const mount = () => {
      if (!cancelled) setMounted(true);
    };
    const start = () => {
      idle = hasIdle ? window.requestIdleCallback(mount, { timeout: 2000 }) : window.setTimeout(mount, 1);
    };
    if (document.readyState === "complete") start();
    else window.addEventListener("load", start, { once: true });
    return () => {
      cancelled = true;
      window.removeEventListener("load", start);
      if (idle !== undefined) {
        if (hasIdle) window.cancelIdleCallback(idle);
        else window.clearTimeout(idle);
      }
    };
  }, [allowed, mounted, failed, userPaused]);

  // Fora da tela (< 25% visível) ou com a aba oculta: pausa; volta quando reaparece, se a pessoa não pausou.
  useEffect(() => {
    if (!active || !stage.current) return;
    const io = new IntersectionObserver(([e]) => setInView(e.intersectionRatio >= 0.25), { threshold: [0, 0.25, 0.5, 1] });
    io.observe(stage.current);
    const onVisibility = () => setTabVisible(document.visibilityState === "visible");
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      io.disconnect();
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [active]);

  useEffect(() => {
    const v = el.current;
    if (!v) return;
    if (playing) {
      v.muted = true; // o React não serializa `muted`; sem ele o navegador bloqueia o autoplay
      v.play().catch(() => undefined); // bloqueado: fica o pôster, e o botão continua oferecendo "Reproduzir"
    } else {
      v.pause();
    }
  }, [playing, active]);

  // Erro (inclusive de todas as <source>) ou travado por mais de 5 s: remove o vídeo e o botão; fica o pôster.
  useEffect(() => {
    const v = el.current;
    if (!active || !v) return;
    let stall: number | undefined;
    const fail = () => {
      v.pause();
      setFailed(true);
    };
    const onStalled = () => {
      window.clearTimeout(stall);
      stall = window.setTimeout(fail, STALL_MS);
    };
    const onProgress = () => window.clearTimeout(stall);
    const onCanPlay = () => setReady(true);
    const lastSource = v.querySelector("source:last-of-type");
    v.addEventListener("error", fail);
    lastSource?.addEventListener("error", fail);
    v.addEventListener("stalled", onStalled);
    for (const ev of MEDIA_EVENTS_OK) v.addEventListener(ev, onProgress);
    v.addEventListener("canplay", onCanPlay);
    return () => {
      window.clearTimeout(stall);
      v.removeEventListener("error", fail);
      lastSource?.removeEventListener("error", fail);
      v.removeEventListener("stalled", onStalled);
      for (const ev of MEDIA_EVENTS_OK) v.removeEventListener(ev, onProgress);
      v.removeEventListener("canplay", onCanPlay);
    };
  }, [active]);

  const toggle = () => {
    if (userPaused) window.sessionStorage.removeItem(PAUSE_KEY);
    else window.sessionStorage.setItem(PAUSE_KEY, "1");
    setUserPaused(!userPaused);
  };

  const label = userPaused ? "Reproduzir animação" : "Pausar animação";
  return (
    <div ref={stage} className="lp-stage" data-ready={active && ready} data-video={active ? "on" : "off"}>
      <Picture variants={poster} alt="" sizes={SIZES} priority />
      {active && video && (
        <video
          ref={el}
          muted
          playsInline
          loop
          preload="metadata"
          aria-hidden="true"
          tabIndex={-1}
          disablePictureInPicture
          disableRemotePlayback
        >
          {video.sources.map((s) => (
            <source key={s.file} src={s.file} type={s.type} />
          ))}
        </video>
      )}
      {allowed && !failed && (
        <button type="button" className="lp-stage-btn" aria-label={label} title={label} onClick={toggle}>
          {userPaused ? <Play size={18} aria-hidden /> : <Pause size={18} aria-hidden />}
        </button>
      )}
    </div>
  );
}
