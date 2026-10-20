import { largestWebp, srcSet, type Variant } from "./site-media";

/**
 * <picture> com AVIF/WebP responsivos. As dimensões do maior WebP reservam o espaço (sem layout shift).
 * Abaixo da dobra: lazy e decoding assíncrono; o pôster do hero usa `priority` (é o candidato a LCP).
 */
export function Picture({
  variants,
  alt,
  sizes,
  className,
  priority,
}: {
  variants: Variant[];
  alt: string;
  sizes: string;
  className?: string;
  priority?: boolean;
}) {
  const fallback = largestWebp(variants);
  if (!fallback) return null;
  return (
    <picture>
      <source type="image/avif" srcSet={srcSet(variants, "avif")} sizes={sizes} />
      <source type="image/webp" srcSet={srcSet(variants, "webp")} sizes={sizes} />
      <img
        src={fallback.file}
        width={fallback.width}
        height={fallback.height}
        alt={alt}
        sizes={sizes}
        loading={priority ? "eager" : "lazy"}
        fetchPriority={priority ? "high" : undefined}
        decoding={priority ? "sync" : "async"}
        className={className}
      />
    </picture>
  );
}
