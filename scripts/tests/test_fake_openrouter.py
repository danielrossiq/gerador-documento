"""Testes da IA falsa (scripts/fake_openrouter.py): formato OpenRouter, schemas do DocFeito e modos de falha.

python -m unittest discover -s scripts/tests -v
"""

from __future__ import annotations

import json
import sys
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import fake_openrouter as fake

KEY = "Bearer sk-or-v1-" + "f" * 40


def fill_schema(names: list[str]) -> dict:
    item = {"type": "object", "properties": {"name": {"type": "string", "enum": names}, "value": {"type": "string"}, "evidence": {"type": "string"}}}
    return {"type": "object", "required": ["values"], "properties": {"values": {"type": "array", "items": item}}}


class FakeOpenRouterTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), fake.Handler)
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self) -> None:
        fake.CONFIG.__init__()  # padrão
        fake.CONFIG.latency_ms = fake.CONFIG.jitter_ms = 0
        self._post("/__reset", {})

    def _post(self, path: str, body: dict, auth: str | None = KEY) -> tuple[int, dict]:
        req = urllib.request.Request(self.base + path, data=json.dumps(body).encode(), method="POST")
        req.add_header("Content-Type", "application/json")
        if auth:
            req.add_header("Authorization", auth)
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.load(r)
        except urllib.error.HTTPError as e:
            return e.code, json.load(e)

    def _chat(self, schema_name: str, schema: dict, user: str, model: str = "google/gemini-2.5-flash", **kw) -> tuple[int, dict]:
        body = {
            "model": model,
            "messages": [{"role": "system", "content": "s"}, {"role": "user", "content": user}],
            "max_tokens": 2000,
            "response_format": {"type": "json_schema", "json_schema": {"name": schema_name, "strict": True, "schema": schema}},
        }
        return self._post("/api/v1/chat/completions", body, **kw)

    def test_fill_answer_is_grounded_in_the_pasted_text(self) -> None:
        user = "CAMPOS DO FORMULÁRIO:\n- x\n\nTEXTO COLADO:\nnome: Maria Souza, CPF 529.982.247-25, R$ 1.234,50 desde 15/11/2026."
        st, out = self._chat("preenchimento", fill_schema(["nome_cliente", "cpf_cliente", "valor_mensal", "data_inicio", "objeto"]), user)
        self.assertEqual(st, 200)
        self.assertEqual(out["choices"][0]["finish_reason"], "stop")
        values = {v["name"]: v["value"] for v in json.loads(out["choices"][0]["message"]["content"])["values"]}
        self.assertEqual(values, {"nome_cliente": "Maria Souza", "cpf_cliente": "529.982.247-25", "valor_mensal": "R$ 1.234,50", "data_inicio": "15/11/2026", "objeto": ""})
        self.assertGreater(out["usage"]["cost"], 0)

    def test_fields_answer_points_to_blocks(self) -> None:
        user = "[body/p1] (corpo) CONTRATANTE: Ana Lima, CPF 111.444.777-35, paga R$ 900,00."
        _, out = self._chat("campos", {"type": "object"}, user, model="anthropic/claude-haiku-5.5")
        sugs = json.loads(out["choices"][0]["message"]["content"])["suggestions"]
        self.assertEqual({(s["block"], s["text"]) for s in sugs} >= {("body/p1", "111.444.777-35"), ("body/p1", "R$ 900,00")}, True)

    def test_unknown_schema_gets_minimal_valid_instance(self) -> None:
        schema = {"type": "object", "required": ["a", "b"], "properties": {"a": {"type": "array"}, "b": {"type": "string", "enum": ["x", "y"]}}}
        _, out = self._chat("outro", schema, "oi")
        self.assertEqual(json.loads(out["choices"][0]["message"]["content"]), {"a": [], "b": "x"})

    def test_failure_modes_and_counters(self) -> None:
        self._post("/__control", {"rate_429": 1.0})
        self.assertEqual(self._chat("revisao", {}, "x")[0], 429)
        self._post("/__control", {"rate_429": 0.0, "rate_truncate": 1.0})
        _, out = self._chat("revisao", {}, "x")
        self.assertEqual(out["choices"][0]["finish_reason"], "length")
        self.assertEqual(out["usage"]["completion_tokens"], 2000)  # cortada = cobrou o teto
        self.assertEqual(self._chat("revisao", {}, "x", auth=None)[0], 401)
        with urllib.request.urlopen(self.base + "/__stats") as r:
            stats = json.load(r)
        self.assertEqual(stats["calls"], 3)
        self.assertEqual(stats["by_outcome"], {"rate_limited": 1, "truncated": 1, "no_key": 1})
        self.assertGreater(stats["cost_usd"], 0)

    def test_models_lists_prices(self) -> None:
        with urllib.request.urlopen(self.base + "/api/v1/models") as r:
            data = {m["id"]: m for m in json.load(r)["data"]}
        self.assertEqual(float(data["google/gemini-2.5-flash"]["pricing"]["prompt"]), 0.30e-6)

    def test_control_rejects_unknown_settings(self) -> None:
        st, _ = self._post("/__control", {"nao_existe": 1})
        self.assertEqual(st, 400)


if __name__ == "__main__":
    unittest.main()
