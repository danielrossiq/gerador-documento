"""Cenários de estresse contra o stack local (scripts/stack_local.sh up). Tudo com a IA FALSA.

    python scripts/stress/run.py limits                 limites de login/cadastro (com e sem X-Forwarded-For falso)
    python scripts/stress/run.py upload [-c 10 -n 30]   upload de modelo: carga + arquivos estranhos
    python scripts/stress/run.py fill-text [-c 20 -n 100 --ai-latency 1500]
    python scripts/stress/run.py fill-files [-c 10 -n 40]
    python scripts/stress/run.py batch                  planilha grande, lote de 1000 linhas, planilha "bomba"
    python scripts/stress/run.py baseline               todos acima, versões curtas
    python scripts/stress/run.py trial [-c 30 -n 60]    teste grátis da landing (D38), quando existir

Endereços pelo ambiente: STRESS_API (padrão http://127.0.0.1:8150), STRESS_AI (http://127.0.0.1:8151),
STRESS_WEB (http://127.0.0.1:3350; `--via-web` manda pelo proxy do Next). Resultados em
backend/data/stack/stress/*.json (fora do git) e uma linha por cenário na saída.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import payloads as P
from lib import (
    API,
    WEB,
    Result,
    Session,
    ai_control,
    ai_reset,
    fake_email,
    random_ip,
    run,
    save,
)

DOCX_CT = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


async def _demo_session(base: str) -> Session:
    s = Session(base)
    r = await s.login()
    assert r.status_code == 200, f"login demo falhou ({r.status_code}): rode scripts/stack_local.sh seed"
    return s


async def _fresh_session(base: str, xff: str | None = None) -> Session:
    """Conta nova (cota de IA zerada). Usa um IP falso só para não esbarrar no limite de cadastro."""
    s = Session(base, xff=xff or random_ip())
    r = await s.register(fake_email("estresse"))
    assert r.status_code == 201, r.text
    return s


async def _usable_generator(s: Session, fields: int = 7) -> str:
    g = await s.post("/generators", json={"name": f"Estresse {time.time():.0f}"})
    gid = g.json()["id"]
    up = await s.post(f"/generators/{gid}/template", files={"file": ("contrato.docx", P.demo_docx(), DOCX_CT)})
    assert up.status_code == 201, up.text
    labels = [
        ("Nome do contratante", "text_short"), ("CPF do contratante", "cpf"), ("Valor mensal", "currency"),
        ("Data de início", "date"), ("CEP", "cep"), ("E-mail", "email"), ("Telefone", "phone"),
    ]
    for label, typ in labels[:fields]:
        await s.post(f"/generators/{gid}/fields", json={"label": label, "type": typ})
    return gid


def _print(results: list[Result]) -> None:
    for r in results:
        print(r.line(), flush=True)


# ------------------------------------------------------------------ limites


async def scen_limits(args: argparse.Namespace) -> list[Result]:
    base = args.base
    out: list[Result] = []
    email = "demo@docfeito.com.br"

    async def login_same_ip(i: int):
        async with Session(base) as s:
            return await s.client.post("/api/v1/auth/login", json={"email": f"x{i}@exemplo.test", "password": "errada-123"})

    out.append(await run("login 40x mesmo IP (lim 20/min)", login_same_ip, requests=40, concurrency=5))

    async def login_spoof(i: int):
        async with Session(base, xff=random_ip()) as s:
            return await s.client.post("/api/v1/auth/login", json={"email": f"y{i}@exemplo.test", "password": "errada-123"})

    out.append(await run("login 40x X-Forwarded-For falso", login_spoof, requests=40, concurrency=5))

    async def login_user(i: int):
        async with Session(base, xff=random_ip()) as s:
            return await s.client.post("/api/v1/auth/login", json={"email": email, "password": "errada-123"})

    out.append(await run("login 15x mesmo e-mail, IPs falsos", login_user, requests=15, concurrency=3))

    async def reg_same(i: int):
        async with Session(base) as s:
            return await s.client.post("/api/v1/auth/register", json={"name": "Pessoa", "email": fake_email("lim"), "password": "senha-forte-123"})

    out.append(await run("cadastro 15x mesmo IP (lim 10/h)", reg_same, requests=15, concurrency=3))

    async def reg_spoof(i: int):
        async with Session(base, xff=random_ip()) as s:
            return await s.client.post("/api/v1/auth/register", json={"name": "Pessoa", "email": fake_email("lim"), "password": "senha-forte-123"})

    out.append(await run("cadastro 30x X-Forwarded-For falso", reg_spoof, requests=30, concurrency=5))
    return out


# ------------------------------------------------------------------ upload de modelo


async def scen_upload(args: argparse.Namespace) -> list[Result]:
    s = await _fresh_session(args.base)
    out: list[Result] = []
    gid = (await s.post("/generators", json={"name": "Uploads"})).json()["id"]

    async def up(data: bytes, name: str = "contrato.docx", ct: str = DOCX_CT):
        return await s.post(f"/generators/{gid}/template", files={"file": (name, data, ct)})

    out.append(await run("upload demo .docx", lambda i: up(P.demo_docx()), requests=args.n, concurrency=args.c, memory=True))
    weird = [
        ("docx 2.000 parágrafos", lambda: P.many_paragraphs_docx(2000), "contrato.docx"),
        ("docx 20.000 parágrafos", lambda: P.many_paragraphs_docx(20000), "contrato.docx"),
        ("docx 14 MB (mídia)", lambda: P.big_media_docx(14), "contrato.docx"),
        ("docx 16 MB (acima do teto)", lambda: P.big_media_docx(16), "contrato.docx"),
        ("zip bomb 200 MB", P.zip_bomb_docx, "contrato.docx"),
        ("zip bomb 240x(1 MB-1)", P.sub_threshold_bomb_docx, "contrato.docx"),
        ("docx corrompido", P.corrupt_docx, "contrato.docx"),
        ("docx cortado ao meio", P.truncated_docx, "contrato.docx"),
        ("docx com DTD/entidades", P.entity_docx, "contrato.docx"),
        ("PDF com extensão .docx", P.fake_pdf_with_docx_ext, "contrato.docx"),
        ("PDF escaneado 3 pág.", lambda: P.scanned_pdf(3), "escaneado.pdf"),
        ("arquivo vazio", lambda: b"", "contrato.docx"),
    ]
    for label, make, name in weird:
        data = make()
        r = await run(f"upload {label} ({len(data) // 1024} KB)", lambda i, d=data, n=name: up(d, n), requests=1, concurrency=1, memory=True)
        out.append(r)
    if args.big:
        data = P.many_paragraphs_docx(100_000)
        out.append(await run(f"upload docx 100.000 parágrafos ({len(data) // 1024} KB)", lambda i: up(data), requests=1, concurrency=1, memory=True))
    return out


# ------------------------------------------------------------------ preencher com IA


async def scen_fill_text(args: argparse.Namespace) -> list[Result]:
    ai_control(latency_ms=args.ai_latency, jitter_ms=args.ai_latency // 5, rate_429=0, rate_500=0)
    s = await _fresh_session(args.base)
    gid = await _usable_generator(s)
    text = (
        "Oi! Sou a Maria Ficticia Souza, CPF 529.982.247-25, moro na Rua das Flores, 10, CEP 01310-100. "
        "O valor combinado é R$ 3.200,00 por mês a partir de 15/11/2026. maria@exemplo.test (11) 98765-4321"
    )

    async def fill(i: int):
        return await s.post(f"/generators/{gid}/assist/fill", json={"text": text})

    out = [await run(f"fill texto (IA {args.ai_latency} ms)", fill, requests=args.n, concurrency=args.c)]
    ai_control(rate_429=0.3, rate_500=0.1)
    out.append(await run("fill texto com 30% 429 + 10% 500", fill, requests=min(args.n, 40), concurrency=args.c))
    ai_control(rate_429=0, rate_500=0, rate_truncate=0.5)
    out.append(await run("fill texto com 50% resposta cortada", fill, requests=min(args.n, 40), concurrency=args.c))
    ai_control(rate_truncate=0, latency_ms=300, jitter_ms=50)
    big = text * 400  # ~100 mil caracteres (a API aceita até 20 mil: deve recusar com 422)
    out.append(await run("fill texto de 100 mil caracteres", lambda i: s.post(f"/generators/{gid}/assist/fill", json={"text": big}), requests=3, concurrency=3))
    return out


async def scen_fill_files(args: argparse.Namespace) -> list[Result]:
    ai_control(latency_ms=args.ai_latency, jitter_ms=args.ai_latency // 5)
    s = await _fresh_session(args.base)
    gid = await _usable_generator(s)
    luz, ficha = P.fixture("conta_de_luz_ficticia.jpg"), P.fixture("ficha_cadastral_ficticia.jpg")

    def files(*items: tuple[str, bytes, str]):
        return [("files", it) for it in items]

    async def send(fs):
        return await s.post(f"/generators/{gid}/assist/fill-files", files=fs)

    out = [await run("fill-files 2 fotos fictícias", lambda i: send(files(("a.jpg", luz, "image/jpeg"), ("b.jpg", ficha, "image/jpeg"))), requests=args.n, concurrency=args.c, memory=True)]
    noisy = P.noisy_photo(2400, 1800)
    out.append(await run(f"fill-files 4 fotos ruidosas ({len(noisy) // 1024} KB cada)", lambda i: send(files(*[(f"{k}.jpg", noisy, "image/jpeg") for k in range(4)])), requests=max(4, args.n // 4), concurrency=min(args.c, 4), memory=True))
    single = [
        ("foto 6000x8000 lisa (48 Mpx)", [("f.png", P.png_dimensions(6000, 8000), "image/png")]),
        ("foto 8000x8000 (64 Mpx, acima)", [("f.png", P.png_dimensions(8000, 8000), "image/png")]),
        ("jpeg corrompido", [("f.jpg", P.corrupt_jpeg(), "image/jpeg")]),
        ("PDF escaneado 3 pág.", [("f.pdf", P.scanned_pdf(3), "application/pdf")]),
        ("5 arquivos (acima de 4)", [(f"{k}.jpg", luz, "image/jpeg") for k in range(5)]),
        ("arquivo 9 MB (acima de 8)", [("f.jpg", b"\xff\xd8\xff" + bytes(9 * 1024 * 1024), "image/jpeg")]),
        ("executável renomeado .jpg", [("f.jpg", b"MZ\x90\x00" + bytes(1000), "image/jpeg")]),
    ]
    for label, items in single:
        out.append(await run(f"fill-files {label}", lambda i, it=items: send(files(*it)), requests=1, concurrency=1, memory=True))
    if args.big:
        # 60 arquivos de 8 MB num só pedido: o servidor só conta os arquivos DEPOIS de receber tudo
        blob = bytes(8 * 1024 * 1024 - 10)
        many = files(*[(f"{k}.jpg", b"\xff\xd8\xff" + blob, "image/jpeg") for k in range(60)])
        out.append(await run("fill-files 60 x 8 MB (480 MB)", lambda i: send(many), requests=1, concurrency=1, memory=True))
        png = P.png_dimensions(6000, 8000)
        out.append(await run("fill-files 4 x 48 Mpx, 4 em paralelo", lambda i: send(files(*[(f"{k}.png", png, "image/png") for k in range(4)])), requests=4, concurrency=4, memory=True))
    return out


# ------------------------------------------------------------------ lote


async def scen_batch(args: argparse.Namespace) -> list[Result]:
    s = await _fresh_session(args.base)
    gid = await _usable_generator(s, fields=4)
    out: list[Result] = []
    xl = P.xlsx_rows(1000)
    out.append(await run(f"importar xlsx 1000 linhas ({len(xl) // 1024} KB)", lambda i: s.post(f"/generators/{gid}/batch/imports", files={"file": ("lote.xlsx", xl, "application/octet-stream")}), requests=5, concurrency=5, memory=True))
    xl2 = P.xlsx_rows(5000)
    out.append(await run("importar xlsx 5000 linhas (acima)", lambda i: s.post(f"/generators/{gid}/batch/imports", files={"file": ("lote.xlsx", xl2, "application/octet-stream")}), requests=1, concurrency=1, memory=True))
    for rows in (500, 2000):
        bomb = P.xlsx_dimension_bomb(rows)
        out.append(await run(f"xlsx 'dimension' A1:XFD{rows} ({len(bomb)} B)", lambda i, b=bomb: s.post(f"/generators/{gid}/batch/imports", files={"file": ("lote.xlsx", b, "application/octet-stream")}), requests=1, concurrency=1, memory=True))
    rows = [{"nome_do_contratante": f"Pessoa {i}", "cpf_do_contratante": P.CPFS_TESTE[i % 4], "valor_mensal": "1.000,00", "data_de_inicio": "01/12/2026"} for i in range(1000)]
    out.append(await run("criar lote 1000 linhas", lambda i: s.post(f"/generators/{gid}/batches", json={"rows": rows}), requests=1, concurrency=1, memory=True))
    return out


# ------------------------------------------------------------------ teste grátis (D38)


async def scen_trial(args: argparse.Namespace) -> list[Result]:
    """POST /public/trials anônimo; consulta o status até terminar. Use com limites altos na API."""
    base = args.base
    data = P.demo_docx()

    async def one(i: int):
        async with Session(base, xff=random_ip() if args.spoof else None) as s:
            r = await s.client.post("/api/v1/public/trials", files={"file": ("contrato.docx", data, DOCX_CT)}, data={"website": ""})
            if r.status_code not in (200, 201, 202):
                return r
            token = r.json()["token"]
            for _ in range(240):
                st = await s.client.get(f"/api/v1/public/trials/{token}")
                if st.status_code != 200 or st.json().get("status") in ("done", "failed"):
                    return st
                await asyncio.sleep(0.5)
            return st

    return [await run("teste grátis (envio + espera)", one, requests=args.n, concurrency=args.c, memory=True)]


SCENARIOS = {
    "limits": scen_limits,
    "upload": scen_upload,
    "fill-text": scen_fill_text,
    "fill-files": scen_fill_files,
    "batch": scen_batch,
    "trial": scen_trial,
}


async def main_async(args: argparse.Namespace) -> int:
    names = ["upload", "fill-files", "fill-text", "batch", "limits"] if args.scenario == "baseline" else [args.scenario]
    all_results: list[Result] = []
    for name in names:
        print(f"== {name}", flush=True)
        res = await SCENARIOS[name](args)
        _print(res)
        all_results += res
    print(f"resultados: {save(all_results, args.scenario)}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    p.add_argument("scenario", choices=[*SCENARIOS, "baseline"])
    p.add_argument("-c", type=int, default=10, help="concorrência")
    p.add_argument("-n", type=int, default=30, help="requisições")
    p.add_argument("--ai-latency", type=int, default=1500, help="latência da IA falsa (ms)")
    p.add_argument("--via-web", action="store_true", help="passa pelo proxy do Next (STRESS_WEB)")
    p.add_argument("--spoof", action="store_true", help="X-Forwarded-For aleatório em cada pedido")
    p.add_argument("--big", action="store_true", help="inclui os casos pesados (100 mil parágrafos, 480 MB…)")
    args = p.parse_args()
    args.base = WEB if args.via_web else API
    ai_reset()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    sys.exit(main())
