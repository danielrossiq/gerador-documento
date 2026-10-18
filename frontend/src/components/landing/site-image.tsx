import manifest from "../../../public/site/manifest.json";

type Variant = { file: string; width: number; height: number };
type Entry = { alt: string; variants: Variant[] };
const images = manifest.images as Record<string, Entry>;

/**
 * Imagem gerada pela Runway (scripts/generate_site_images.py), servida em AVIF/WebP com larguras responsivas.
 * Sem imagem no manifest (ainda não gerada), não renderiza nada: a página continua completa só com o texto.
 */
export function SiteImage({ slug, sizes, className, priority }: { slug: string; sizes: string; className?: string; priority?: boolean }) {
  const img = images[slug];
  if (!img?.variants?.length) return null;
  const set = (ext: string) =>
    img.variants
      .filter((v) => v.file.endsWith(`.${ext}`))
      .map((v) => `${v.file} ${v.width}w`)
      .join(", ");
  const webp = img.variants.filter((v) => v.file.endsWith(".webp"));
  const fallback = webp[webp.length - 1];
  return (
    <picture>
      <source type="image/avif" srcSet={set("avif")} sizes={sizes} />
      <source type="image/webp" srcSet={set("webp")} sizes={sizes} />
      <img
        src={fallback.file}
        width={fallback.width}
        height={fallback.height}
        alt={img.alt}
        sizes={sizes}
        loading={priority ? "eager" : "lazy"}
        fetchPriority={priority ? "high" : undefined}
        decoding="async"
        className={className}
      />
    </picture>
  );
}
