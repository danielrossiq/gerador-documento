"""Sondagem do teste grátis (D38) no stack local: fluxo completo, arquivos estranhos, claim e limites.

    TRIAL_LIMIT_IP_HOUR=10000 TRIAL_LIMIT_IP_DAY=10000 TRIAL_LIMIT_NET_DAY=10000 scripts/stack_local.sh restart-api
    python scripts/stress/trial_probe.py files      # arquivos estranhos (precisa de limites altos)
    python scripts/stress/trial_probe.py claim      # claim: antes de pronto, duplo, outro usuário, concorrente
    python scripts/stress/trial_probe.py limits     # limites PADRÃO (reinicie a API sem as variáveis acima)
    python scripts/stress/trial_probe.py dense      # pior caso de CPU dentro do teto de 40 mil caracteres

Cada linha: o que foi enviado → status HTTP, código e status final do teste (com o tempo até terminar).
"""

from __future__ import annotations

import asyncio
import io
import sys
import time
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import httpx
import payloads as P
from lib import API, WEB, Session, fake_email, random_ip

DOCX_CT = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


async def send(c: httpx.AsyncClient, data: bytes, name: str = "contrato.docx", **form: str) -> httpx.Response:
    return await c.post("/api/v1/public/trials", files={"file": (name, data, DOCX_CT)}, data=form or {"website": ""})


async def wait(c: httpx.AsyncClient, token: str, secs: float = 120) -> tuple[dict, float]:
    t = time.perf_counter()
    while time.perf_counter() - t < secs:
        r = await c.get(f"/api/v1/public/trials/{token}")
        if r.status_code != 200:
            return {"http": r.status_code, "code": (r.json().get("error") or {}).get("code")}, time.perf_counter() - t
        j = r.json()
        if j["status"] in ("done", "failed"):
            return j, time.perf_counter() - t
        await asyncio.sleep(0.3)
    return {"status": "timeout"}, time.perf_counter() - t


def _code(r: httpx.Response) -> str:
    try:
        return str((r.json().get("error") or {}).get("code") or "")
    except ValueError:
        return r.text[:80]


async def probe(c: httpx.AsyncClient, label: str, data: bytes, name: str = "contrato.docx", **form: str) -> dict:
    t = time.perf_counter()
    r = await send(c, data, name, **form)
    took = time.perf_counter() - t
    line = f"{label:<46} {len(data) // 1024:>6} KB -> {r.status_code} {_code(r):<22} ({took:.1f}s)"
    out: dict = {"http": r.status_code}
    if r.status_code == 202:
        j, secs = await wait(c, r.json()["token"])
        res = j.get("result") or {}
        err = (j.get("error") or {}).get("code") or j.get("code") or ""
        line += f" final={j.get('status', j.get('http'))} {err} campos={len(res.get('fields') or [])} ia={j.get('ai')} em {secs:.1f}s"
        out = {**j, "token": r.json()["token"]}
    print(line, flush=True)
    return out


def docx_with_pages(paragraphs: list[str], pages: int) -> bytes:
    data = P.docx_from_paragraphs(paragraphs)
    app = (
        '<?xml version="1.0" encoding="UTF-8"?><Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/'
        f'extended-properties"><Pages>{pages}</Pages></Properties>'
    )
    buf = io.BytesIO(data)
    with zipfile.ZipFile(buf, "a") as z:
        z.writestr("docProps/app.xml", app)
    return buf.getvalue()


def corrupt_member(data: bytes, name: str) -> bytes:
    zf = zipfile.ZipFile(io.BytesIO(data))
    info = zf.getinfo(name)
    raw = bytearray(data)
    start = info.header_offset + 30 + len(info.filename.encode()) + len(info.extra)
    for i in range(start + 2, start + info.compress_size - 2):
        raw[i] ^= 0x5A
    return bytes(raw)


async def files(base: str) -> None:
    async with httpx.AsyncClient(base_url=base, timeout=180) as c:
        await probe(c, "demo .docx", P.demo_docx())
        await probe(c, "PDF digitado", P.typed_pdf(), "contrato.pdf")
        await probe(c, "PDF escaneado 3 pág.", P.scanned_pdf(3), "escaneado.pdf")
        await probe(c, "PDF escaneado 12 pág.", P.scanned_pdf(12, side=900), "longo.pdf")
        await probe(c, "PDF com nome .docx", P.typed_pdf(), "contrato.docx")
        await probe(c, ".docx com nome .pdf", P.demo_docx(), "contrato.pdf")
        await probe(c, ".doc antigo (OLE)", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + bytes(4000), "contrato.doc")
        await probe(c, "executável renomeado", b"MZ\x90\x00" + bytes(4000), "contrato.docx")
        await probe(c, "zip qualquer (não docx)", _plain_zip(), "contrato.docx")
        await probe(c, "docx corrompido (bytes trocados)", P.corrupt_docx())
        await probe(c, "docx cortado ao meio", P.truncated_docx())
        await probe(c, "docx parte [Content_Types] corrompida", corrupt_member(_ct_big_docx(), "[Content_Types].xml"))
        await probe(c, "docx document.xml corrompido", corrupt_member(P.docx_from_paragraphs(["Contrato. " * 300]), "word/document.xml"))
        await probe(c, "zip bomb 200 MB", P.zip_bomb_docx())
        await probe(c, "zip bomb 240 x (1 MB-1)", P.sub_threshold_bomb_docx())
        await probe(c, "docx com DTD/entidades", P.entity_docx())
        await probe(c, "docx 4,9 MB (mídia)", P.docx_from_paragraphs([P.contract_paragraph(1)], {"word/media/a.bin": bytes(1) + __import__("os").urandom(int(4.9 * 1024 * 1024))}))
        await probe(c, "docx 5,5 MB (acima)", P.big_media_docx(6))
        await probe(c, "docx 300 parágrafos (~10 pág.)", P.many_paragraphs_docx(300))
        await probe(c, "docx 2.000 parágrafos (acima de 40 mil car.)", P.many_paragraphs_docx(2000))
        await probe(c, "docx Pages=1 mas 60 mil caracteres", docx_with_pages([P.contract_paragraph(i) for i in range(350)], 1))
        await probe(c, "docx Pages=50 com 1 parágrafo", docx_with_pages(["Contrato curto, CPF 529.982.247-25."], 50))
        await probe(c, "docx só com espaços", P.docx_from_paragraphs(["   ", ""]))
        await probe(c, "arquivo vazio", b"")
        r = await c.post("/api/v1/public/trials", content=b"x" * 100, headers={"Content-Type": "multipart/form-data; boundary=zzz"})
        print(f"{'multipart quebrado':<46} -> {r.status_code} {_code(r)}")
        r = await c.post("/api/v1/public/trials", data={"file": "texto no lugar do arquivo", "website": ""})
        print(f"{'campo file como texto':<46} -> {r.status_code} {_code(r)}")
        two = [("file", ("a.docx", P.demo_docx(), DOCX_CT)), ("file", ("b.docx", P.demo_docx(), DOCX_CT))]
        r = await c.post("/api/v1/public/trials", files=two)
        print(f"{'dois arquivos no mesmo envio':<46} -> {r.status_code} {_code(r)}")

        async def chunked():
            yield b"--zzz\r\nContent-Disposition: form-data; name=\"file\"; filename=\"a.docx\"\r\n\r\n"
            yield P.demo_docx()
            yield b"\r\n--zzz--\r\n"

        r = await c.post("/api/v1/public/trials", content=chunked(), headers={"Content-Type": "multipart/form-data; boundary=zzz"})
        print(f"{'envio chunked (sem Content-Length)':<46} -> {r.status_code} {_code(r)}")
        r = await c.post("/api/v1/public/trials", files={"file": ("a.docx", P.demo_docx(), DOCX_CT)}, data={"website": "http://spam"})
        tok = r.json().get("token")
        st = await c.get(f"/api/v1/public/trials/{tok}")
        print(f"{'armadilha preenchida':<46} -> {r.status_code} token={bool(tok)}; consulta do token -> {st.status_code} {_code(st)}")


def _plain_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("leia.txt", "oi")
    return buf.getvalue()


def _ct_big_docx() -> bytes:
    data = P.docx_from_paragraphs(["Contrato de teste."])
    buf = io.BytesIO()
    src = zipfile.ZipFile(io.BytesIO(data))
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for info in src.infolist():
            body = src.read(info)
            if info.filename == "[Content_Types].xml":
                body = body.replace(b"</Types>", b"<!--" + b"x" * 3000 + b"--></Types>")
            z.writestr(info.filename, body)
    return buf.getvalue()


async def claim(base: str) -> None:
    async with httpx.AsyncClient(base_url=base, timeout=120) as anon:
        r = await send(anon, P.demo_docx())
        token = r.json()["token"]
        a = Session(base, xff=random_ip())
        await a.register(fake_email("claim"))
        early = await a.post(f"/trials/{token}/claim")
        print(f"claim antes de terminar          -> {early.status_code} {_code(early)}")
        j, _ = await wait(anon, token)
        print(f"teste terminou: {j.get('status')} campos={len((j.get('result') or {}).get('fields') or [])}")
        b = Session(base, xff=random_ip())
        await b.register(fake_email("claim"))
        both = await asyncio.gather(a.post(f"/trials/{token}/claim"), b.post(f"/trials/{token}/claim"))
        print(f"claim simultâneo (A e B)         -> {[x.status_code for x in both]} {[_code(x) for x in both]}")
        again = await a.post(f"/trials/{token}/claim")
        print(f"claim de novo                    -> {again.status_code} {_code(again)}")
        st = await anon.get(f"/api/v1/public/trials/{token}")
        print(f"status do teste após o claim     -> {st.status_code} {_code(st)}")
        winner = a if both[0].status_code == 201 else b
        gid = (both[0] if both[0].status_code == 201 else both[1]).json()["generator_id"]
        sug = await winner.get(f"/generators/{gid}/suggestions")
        print(f"sugestões no modelo criado       -> {sug.status_code} itens={len(sug.json().get('items') or [])}")
        loser = b if winner is a else a
        peek = await loser.get(f"/generators/{gid}")
        print(f"outro usuário abre o modelo      -> {peek.status_code}")
        anon_claim = await anon.post(f"/api/v1/trials/{token}/claim")
        print(f"claim sem sessão                 -> {anon_claim.status_code} {_code(anon_claim)}")
        bad = await a.post("/trials/" + "x" * 43 + "/claim")
        print(f"claim de token inexistente       -> {bad.status_code} {_code(bad)}")
        for s in (a, b):
            await s.client.aclose()


async def limits(base: str) -> None:
    """Limites padrão (3/h por IP). Rode logo depois de reiniciar a API sem TRIAL_LIMIT_*."""
    async with httpx.AsyncClient(base_url=base, timeout=60) as c:
        for i in range(5):
            r = await send(c, P.demo_docx())
            print(f"envio {i + 1} mesmo IP            -> {r.status_code} {_code(r)}")
            if r.status_code == 202:
                await wait(c, r.json()["token"])
        for _ in range(3):
            r = await c.post("/api/v1/public/trials", files={"file": ("a.docx", P.demo_docx(), DOCX_CT)}, headers={"X-Forwarded-For": random_ip()})
            print(f"envio com X-Forwarded-For falso   -> {r.status_code} {_code(r)}  ({base})")


async def dense(base: str) -> None:
    """Muitos achados por caractere: ~39 mil caracteres só de datas/CPFs/valores (o teto é 10 pág. x 4 mil)."""
    async with httpx.AsyncClient(base_url=base, timeout=300) as c:
        tokens = ["01/02/2027", "529.982.247-25", "R$ 1,00", "01310-100"]
        para = " ".join(tokens * 4)  # ~150 caracteres, 16 achados
        for n in (100, 250):
            await probe(c, f"docx denso {n} parágrafos ({n * 16} achados)", P.docx_from_paragraphs([para] * n))
        one = " ".join(tokens * 900)  # um parágrafo só, ~38 mil caracteres, 3.600 achados
        await probe(c, "docx denso 1 parágrafo (3.600 achados)", P.docx_from_paragraphs([one]))


def main() -> int:
    what = sys.argv[1] if len(sys.argv) > 1 else "files"
    base = WEB if "--via-web" in sys.argv else API
    asyncio.run({"files": files, "claim": claim, "limits": limits, "dense": dense}[what](base))
    return 0


if __name__ == "__main__":
    sys.exit(main())
