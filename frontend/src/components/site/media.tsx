// Imagens e vídeo da landing. O manifesto (site-assets.json) é gerado por scripts/site_assets.py junto com os
// arquivos em public/site/. Asset ausente → o componente não renderiza nada e a seção segue só com texto.
import manifest from "@/components/site/site-assets.json";
import { cn } from "@/lib/utils";

type ImageEntry = { base: string; widths: number[]; width: number; height: number; alt: string };
type VideoEntry = { mp4: string; webm?: string; poster: string; width: number; height: number; title: string; captions?: string };

const images = manifest.images as Record<string, ImageEntry>;
const video = manifest.video as VideoEntry | null;

export const hasImage = (name: string) => Boolean(images[name]);
export const demoVideo = video;

export function SiteImage({ name, sizes, className, priority }: { name: string; sizes: string; className?: string; priority?: boolean }) {
  const img = images[name];
  if (!img) return null;
  const set = (ext: string) => img.widths.map((w) => `${img.base}-${w}.${ext} ${w}w`).join(", ");
  const largest = img.widths[img.widths.length - 1];
  return (
    <picture>
      <source type="image/avif" srcSet={set("avif")} sizes={sizes} />
      <source type="image/webp" srcSet={set("webp")} sizes={sizes} />
      <img
        src={`${img.base}-${largest}.webp`}
        width={img.width}
        height={img.height}
        alt={img.alt}
        loading={priority ? "eager" : "lazy"}
        decoding="async"
        className={cn("h-auto w-full", className)}
      />
    </picture>
  );
}

export function DemoVideo({ className }: { className?: string }) {
  if (!video) return null;
  return (
    <video
      className={cn("h-auto w-full", className)}
      controls
      playsInline
      preload="none"
      poster={video.poster}
      width={video.width}
      height={video.height}
      aria-label={video.title}
      data-testid="demo-video"
    >
      {video.webm && <source src={video.webm} type="video/webm" />}
      <source src={video.mp4} type="video/mp4" />
      {video.captions && <track kind="captions" src={video.captions} srcLang="pt-BR" label="Português" default />}
    </video>
  );
}
