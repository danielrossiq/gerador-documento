"""Codifica a gravação de scripts/site_video.cjs para a landing: corta o carregamento inicial, gera MP4 (H.264,
faststart), WebM (VP9) e o pôster, publica em frontend/public/site/ e atualiza o manifesto (site-assets.json).

Uso: python scripts/site_video_encode.py   (precisa do ffmpeg no PATH)
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "scripts" / ".media-originals" / "video"
PUBLIC = ROOT / "frontend" / "public" / "site"
MANIFEST = ROOT / "frontend" / "src" / "components" / "site" / "site-assets.json"
TITLE = "Demonstração do Minuta: do contrato enviado ao PDF pronto, com a IA achando os campos, preenchendo e revisando"


def ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


def has_encoder(name: str) -> bool:
    out = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True).stdout
    return f" {name} " in out


def main() -> None:
    if not shutil.which("ffmpeg"):
        raise SystemExit("ffmpeg não encontrado no PATH")
    steps = {s["name"]: s["t"] for s in json.loads((SRC / "demo-steps.json").read_text(encoding="utf-8"))["steps"]}
    start = max(0.0, steps["inicio"] - 0.2)
    end = steps["fim"]
    poster_at = steps["preencheu"] + 2.5 - start
    raw = SRC / "demo-raw.webm"
    PUBLIC.mkdir(parents=True, exist_ok=True)
    mp4, webm, poster = PUBLIC / "demo.mp4", PUBLIC / "demo.webm", PUBLIC / "demo-poster.jpg"
    cut = ["-ss", f"{start:.2f}", "-to", f"{end:.2f}", "-i", str(raw)]
    ffmpeg(*cut, "-an", "-c:v", "libx264", "-preset", "slow", "-crf", "24", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(mp4))
    has_webm = has_encoder("libvpx-vp9")
    if has_webm:
        ffmpeg(*cut, "-an", "-c:v", "libvpx-vp9", "-crf", "36", "-b:v", "0", "-row-mt", "1", "-deadline", "good", str(webm))
        # o navegador pega a 1ª fonte que entende: WebM só vale a pena se for menor que o MP4
        if webm.stat().st_size >= mp4.stat().st_size:
            webm.unlink()
            has_webm = False
    ffmpeg("-ss", f"{poster_at:.2f}", "-i", str(mp4), "-frames:v", "1", "-q:v", "3", str(poster))
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height:format=duration", "-of", "json", str(mp4)],
        capture_output=True, text=True, check=True,
    )
    info = json.loads(probe.stdout)
    w, h = info["streams"][0]["width"], info["streams"][0]["height"]
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    manifest["video"] = {
        "mp4": "/site/demo.mp4",
        **({"webm": "/site/demo.webm"} if has_webm else {}),
        "poster": "/site/demo-poster.jpg",
        "width": w,
        "height": h,
        "title": TITLE,
    }
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    sizes = {p.name: f"{p.stat().st_size / 1e6:.2f} MB" for p in (mp4, webm, poster) if p.exists()}
    print(f"{float(info['format']['duration']):.1f}s {w}x{h}", sizes)


if __name__ == "__main__":
    main()
