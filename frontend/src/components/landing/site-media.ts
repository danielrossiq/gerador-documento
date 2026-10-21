import captures from "./site-captures.json";
import media from "./site-media.json";

/** Uma variante otimizada (AVIF ou WebP) servida de /site/. */
export type Variant = { file: string; width: number; height: number };
export type ImageEntry = { alt: string; variants: Variant[] };
export type VideoEntry = {
  alt: string;
  width: number;
  height: number;
  duration: number;
  sources: { file: string; type: string }[];
  poster: Variant[];
};

// Gerados por scripts/generate_site_media.py (imagens e vídeo) e scripts/site_captures.py (capturas reais).
export const siteImages = media.images as Record<string, ImageEntry>;
export const siteVideos = media.videos as Record<string, VideoEntry>;
export const siteCaptures = captures as Record<string, ImageEntry>;

/** Slugs da landing-spec-v2 §5. */
export const HERO_IMAGE = "hero-modelo-vazado";
export const HERO_VIDEO = "hero-loop";
export const STEP_IMAGES = ["passo-1-modelo", "passo-2-campos", "passo-3-gerado"] as const;
export const FEATURE_IMAGES = ["recurso-lote", "recurso-kits", "recurso-historico"] as const;
/** A pessoa pausou o vídeo: ele não volta sozinho nesta sessão (§8). */
export const PAUSE_KEY = "minuta:landing-video-paused";

/** `srcset` só com as variantes de uma extensão, da menor para a maior. */
export function srcSet(variants: Variant[], ext: "avif" | "webp"): string {
  return variants
    .filter((v) => v.file.endsWith(`.${ext}`))
    .sort((a, b) => a.width - b.width)
    .map((v) => `${v.file} ${v.width}w`)
    .join(", ");
}

/** Maior WebP: vai no `src` do <img> (fallback) e define as dimensões que reservam o espaço. */
export function largestWebp(variants: Variant[]): Variant | undefined {
  return variants.filter((v) => v.file.endsWith(".webp")).sort((a, b) => b.width - a.width)[0];
}

/** Pôster do hero: o quadro 0 do vídeo quando ele existe (a troca não muda a cor); senão a imagem I1. */
export function heroPoster(
  images: Record<string, ImageEntry> = siteImages,
  videos: Record<string, VideoEntry> = siteVideos,
): { poster: Variant[]; video?: VideoEntry; narrow?: Variant[] } | null {
  const video = videos[HERO_VIDEO];
  const image = images[HERO_IMAGE];
  // Abaixo de 768 px não há vídeo (nem troca de cor): vale a I1, bem mais leve que o quadro extraído do vídeo.
  if (video?.poster?.length && video.sources?.length) return { poster: video.poster, video, narrow: image?.variants };
  return image?.variants?.length ? { poster: image.variants } : null;
}

/** Tríptico dos passos (§4.3 e ordem de corte do §10): os três, só I3 (maior, acima dos passos) ou só texto. */
export function stepImages(images: Record<string, ImageEntry> = siteImages):
  | { mode: "three"; items: ImageEntry[] }
  | { mode: "middle"; item: ImageEntry }
  | { mode: "none" } {
  const items = STEP_IMAGES.map((slug) => images[slug]);
  if (items.every((i) => i?.variants?.length)) return { mode: "three", items: items as ImageEntry[] };
  const middle = items[1];
  return middle?.variants?.length ? { mode: "middle", item: middle } : { mode: "none" };
}

/** Os três cards de recursos entram juntos ou nenhum entra: cards desiguais parecem quebrados (§4.5). */
export function featureImages(images: Record<string, ImageEntry> = siteImages): ImageEntry[] | null {
  const items = FEATURE_IMAGES.map((slug) => images[slug]);
  return items.every((i) => i?.variants?.length) ? (items as ImageEntry[]) : null;
}

export type MediaEnv = { wide: boolean; reducedMotion: boolean; saveData: boolean; effectiveType?: string };

/** O vídeo só é baixado com largura ≥ 768, sem reduzir movimento, sem Save-Data e fora de 2g/3g (§8). */
export function canLoadVideo(env: MediaEnv): boolean {
  const slow = ["slow-2g", "2g", "3g"].includes(env.effectiveType ?? "");
  return env.wide && !env.reducedMotion && !env.saveData && !slow;
}

/** Só aceita mídia da própria origem (/site/...): nada de hotlink, compatível com `media-src 'self'`. */
export function isSameOriginAsset(file: string): boolean {
  return /^\/site\/[a-z0-9][a-z0-9.-]*$/.test(file) && !file.includes("..");
}
