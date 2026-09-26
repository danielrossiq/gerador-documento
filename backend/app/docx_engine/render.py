"""Renderização: substitui os runs-token do gabarito compilado pelos valores formatados."""

from __future__ import annotations

import io
import re
import zipfile
from collections.abc import Mapping

from lxml import etree

from app.docx_engine.compile import TOKEN_CLOSE, TOKEN_OPEN
from app.docx_engine.ooxml import PART_RE, local, make_text_children, parse_xml, to_bytes, w

TOKEN_RE = re.compile(rf"^{TOKEN_OPEN}F:([0-9a-f]{{8}}):([a-z][a-z0-9_]{{0,63}}){TOKEN_CLOSE}$")
_TOKEN_BYTES = (TOKEN_OPEN + "F:").encode()


def _is_token_part(name: str) -> bool:
    return name == "word/document.xml" or bool(PART_RE.match(name))


class CompiledTemplate:
    """Gabarito carregado uma vez em memória; `render` é barato o bastante para lotes grandes."""

    def __init__(self, data: bytes) -> None:
        zf = zipfile.ZipFile(io.BytesIO(data))
        self._infos = zf.infolist()
        self._blobs = {i.filename: zf.read(i.filename) for i in self._infos}
        self._token_parts = [n for n, b in self._blobs.items() if _is_token_part(n) and _TOKEN_BYTES in b]

    def field_names(self) -> set[str]:
        names: set[str] = set()
        for part in self._token_parts:
            root = parse_xml(self._blobs[part])
            for t in root.iter(w("t")):
                if t.text and (m := TOKEN_RE.match(t.text)):
                    names.add(m.group(2))
        return names

    def render(self, values: Mapping[str, str]) -> bytes:
        replaced: dict[str, bytes] = {}
        for part in self._token_parts:
            root = parse_xml(self._blobs[part])
            _replace_tokens(root, values)
            replaced[part] = to_bytes(root)
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
            for info in self._infos:
                zi = zipfile.ZipInfo(info.filename, date_time=info.date_time)
                zi.compress_type = zipfile.ZIP_DEFLATED
                zi.external_attr = info.external_attr
                zout.writestr(zi, replaced.get(info.filename, self._blobs[info.filename]))
        return out.getvalue()


def _replace_tokens(root: etree._Element, values: Mapping[str, str]) -> None:
    for run in root.iter(w("r")):
        content = [c for c in run if local(c) not in (None, "rPr")]
        if len(content) != 1 or local(content[0]) != "t":
            continue
        m = TOKEN_RE.match(content[0].text or "")
        if not m:
            continue
        value = values.get(m.group(2), "")
        run.remove(content[0])
        make_text_children(value, run)
