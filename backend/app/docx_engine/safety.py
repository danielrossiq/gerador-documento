"""Validação de segurança de arquivos .docx antes de qualquer processamento.

Proteções: tipo real (magia do ZIP + estrutura OOXML), tamanho, ZIP bomb (razão de compressão e
tamanho descomprimido), path traversal, criptografia, macros VBA e executáveis embutidos.
Nada é executado: apenas inspecionamos o ZIP.
"""

from __future__ import annotations

import io
import zipfile
import zlib
from dataclasses import dataclass

MAX_ENTRIES = 3000
MAX_ENTRY_BYTES = 80 * 1024 * 1024
MAX_TOTAL_BYTES = 250 * 1024 * 1024
MAX_RATIO = 150  # descomprimido / comprimido, para entradas grandes
RATIO_MIN_SIZE = 1 * 1024 * 1024
BLOCKED_EXT = (".exe", ".dll", ".bat", ".cmd", ".com", ".scr", ".msi", ".vbs", ".ps1", ".js", ".jar", ".sh")
MAIN_CT = "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"


class DocxRejected(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class DocxInfo:
    entries: int
    total_uncompressed: int
    has_images: bool
    has_headers: bool


def validate_docx(
    data: bytes,
    *,
    filename: str,
    max_bytes: int,
    max_entries: int = MAX_ENTRIES,
    max_entry_bytes: int = MAX_ENTRY_BYTES,
    max_total_bytes: int = MAX_TOTAL_BYTES,
) -> DocxInfo:
    """Limites menores (`max_*`) para entrada anônima: o teste grátis da landing (D38) usa 25 MB descompactados."""
    if not filename.lower().endswith(".docx"):
        raise DocxRejected("INVALID_EXTENSION", "Envie um arquivo com extensão .docx.")
    if len(data) == 0:
        raise DocxRejected("EMPTY_FILE", "O arquivo está vazio.")
    if len(data) > max_bytes:
        raise DocxRejected("FILE_TOO_LARGE", f"O arquivo excede o limite de {max_bytes // (1024 * 1024)} MB.")
    if not data.startswith(b"PK\x03\x04"):
        raise DocxRejected(
            "NOT_A_DOCX",
            "O arquivo não é um .docx válido (pode ser um .doc antigo, protegido por senha ou de outro tipo).",
        )
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise DocxRejected("CORRUPT_ZIP", "O arquivo está corrompido ou não é um .docx válido.") from exc

    infos = zf.infolist()
    if len(infos) > max_entries:
        raise DocxRejected(
            "TOO_MANY_ENTRIES", "O arquivo contém partes demais para ser processado com segurança."
        )

    total = 0
    names: set[str] = set()
    for info in infos:
        name = info.filename
        norm = name.replace("\\", "/")
        if norm.startswith("/") or ".." in norm.split("/") or ":" in norm.split("/")[0]:
            raise DocxRejected("UNSAFE_PATH", "O arquivo contém caminhos internos inseguros.")
        if info.flag_bits & 0x1:
            raise DocxRejected("ENCRYPTED", "Arquivos protegidos por senha não são suportados.")
        if info.file_size > max_entry_bytes:
            raise DocxRejected("ENTRY_TOO_LARGE", "Uma parte do arquivo é grande demais.")
        if (
            info.compress_size > 0
            and info.file_size >= RATIO_MIN_SIZE
            and info.file_size / info.compress_size > MAX_RATIO
        ):
            raise DocxRejected("ZIP_BOMB", "O arquivo tem taxa de compressão suspeita e foi recusado.")
        total += info.file_size
        if total > max_total_bytes:
            raise DocxRejected("ZIP_BOMB", "O conteúdo descomprimido excede o limite permitido.")
        lname = norm.lower()
        if lname.endswith("vbaproject.bin") or lname.endswith("vbadata.xml") or "/macrosheets/" in lname:
            raise DocxRejected("MACROS_NOT_ALLOWED", "Documentos com macros não são aceitos.")
        if lname.endswith(BLOCKED_EXT):
            raise DocxRejected(
                "EXECUTABLE_CONTENT", "O arquivo contém conteúdo executável embutido e foi recusado."
            )
        names.add(norm)

    if "[Content_Types].xml" not in names or "word/document.xml" not in names:
        raise DocxRejected(
            "NOT_A_DOCX", "A estrutura interna não corresponde a um documento do Word (.docx)."
        )

    try:
        ct = zf.read("[Content_Types].xml")
    except (zipfile.BadZipFile, RuntimeError, zlib.error, EOFError) as exc:  # parte comprimida corrompida (QA-1)
        raise DocxRejected("CORRUPT_ZIP", "O arquivo está corrompido.") from exc
    lowered = ct.lower()
    if b"macroenabled" in lowered or b"vbaproject" in lowered:
        raise DocxRejected("MACROS_NOT_ALLOWED", "Documentos com macros não são aceitos.")
    if MAIN_CT.encode() not in ct:
        raise DocxRejected("NOT_A_DOCX", "O arquivo não é um documento do Word (.docx) padrão.")

    return DocxInfo(
        entries=len(infos),
        total_uncompressed=total,
        has_images=any(n.startswith("word/media/") for n in names),
        has_headers=any(n.startswith(("word/header", "word/footer")) for n in names),
    )


def validate_zip_container(data: bytes, *, max_bytes: int) -> None:
    """Proteções genéricas para pacotes OOXML que não são .docx (ex.: .xlsx enviado para importação)."""
    if len(data) > max_bytes:
        raise DocxRejected("FILE_TOO_LARGE", f"O arquivo excede o limite de {max_bytes // (1024 * 1024)} MB.")
    if not data.startswith(b"PK"):
        raise DocxRejected("NOT_A_XLSX", "O arquivo não é uma planilha .xlsx válida.")
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise DocxRejected("CORRUPT_ZIP", "O arquivo está corrompido.") from exc
    total = 0
    for info in zf.infolist():
        norm = info.filename.replace("\\", "/")
        if norm.startswith("/") or ".." in norm.split("/"):
            raise DocxRejected("UNSAFE_PATH", "O arquivo contém caminhos internos inseguros.")
        if info.file_size > MAX_ENTRY_BYTES or (
            info.compress_size > 0
            and info.file_size >= RATIO_MIN_SIZE
            and info.file_size / info.compress_size > MAX_RATIO
        ):
            raise DocxRejected("ZIP_BOMB", "O arquivo tem taxa de compressão suspeita e foi recusado.")
        total += info.file_size
        lname = norm.lower()
        if lname.endswith("vbaproject.bin"):
            raise DocxRejected("MACROS_NOT_ALLOWED", "Planilhas com macros não são aceitas.")
    if total > MAX_TOTAL_BYTES:
        raise DocxRejected("ZIP_BOMB", "O conteúdo descomprimido excede o limite permitido.")
