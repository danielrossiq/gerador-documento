"""HTTP com os provedores de assinatura, com as travas anti-SSRF da D40 (OBR-13).

* A base URL de cada provedor é fixa no código, por ambiente; nada de URL configurável por espaço de trabalho.
* Sem redirecionamento automático, tempo limite curto.
* URL que vem do provedor (ex.: link do PDF assinado) só é buscada se for https, se o host estiver na lista do
  provedor e se ele não resolver para IP privado, loopback, link-local ou reservado. O download tem teto de tamanho.
"""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable
from urllib.parse import urlsplit

import httpx

from app.modules.signatures.base import ProviderError

TIMEOUT = httpx.Timeout(30.0, connect=10.0)

# os testes trocam por httpx.MockTransport; em produção fica None (transporte padrão do httpx)
_transport: httpx.BaseTransport | None = None


def _system_resolve(host: str) -> list[str]:
    return [str(info[4][0]) for info in socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)]


# resolução de nomes trocável nos testes (sem DNS de verdade). A checagem de IP complementa a lista de hosts do
# provedor (a trava principal): quem controla o DNS desses hosts é o próprio provedor.
resolve: Callable[[str], list[str]] = _system_resolve


def set_transport(transport: httpx.BaseTransport | None) -> None:
    global _transport
    _transport = transport


def client(base_url: str, headers: dict[str, str]) -> httpx.Client:
    return httpx.Client(
        base_url=base_url,
        headers=headers,
        timeout=TIMEOUT,
        follow_redirects=False,
        transport=_transport,
    )


def _host_allowed(host: str, allowed: tuple[str, ...]) -> bool:
    host = host.lower().rstrip(".")
    return any(host == a or (a.startswith(".") and host.endswith(a)) for a in allowed)


def _public_ip(addr: str) -> bool:
    ip = ipaddress.ip_address(addr.split("%", 1)[0])
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


def check_url(url: str, allowed_hosts: tuple[str, ...]) -> str:
    """Confere a URL vinda do provedor antes de buscar. Devolve o host; recusa com ProviderError."""
    parts = urlsplit(url)
    host = parts.hostname or ""
    if parts.scheme != "https" or not host or parts.username or parts.password:
        raise ProviderError("SIGNATURE_UNSAFE_URL")
    if parts.port not in (None, 443):
        raise ProviderError("SIGNATURE_UNSAFE_URL")
    if not _host_allowed(host, allowed_hosts):
        raise ProviderError("SIGNATURE_UNSAFE_URL")
    try:
        addrs = [host] if _is_ip(host) else resolve(host)
    except OSError as exc:
        raise ProviderError("SIGNATURE_DOWNLOAD_FAILED") from exc
    if not addrs or not all(_public_ip(a) for a in addrs):
        raise ProviderError("SIGNATURE_UNSAFE_URL")
    return host


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def fetch(url: str, allowed_hosts: tuple[str, ...], max_bytes: int, headers: dict[str, str] | None = None) -> bytes:
    """Baixa um artefato do provedor (PDF assinado) com as travas acima e teto de `max_bytes`."""
    check_url(url, allowed_hosts)
    with httpx.Client(timeout=TIMEOUT, follow_redirects=False, transport=_transport) as http:
        try:
            with http.stream("GET", url, headers=headers or {}) as resp:
                if resp.status_code != 200:
                    raise ProviderError("SIGNATURE_DOWNLOAD_FAILED", resp.status_code)
                length = resp.headers.get("content-length", "")
                if length.isdigit() and int(length) > max_bytes:
                    raise ProviderError("SIGNATURE_FILE_TOO_LARGE", 200)
                data = bytearray()
                for chunk in resp.iter_bytes():
                    data += chunk
                    if len(data) > max_bytes:
                        raise ProviderError("SIGNATURE_FILE_TOO_LARGE", 200)
        except httpx.HTTPError as exc:
            raise ProviderError("SIGNATURE_DOWNLOAD_FAILED") from exc
    return bytes(data)
