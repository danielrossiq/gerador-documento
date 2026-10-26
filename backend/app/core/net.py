"""IP real do cliente atrás de proxies confiáveis (TRUSTED_PROXIES) e agrupamento por rede para limites.

Regra ("rightmost untrusted", como o `real_ip_recursive` do nginx, mas com número máximo de saltos):

* a conexão TCP (peer) é a única informação que o cliente não falsifica;
* se o peer NÃO é um proxy confiável, ele é o cliente — qualquer `X-Forwarded-For` é ignorado;
* se é confiável, percorre o `X-Forwarded-For` da DIREITA para a esquerda (cada proxy acrescenta à direita o
  endereço de quem falou com ele), olhando no máximo `hops` entradas (TRUSTED_PROXY_HOPS = quantos proxies há antes
  da API; 1 = só o Next), e o cliente é a primeira entrada que não é proxy confiável — ou a última olhada. O que o
  próprio cliente escreveu fica à esquerda e nunca é alcançado.

Por que o limite de saltos: no desenvolvimento o navegador está em 127.0.0.1 e, no compose, chega ao Next pelo
gateway do Docker (172.x.0.1) — endereços que também são de proxies confiáveis. Sem o limite, a varredura passaria
por eles e aceitaria o que o cliente escreveu no cabeçalho.

O Next (frontend) acrescenta o endereço do socket ao `X-Forwarded-For` antes de repassar `/api/*` (ver
`frontend/src/lib/server/forwarded-for.ts`), e o uvicorn roda com `--no-proxy-headers`: esta função é a única que
interpreta o cabeçalho.
"""

from __future__ import annotations

import ipaddress
from functools import lru_cache

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
IPNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network

MAX_HOPS = 20  # cabeçalho gigante não custa CPU: só os últimos saltos importam


def parse_ip(value: str | None) -> IPAddress | None:
    """Endereço sem porta/colchetes; IPv4 mapeado em IPv6 (::ffff:1.2.3.4, comum no Node) vira IPv4."""
    if not value:
        return None
    v = value.strip().strip('"')
    if v.startswith("["):  # [2001:db8::1]:443
        v = v[1 : v.find("]")] if "]" in v else v[1:]
    elif v.count(":") == 1:  # 1.2.3.4:5678
        v = v.split(":", 1)[0]
    v = v.split("%", 1)[0]  # zona de IPv6 (fe80::1%eth0)
    try:
        ip = ipaddress.ip_address(v)
    except ValueError:
        return None
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        return ip.ipv4_mapped
    return ip


@lru_cache(maxsize=32)
def parse_networks(spec: tuple[str, ...]) -> tuple[IPNetwork, ...]:
    nets: list[IPNetwork] = []
    for item in spec:
        item = item.strip()
        if not item:
            continue
        nets.append(ipaddress.ip_network(item, strict=False))
    return tuple(nets)


def _trusted(ip: IPAddress, nets: tuple[IPNetwork, ...]) -> bool:
    return any(ip.version == n.version and ip in n for n in nets)


def resolve_client_ip(
    peer: str | None, forwarded_for: str | None, trusted: tuple[IPNetwork, ...], hops: int = 1
) -> str | None:
    peer_ip = parse_ip(peer)
    if peer_ip is None:
        return (peer or "")[:64] or None  # cliente de teste ("testclient") ou socket unix
    if not forwarded_for or hops < 1 or not _trusted(peer_ip, trusted):
        return str(peer_ip)
    client: IPAddress = peer_ip
    for hop in list(reversed(forwarded_for.split(",")[-MAX_HOPS:]))[: min(hops, MAX_HOPS)]:
        ip = parse_ip(hop)
        if ip is None:
            break  # lixo onde só um proxy confiável escreve: fica com o último endereço válido
        client = ip
        if not _trusted(ip, trusted):
            break
    return str(client)


def network_key(ip: str | None) -> str:
    """Rede do cliente para limites por vizinhança: /24 no IPv4, /64 no IPv6 (o que um provedor entrega a uma casa)."""
    addr = parse_ip(ip)
    if addr is None:
        return "na"
    prefix = 24 if addr.version == 4 else 64
    return str(ipaddress.ip_network(f"{addr}/{prefix}", strict=False))
