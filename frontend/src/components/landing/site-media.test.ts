import { describe, expect, it } from "vitest";
import captures from "./site-captures.json";
import media from "./site-media.json";
import {
  canLoadVideo,
  featureImages,
  heroPoster,
  isSameOriginAsset,
  largestWebp,
  srcSet,
  stepImages,
  type ImageEntry,
  type Variant,
  type VideoEntry,
} from "./site-media";

const variants: Variant[] = [
  { file: "/site/hero-1600.webp", width: 1600, height: 900 },
  { file: "/site/hero-640.avif", width: 640, height: 360 },
  { file: "/site/hero-640.webp", width: 640, height: 360 },
  { file: "/site/hero-1600.avif", width: 1600, height: 900 },
];
const img = (slug: string): ImageEntry => ({ alt: "", variants: [{ file: `/site/${slug}-400.webp`, width: 400, height: 300 }] });
const video: VideoEntry = {
  alt: "",
  width: 1920,
  height: 1080,
  duration: 7.96,
  sources: [{ file: "/site/hero-loop.webm", type: "video/webm" }],
  poster: [{ file: "/site/hero-loop-poster-768.webp", width: 768, height: 432 }],
};
const ok = { wide: true, reducedMotion: false, saveData: false, effectiveType: "4g" };

describe("site-media", () => {
  it("monta srcset por formato, em ordem crescente, e usa o maior WebP como fallback", () => {
    expect(srcSet(variants, "avif")).toBe("/site/hero-640.avif 640w, /site/hero-1600.avif 1600w");
    expect(srcSet(variants, "webp")).toBe("/site/hero-640.webp 640w, /site/hero-1600.webp 1600w");
    expect(largestWebp(variants)?.file).toBe("/site/hero-1600.webp");
    expect(largestWebp([])).toBeUndefined();
  });

  it("pôster do hero: quadro 0 do vídeo, senão a imagem I1, senão só texto", () => {
    expect(heroPoster({ "hero-modelo-vazado": img("i1") }, { "hero-loop": video })).toEqual({ poster: video.poster, video, narrow: img("i1").variants });
    expect(heroPoster({ "hero-modelo-vazado": img("i1") }, {})?.poster[0].file).toBe("/site/i1-400.webp");
    expect(heroPoster({}, {})).toBeNull();
  });

  it("tríptico: os três, só I3 maior ou só texto (ordem de corte do §10)", () => {
    const all = { "passo-1-modelo": img("a"), "passo-2-campos": img("b"), "passo-3-gerado": img("c") };
    expect(stepImages(all).mode).toBe("three");
    expect(stepImages({ "passo-2-campos": img("b") })).toEqual({ mode: "middle", item: img("b") });
    expect(stepImages({ "passo-1-modelo": img("a"), "passo-3-gerado": img("c") }).mode).toBe("none");
  });

  it("cards de recursos: as três imagens juntas ou nenhuma", () => {
    const two = { "recurso-lote": img("l"), "recurso-kits": img("k") };
    expect(featureImages(two)).toBeNull();
    expect(featureImages({ ...two, "recurso-historico": img("h") })).toHaveLength(3);
  });

  it("vídeo só com largura ≥ 768, sem reduzir movimento, sem Save-Data e fora de 2g/3g", () => {
    expect(canLoadVideo(ok)).toBe(true);
    expect(canLoadVideo({ ...ok, effectiveType: undefined })).toBe(true);
    for (const env of [
      { ...ok, wide: false },
      { ...ok, reducedMotion: true },
      { ...ok, saveData: true },
      { ...ok, effectiveType: "3g" },
      { ...ok, effectiveType: "slow-2g" },
    ]) {
      expect(canLoadVideo(env), JSON.stringify(env)).toBe(false);
    }
  });

  it("aceita só arquivos da própria origem em /site/", () => {
    expect(isSameOriginAsset("/site/hero-loop.mp4")).toBe(true);
    for (const bad of ["https://cdn.example/x.mp4", "//cdn.example/x.mp4", "/site/../x.mp4", "/outra/x.mp4", "data:video/mp4;base64,AA"]) {
      expect(isSameOriginAsset(bad), bad).toBe(false);
    }
  });

  it("todo arquivo dos JSONs gerados é da própria origem", () => {
    const entries = [
      ...Object.values(media.images as Record<string, ImageEntry>),
      ...Object.values(captures as Record<string, ImageEntry>),
    ];
    const files = [
      ...entries.flatMap((i) => i.variants.map((v) => v.file)),
      ...Object.values(media.videos as Record<string, VideoEntry>).flatMap((v) => [
        ...v.sources.map((s) => s.file),
        ...v.poster.map((p) => p.file),
      ]),
    ];
    expect(files.every(isSameOriginAsset)).toBe(true);
  });
});
