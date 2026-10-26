"""IP real do cliente (app.core.net): X-Forwarded-For só vale vindo de proxy confiável e só os últimos saltos."""

from __future__ import annotations

import pytest

from app.core.net import network_key, parse_ip, parse_networks, resolve_client_ip

TRUSTED = parse_networks(("127.0.0.0/8", "::1/128", "172.16.0.0/12"))


def test_untrusted_peer_ignores_the_header():
    assert resolve_client_ip("203.0.113.9", "1.1.1.1", TRUSTED) == "203.0.113.9"


def test_trusted_peer_takes_the_entry_the_proxy_appended():
    # o cliente escreveu "6.6.6.6"; o Next acrescentou o endereço real do socket
    assert resolve_client_ip("172.18.0.5", "6.6.6.6, 198.51.100.7", TRUSTED) == "198.51.100.7"


def test_local_browser_cannot_spoof_through_a_trusted_hop():
    # desenvolvimento: navegador em ::1 → Next em 127.0.0.1 → API. ::1 também é "confiável", mas só 1 salto é lido
    assert resolve_client_ip("127.0.0.1", "6.6.6.6, ::1", TRUSTED) == "::1"
    # compose: o navegador chega ao Next pelo gateway do Docker
    assert resolve_client_ip("172.18.0.3", "6.6.6.6, 172.18.0.1", TRUSTED) == "172.18.0.1"


def test_two_hops_with_an_edge_proxy():
    # Caddy (172.18.0.9) acrescenta o cliente; o Next acrescenta o Caddy
    xff = "6.6.6.6, 198.51.100.7, 172.18.0.9"
    assert resolve_client_ip("172.18.0.5", xff, TRUSTED, hops=2) == "198.51.100.7"
    # requisição que não passou pelo Caddy: o primeiro endereço não confiável já é o cliente
    assert resolve_client_ip("172.18.0.5", "6.6.6.6, 198.51.100.7", TRUSTED, hops=2) == "198.51.100.7"


def test_garbage_and_missing_values():
    assert resolve_client_ip("127.0.0.1", "unknown", TRUSTED) == "127.0.0.1"
    assert resolve_client_ip("127.0.0.1", "", TRUSTED) == "127.0.0.1"
    assert resolve_client_ip("127.0.0.1", "1.2.3.4", TRUSTED, hops=0) == "127.0.0.1"
    assert resolve_client_ip("testclient", "1.2.3.4", TRUSTED) == "testclient"
    assert resolve_client_ip(None, None, TRUSTED) is None
    huge = ", ".join(["6.6.6.6"] * 10_000) + ", 198.51.100.7"
    assert resolve_client_ip("127.0.0.1", huge, TRUSTED) == "198.51.100.7"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("::ffff:198.51.100.7", "198.51.100.7"),
        ("198.51.100.7:5050", "198.51.100.7"),
        ("[2001:db8::1]:443", "2001:db8::1"),
        (" 2001:db8::1 ", "2001:db8::1"),
        ("fe80::1%eth0", "fe80::1"),
        ("nada", None),
    ],
)
def test_parse_ip_formats(raw, expected):
    ip = parse_ip(raw)
    assert (str(ip) if ip else None) == expected


def test_network_key_groups_neighbours():
    assert network_key("198.51.100.7") == "198.51.100.0/24"
    assert network_key("2001:db8:1:2:3:4:5:6") == "2001:db8:1:2::/64"
    assert network_key(None) == "na"


def test_api_uses_the_real_ip_for_the_register_limit(env, monkeypatch):
    """Cadastro: limite por IP. Peer confiável + X-Forwarded-For trocando a cada vez não fura o limite (o último
    salto é o do proxy); e o mesmo cabeçalho vindo direto de um IP de fora é ignorado."""
    from fastapi.testclient import TestClient

    from app.main import create_app

    app = create_app()

    def register(tc: TestClient, i: int, xff: str) -> int:
        body = {"name": "Ana", "email": f"ana{i}@exemplo.test", "password": "senha-forte-123"}
        return tc.post("/api/v1/auth/register", json=body, headers={"X-Forwarded-For": xff}).status_code

    with TestClient(app, client=("127.0.0.1", 5000)) as tc:
        codes = [register(tc, i, f"10.0.0.{i}, 198.51.100.7") for i in range(11)]
    assert codes[:10] == [201] * 10 and codes[10] == 429

    with TestClient(app, client=("203.0.113.50", 5000)) as tc:
        codes = [register(tc, 100 + i, f"192.0.2.{i}") for i in range(11)]
    assert codes[-1] == 429  # o cabeçalho de quem não é proxy não muda o IP


def test_invalid_trusted_proxies_fails_at_startup(monkeypatch):
    from pydantic import ValidationError

    from app.core.config import Settings

    monkeypatch.setenv("TRUSTED_PROXIES", "127.0.0.1,nao-e-ip")
    with pytest.raises(ValidationError):
        Settings()
    monkeypatch.setenv("TRUSTED_PROXIES", "10.0.0.0/8, 127.0.0.1")
    assert Settings().trusted_proxies == ["10.0.0.0/8", "127.0.0.1"]
