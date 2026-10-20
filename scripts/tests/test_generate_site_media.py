"""Testes do gerador de mídia da landing (sem rede e sem chave real).

python -m unittest discover -s scripts/tests -v
"""

from __future__ import annotations

import base64
import email.message
import io
import json
import shutil
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
import urllib.response
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import generate_site_media as gsm

FAKE_KEY = "sk-or-v1-" + "a1b2c3d4" * 8


def image_item(slug: str = "hero-still", **extra) -> dict:
    return {
        "slug": slug,
        "model": "black-forest-labs/flux-3-image",
        "resolution": "2K",
        "aspect_ratio": "16:9",
        "widths": [64, 128],
        "prompt": "p",
        "alt": "a",
        **extra,
    }


def video_item(**extra) -> dict:
    return {
        "slug": "hero-loop",
        "model": "google/veo-3.1-fast",
        "resolution": "1080p",
        "aspect_ratio": "16:9",
        "duration": 8,
        "frame": "hero-still",
        "loop": True,
        "prompt": "p",
        "alt": "",
        **extra,
    }


def nano_item(**extra) -> dict:
    base = {
        "model": "google/gemini-nano-banana-2.1",
        "resolution": "1K",
        "aspect_ratio": "4:3",
        "references": ["hero-still"],
    }
    return image_item("passo-1-modelo", **{**base, **extra})


FLUX_PARAMS = {
    "resolution": {"type": "enum", "values": ["768", "1K", "1.5K", "2K", "4K"]},
    "aspect_ratio": {"type": "enum", "values": ["16:9", "4:3", "1:1"]},
    "n": {"type": "range", "min": 1, "max": 1},
    "input_references": {"type": "range", "min": 0, "max": 10},
}
NANO_PARAMS = {**FLUX_PARAMS, "resolution": {"type": "enum", "values": ["1K", "2K", "4K"]}}


def flux_endpoints(
    cost: float = 0.1, extra: tuple = (), tag: str | None = "black-forest-labs", unit: str = "image"
):
    return [
        {
            "provider_slug": "black-forest-labs",
            "provider_tag": tag,
            "supported_parameters": FLUX_PARAMS,
            "pricing": [
                {"billable": "output_image", "unit": unit, "cost_usd": 0.048, "variant": "1k"},
                {"billable": "output_image", "unit": unit, "cost_usd": cost, "variant": "2k"},
                *extra,
            ],
        }
    ]


def nano_endpoints(cost: float = 3e-05):
    return [
        {
            "provider_slug": "google-ai-studio",
            "provider_tag": "google-ai-studio",
            "supported_parameters": NANO_PARAMS,
            "pricing": [{"billable": "output_image", "unit": "token", "cost_usd": cost}],
        }
    ]


def video_models(**over) -> dict:
    info = {
        "id": "google/veo-3.1-fast",
        "supported_durations": [4, 6, 8],
        "supported_resolutions": ["720p", "1080p", "4K"],
        "supported_aspect_ratios": ["16:9", "9:16"],
        "supported_frame_images": ["first_frame", "last_frame"],
        "seed": True,
        "pricing_skus": {"duration_seconds_without_audio": "0.10", "duration_seconds_with_audio": "0.12"},
        "allowed_passthrough_parameters": ["negativePrompt", "enhancePrompt"],
        **over,
    }
    return {info["id"]: info}


class KeyStub:
    """Simula GET /key: uso acumulado da chave, limite opcional e falha."""

    def __init__(self, usage: float = 10.0, limit: float | None = None):
        self.usage, self.limit, self.spent, self.fail = usage, limit, 0.0, False

    def charge(self, usd: float) -> None:
        self.spent = round(self.spent + usd, 4)

    def __call__(self, key):
        if self.fail:
            raise gsm.ApiError("HTTP 503 em GET /api/v1/key", 503)
        remaining = None if self.limit is None else round(self.limit - self.spent, 4)
        return {"usage": round(self.usage + self.spent, 4), "limit": self.limit, "limit_remaining": remaining}


class FakeResp:
    def __init__(self, body: bytes, content_type: str):
        self._buf = io.BytesIO(body)
        self.headers = email.message.Message()
        self.headers["Content-Type"] = content_type

    def read(self, n: int = -1) -> bytes:
        return self._buf.read(n)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeHTTPS(urllib.request.HTTPSHandler):
    """Transporte falso dentro da pilha real do urllib (HTTPErrorProcessor e handler de redirect de verdade)."""

    def __init__(self, responses: list[tuple[int, dict, bytes]]):
        super().__init__()
        self.responses, self.seen = list(responses), []

    def https_open(self, req):
        auth = req.get_header("Authorization") or req.unredirected_hdrs.get("Authorization")
        self.seen.append((req.full_url, auth))
        status, headers, body = self.responses.pop(0) if self.responses else (500, {}, b"")
        msg = email.message.Message()
        for k, v in headers.items():
            msg[k] = v
        resp = urllib.response.addinfourl(io.BytesIO(body), msg, req.full_url, status)
        resp.msg = "fake"
        return resp


class FakeOpener:
    def __init__(self, resp: FakeResp):
        self.resp, self.requests = resp, []

    def open(self, req, timeout=None):
        self.requests.append(req)
        return self.resp


class TempPaths(unittest.TestCase):
    """Redireciona manifest, originais e saídas para um diretório temporário."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        for name, rel in (
            ("SPEC", "site_media.json"),
            ("MANIFEST", "manifest.json"),
            ("ORIGINALS", "orig"),
            ("PUBLIC", "public/site"),
            ("UI_DATA", "site-media.json"),
        ):
            patcher = mock.patch.object(gsm, name, self.tmp / rel)
            patcher.start()
            self.addCleanup(patcher.stop)

    def write_spec(self, images=None, videos=None):
        gsm.SPEC.write_text(json.dumps({"images": images or [], "videos": videos or []}), encoding="utf-8")


class ScrubAndUrls(unittest.TestCase):
    def test_scrub_removes_key_tokens_data_urls_and_signatures(self):
        text = f"falhou {FAKE_KEY} sk-or-v1-zzzzzzzzzz data:image/png;base64,AAAABBBBCCCC https://x.example/v.mp4?sig=abc&exp=1"
        out = gsm.scrub(text, FAKE_KEY)
        self.assertNotIn(FAKE_KEY, out)
        self.assertNotIn("zzzzzzzzzz", out)
        self.assertNotIn("AAAABBBB", out)
        self.assertNotIn("sig=abc", out)
        self.assertIn("https://x.example/v.mp4?…", out)

    def test_api_url_only_accepts_openrouter_api(self):
        self.assertEqual(gsm.api_url("images"), "https://openrouter.ai/api/v1/images")
        self.assertEqual(gsm.api_url("/api/v1/videos/abc"), "https://openrouter.ai/api/v1/videos/abc")
        self.assertEqual(
            gsm.api_url("https://openrouter.ai/api/v1/videos/abc/content?index=0"),
            "https://openrouter.ai/api/v1/videos/abc/content?index=0",
        )
        for bad in (
            "https://evil.example/api/v1/videos",
            "http://openrouter.ai/api/v1/videos",
            "https://openrouter.ai:8443/api/v1/x",
            "https://user@openrouter.ai/api/v1/x",
            "https://openrouter.ai/other",
            "//evil.example/api/v1/x",
            "https://openrouter.ai.evil.example/api/v1/x",
        ):
            with self.assertRaises(gsm.ApiError, msg=bad):
                gsm.api_url(bad)

    def test_authorization_goes_only_in_unredirected_header(self):
        req, _ = gsm._request("GET", "videos/abc/content?index=0", FAKE_KEY, None)
        self.assertNotIn("Authorization", req.headers)  # o urllib nunca copia unredirected_hdrs num redirect
        self.assertEqual(req.unredirected_hdrs["Authorization"], f"Bearer {FAKE_KEY}")

    def test_real_opener_refuses_every_redirect_and_fetches_nothing_else(self):
        targets = (
            "https://storage.example/v.mp4?sig=1",  # outro host
            "https://openrouter.ai/api/v1/videos/abc/content?index=1",  # mesmo host também é recusado
            "http://openrouter.ai/api/v1/key",
        )
        for code in (301, 302, 303, 307, 308):
            for target in targets:
                transport = FakeHTTPS([(code, {"Location": target}, b"")] * 2)
                with mock.patch.object(gsm, "_OPENER", gsm.build_opener(transport)):
                    with self.assertRaises(gsm.ApiError, msg=f"{code} {target}"):
                        gsm.call_api("GET", "key", FAKE_KEY)
                    with self.assertRaises(gsm.ApiError, msg=f"{code} {target}"):
                        gsm.download(
                            "videos/j/content",
                            Path(tempfile.mkdtemp()) / "v.mp4",
                            FAKE_KEY,
                            10,
                            {"video/mp4"},
                            gsm.is_mp4,
                        )
                self.assertEqual(
                    [u for u, _ in transport.seen],
                    ["https://openrouter.ai/api/v1/key", "https://openrouter.ai/api/v1/videos/j/content"],
                )

    def test_real_opener_sends_key_only_to_the_api(self):
        transport = FakeHTTPS([(200, {"Content-Type": "application/json"}, b'{"data": {"usage": 1.5}}')])
        with mock.patch.object(gsm, "_OPENER", gsm.build_opener(transport)):
            self.assertEqual(gsm.key_state(FAKE_KEY), {"usage": 1.5, "limit": None, "limit_remaining": None})
        self.assertEqual(transport.seen, [("https://openrouter.ai/api/v1/key", f"Bearer {FAKE_KEY}")])

    def test_http_error_message_never_contains_key(self):
        body = json.dumps({"error": {"message": f"Invalid key {FAKE_KEY}", "code": 401}}).encode()
        err = urllib.error.HTTPError(
            "https://openrouter.ai/api/v1/images", 401, "Unauthorized", {}, io.BytesIO(body)
        )
        self.addCleanup(err.close)
        e = gsm._http_error(err, "POST", "https://openrouter.ai/api/v1/images", FAKE_KEY)
        self.assertNotIn(FAKE_KEY, str(e))
        self.assertTrue(e.fatal)

    def test_original_names_from_manifest_cannot_escape_originals_dir(self):
        self.assertEqual(gsm.original_path("hero-still.png"), gsm.ORIGINALS / "hero-still.png")
        for bad in ("../../.minuta/openrouter.key", "..\\x.png", "/etc/passwd", "hero.png.key", "Hero.png"):
            with self.assertRaises(SystemExit, msg=bad):
                gsm.original_path(bad)

    def test_inside_rejects_paths_that_escape_the_base(self):
        base = Path(tempfile.mkdtemp())
        self.assertEqual(gsm.inside(base / "a.webp", base), base / "a.webp")
        for bad in (base / ".." / "x.webp", base, Path(tempfile.gettempdir()) / "x.webp"):
            with self.assertRaises(SystemExit, msg=str(bad)):
                gsm.inside(bad, base)

    def test_slug_is_limited_to_40_safe_characters(self):
        self.assertTrue(gsm.SLUG_RE.match("a" * 40))
        for bad in ("a" * 41, "-hero", "Hero", "hero_still", "hero/still", "hero.still", ""):
            self.assertIsNone(gsm.SLUG_RE.match(bad), bad)

    def test_read_key_validates_format_before_use(self):
        tmp = Path(tempfile.mkdtemp())
        cases = {
            "ok.key": ("﻿" + FAKE_KEY + "\r\n", True),
            "ok-linha-em-branco.key": (FAKE_KEY + "\n\n", True),
            "duas-linhas.key": (FAKE_KEY + "\n" + FAKE_KEY + "\n", False),
            "prefixo.key": ("Bearer " + FAKE_KEY, False),
            "curta.key": ("sk-or-v1-abc", False),
            "outro-arquivo.key": ("[core]\nrepositoryformatversion = 0\n", False),
        }
        for name, (content, ok) in cases.items():
            path = tmp / name
            path.write_bytes(content.encode("utf-8"))
            with mock.patch.dict("os.environ", {"OPENROUTER_KEY_FILE": str(path)}):
                if ok:
                    self.assertEqual(gsm.read_key(), FAKE_KEY)
                    continue
                with self.assertRaises(SystemExit, msg=name) as ctx:
                    gsm.read_key()
                self.assertNotIn(FAKE_KEY, str(ctx.exception))
        big = tmp / "grande.key"
        big.write_bytes(b"sk-or-" + b"a" * 2048)
        with mock.patch.dict("os.environ", {"OPENROUTER_KEY_FILE": str(big)}), self.assertRaises(SystemExit):
            gsm.read_key()
        binary = tmp / "binario.key"
        binary.write_bytes(b"\xff\xfe\x00\x01")
        with (
            mock.patch.dict("os.environ", {"OPENROUTER_KEY_FILE": str(binary)}),
            self.assertRaises(SystemExit),
        ):
            gsm.read_key()

    def test_read_key_refuses_file_inside_repo(self):
        inside = gsm.ROOT / "scripts" / "tests" / ".tmp-test.key"
        inside.write_text(FAKE_KEY, encoding="utf-8")
        try:
            with (
                mock.patch.dict("os.environ", {"OPENROUTER_KEY_FILE": str(inside)}),
                self.assertRaises(SystemExit) as ctx,
            ):
                gsm.read_key()
            self.assertNotIn(FAKE_KEY, str(ctx.exception))
        finally:
            inside.unlink()


class WithRun(TempPaths):
    """Base dos testes que abrem uma execução paga com GET /key simulado."""

    def start_run(self, m: dict | None = None, **stub) -> tuple:
        key = KeyStub(**stub)
        patcher = mock.patch.object(gsm, "key_state", key)
        patcher.start()
        self.addCleanup(patcher.stop)
        out = mock.patch("sys.stdout", io.StringIO())
        out.start()
        self.addCleanup(out.stop)
        return gsm.Run(FAKE_KEY, m or gsm.empty_manifest()), key


def call(model: str, cost: float | None, reserved: float, run: str = "r0", **extra) -> dict:
    return {
        "kind": "image",
        "slug": "x",
        "model": model,
        "run": run,
        "status": "ok",
        "costUsd": cost,
        "reservedUsd": reserved,
        **extra,
    }


FLUX, NANO, VEO = "black-forest-labs/flux-3-image", "google/gemini-nano-banana-2.1", "google/veo-3.1-fast"


class Quotes(unittest.TestCase):
    def test_fixed_price_image_uses_requested_variant_and_pins_provider(self):
        q = gsm.quote_image(image_item(), flux_endpoints())
        self.assertEqual((q.bounded, q.worst_usd, q.pin, q.problems), (True, 0.1, ("black-forest-labs",), ()))

    def test_reference_charges_are_added_and_unverifiable_units_refused(self):
        refs = image_item(references=["a", "b"])
        per_image = {"billable": "input_reference", "unit": "image", "cost_usd": 0.02}
        self.assertTrue(gsm.quote_image(refs, flux_endpoints(cost=0.06, extra=(per_image,))).problems == ())
        self.assertAlmostEqual(
            gsm.quote_image(refs, flux_endpoints(cost=0.06, extra=(per_image,))).worst_usd, 0.1
        )
        cases = {
            "acima do aprovado": (refs, flux_endpoints(extra=(per_image,))),  # 0,10 + 2 x 0,02
            "por megapixel": (
                refs,
                flux_endpoints(extra=({"billable": "input_image", "unit": "megapixel", "cost_usd": 0.01},)),
            ),
            "item desconhecido": (
                image_item(),
                flux_endpoints(extra=({"billable": "surpresa", "unit": "image", "cost_usd": 0},)),
            ),
            "saída por megapixel": (image_item(), flux_endpoints(unit="megapixel")),
            "preço novo": (image_item(), flux_endpoints(cost=0.2)),
            "proporção": (image_item(aspect_ratio="7:3"), flux_endpoints()),
            "sem endpoint": (image_item(), []),
        }
        for name, (item, eps) in cases.items():
            self.assertTrue(gsm.quote_image(item, eps).problems, name)

    def test_unpinnable_endpoint_disables_pinning_but_keeps_the_maximum(self):
        eps = flux_endpoints() + flux_endpoints(cost=0.09, tag=None)
        q = gsm.quote_image(image_item(), eps)
        self.assertEqual((q.pin, q.worst_usd), ((), 0.1))

    def test_token_priced_image_is_unbounded(self):
        q = gsm.quote_image(nano_item(), nano_endpoints())
        self.assertEqual((q.bounded, q.worst_usd, q.problems), (False, 0.1, ()))
        self.assertTrue(gsm.quote_image(nano_item(), nano_endpoints(cost=0.0001)).problems)

    def test_video_maximum_is_requested_sku_times_duration(self):
        q = gsm.quote_video(video_item(), video_models())
        self.assertEqual((q.bounded, q.worst_usd, q.seed, q.problems), (True, 0.8, True, ()))
        cases = {
            "preço novo": video_models(pricing_skus={"duration_seconds_without_audio": "0.12"}),
            "sem SKU": video_models(pricing_skus={"duration_seconds_with_audio": "0.12"}),
            "sem duração": video_models(supported_durations=[4, 6]),
            "sem loop": video_models(supported_frame_images=["first_frame"]),
            "sem negativePrompt": video_models(allowed_passthrough_parameters=[]),
        }
        for name, live in cases.items():
            self.assertTrue(gsm.quote_video(video_item(negative_prompt="x"), live).problems, name)
        self.assertTrue(gsm.quote_video(video_item(), {}).problems)

    def test_key_state_keeps_only_numbers(self):
        payload = {
            "data": {"label": "sk-or-v1-abc...xyz", "usage": 1.5, "limit": True, "limit_remaining": "2"}
        }
        with mock.patch.object(gsm, "call_api", return_value=payload):
            self.assertEqual(gsm.key_state(FAKE_KEY), {"usage": 1.5, "limit": None, "limit_remaining": None})


class Budget(WithRun):
    def test_reported_cost_or_reservation_and_measured_usage(self):
        m = gsm.empty_manifest()
        m["calls"] = [call(FLUX, 0.1, 0.1), call(FLUX, None, 0.1), call(VEO, None, 0.8, run="r2")]
        self.assertAlmostEqual(gsm.recorded_usd(m), 1.0)
        self.assertAlmostEqual(gsm.recorded_usd(m, "r2"), 0.8)
        m["runs"] = [{"usageStart": 10.0, "usageEnd": 10.2}, {"usageStart": 10.2, "usageEnd": None}]
        self.assertAlmostEqual(gsm.measured_usd(m), 0.2)

    def test_model_call_limit_skips_only_that_model(self):
        m = gsm.empty_manifest()
        m["calls"] = [call(VEO, 0.8, 0.8), call(VEO, 0.8, 0.8)]
        run, _ = self.start_run(m)
        self.assertEqual(run.gate(gsm.quote_video(video_item(), video_models()))[0], "skip")
        self.assertIsNone(run.gate(gsm.quote_image(image_item(), flux_endpoints())))

    def test_stops_before_passing_the_ceiling_by_recorded_or_measured_spend(self):
        m = gsm.empty_manifest()
        m["calls"] = [call(FLUX, 2.5, 2.5)]
        run, _ = self.start_run(m)
        self.assertIn("orçamento", run.gate(gsm.quote_video(video_item(), video_models()))[1])
        m = gsm.empty_manifest()
        m["runs"] = [{"usageStart": 1.0, "usageEnd": 3.5}]  # gasto medido na chave sem registro de chamada
        run, _ = self.start_run(m)
        self.assertIn("orçamento", run.gate(gsm.quote_video(video_item(), video_models()))[1])

    def test_unexplained_key_spend_stops_the_run(self):
        run, key = self.start_run()
        key.charge(0.5)  # alguém gastou com a mesma chave durante a execução
        self.assertIn("a chave gastou", run.gate(gsm.quote_image(image_item(), flux_endpoints()))[1])

    def test_key_limit_below_the_call_maximum_stops(self):
        run, _ = self.start_run(limit=0.5)
        self.assertIn("limite da chave", run.gate(gsm.quote_video(video_item(), video_models()))[1])

    def test_fails_closed_without_key_measurement(self):
        run, key = self.start_run()
        key.fail = True
        self.assertEqual(run.gate(gsm.quote_image(image_item(), flux_endpoints()))[0], "stop")

    def test_token_priced_model_needs_key_limit_within_remaining_budget(self):
        nano = gsm.quote_image(nano_item(), nano_endpoints())
        for limit, allowed in ((None, False), (5.0, False), (3.0, True), (2.0, True)):
            run, _ = self.start_run(limit=limit)
            self.assertEqual(run.gate(nano) is None, allowed, limit)
        m = gsm.empty_manifest()
        m["calls"] = [call(FLUX, 1.0, 1.0)]
        run, key = self.start_run(m, limit=3.0)
        key.charge(0.5)  # o limite restante (2,50) passa do que resta do orçamento (2,00)
        m["calls"][0]["run"] = run.id  # gasto desta execução, registrado
        m["calls"][0]["costUsd"] = 0.5
        m["calls"].append(call(FLUX, 0.5, 0.5, run="r0"))
        self.assertEqual(run.gate(nano)[0], "skip")

    def test_reported_cost_above_reservation_is_flagged(self):
        run, _ = self.start_run()
        c = call(FLUX, None, 0.1, run=run.id)
        run.m["calls"].append(c)
        self.assertFalse(run.settle(c, {"cost": 0.15}))
        self.assertTrue(c["overrun"])
        c2 = call(FLUX, None, 0.1, run=run.id)
        self.assertTrue(run.settle(c2, {"cost": 0.1}))
        self.assertTrue(run.settle(c2, None) and c2["costSource"] == "reserve")

    def test_full_plan_never_passes_the_ceiling(self):
        self.assertLessEqual(gsm.BUDGET_USD, 3.00)  # saldo de US$ 5: até US$ 3 para o site, US$ 2 para a IA
        run, key = self.start_run(limit=3.0)
        quotes = {
            FLUX: gsm.quote_image(image_item(), flux_endpoints()),
            NANO: gsm.quote_image(nano_item(), nano_endpoints()),
            VEO: gsm.quote_video(video_item(), video_models()),
        }
        plan = [VEO] * 3 + [FLUX] * 10 + [NANO] * 4  # mais chamadas que os limites, de propósito
        for model in plan:
            q = quotes[model]
            if run.gate(q) is None:
                run.m["calls"].append(call(model, q.worst_usd, q.worst_usd, run=run.id))
                key.charge(q.worst_usd)
        self.assertLessEqual(gsm.recorded_usd(run.m), gsm.BUDGET_USD)
        self.assertLessEqual(key.spent, gsm.BUDGET_USD)
        self.assertEqual([gsm.calls_of(run.m, x) for x in (VEO, FLUX, NANO)], [2, 9, 3])


class SpecValidation(TempPaths):
    def test_rejects_unapproved_model_resolution_slug_duration_and_counts(self):
        cases = [
            ([image_item(model="openai/gpt-image-2")], []),
            ([image_item(model=VEO)], []),
            ([image_item(resolution="4K")], []),
            ([nano_item(resolution="2K")], []),
            ([image_item(slug="../../etc")], []),
            ([image_item(slug="a" * 41)], []),
            ([image_item()], [video_item(duration=10)]),
            ([image_item()], [video_item(model="google/veo-3.1")]),
            ([image_item()], [video_item(model="google/veo-3.1-lite")]),
            ([image_item()], [video_item(model=FLUX)]),
            ([image_item()], [video_item(fallback="google/veo-3.1-lite")]),
            ([image_item(aspect_ratio="4:3")], [video_item()]),
            ([image_item()], [video_item(), video_item(slug="outro-loop")]),
            ([image_item(f"img-{i}") for i in range(8)], []),
        ]
        for images, videos in cases:
            self.write_spec(images, videos)
            with self.assertRaises(SystemExit, msg=json.dumps([images[0], videos[:1]])[:120]):
                gsm.load_spec()

    def test_accepts_allowlisted_plan(self):
        self.write_spec([image_item(), nano_item()], [video_item()])
        self.assertEqual(len(gsm.load_spec()["images"]), 2)

    def test_committed_spec_is_the_design_v2_plan_within_limits(self):
        with mock.patch.object(gsm, "SPEC", gsm.ROOT / "scripts" / "site_media.json"):
            spec = gsm.load_spec()
        self.assertEqual((len(spec["images"]), len(spec["videos"])), (7, 1))
        self.assertTrue(all(a["alt"] == "" for a in spec["images"]))  # decorativas (landing-spec-v2 §5)
        planned = sum(
            rule["calls"] * rule.get("max_call_usd", rule.get("reserve_usd", 0))
            for rule in gsm.MODELS.values()
            if rule["unit"] != "second"
        )
        planned += gsm.MODELS[VEO]["calls"] * gsm.MODELS[VEO]["max_unit_usd"] * gsm.MAX_VIDEO_SECONDS
        self.assertAlmostEqual(planned, 2.8)  # tabela do §10
        self.assertLessEqual(planned, gsm.BUDGET_USD)


class Generation(WithRun):
    def setUp(self):
        super().setUp()
        for name, value in (
            ("fetch_image_endpoints", lambda model: flux_endpoints() if model == FLUX else nano_endpoints()),
            ("fetch_video_models", lambda: video_models()),
        ):
            patcher = mock.patch.object(gsm, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def png_original(self, slug: str) -> Path:
        from PIL import Image

        gsm.ORIGINALS.mkdir(parents=True, exist_ok=True)
        path = gsm.ORIGINALS / f"{slug}.png"
        Image.new("RGB", (160, 90), (52, 77, 104)).save(path, "PNG")
        return path

    def test_failed_image_call_is_recorded_before_sending_and_sanitized(self):
        run, _ = self.start_run()

        def boom(key, item, body):
            saved = json.loads(gsm.MANIFEST.read_text(encoding="utf-8"))["calls"][0]
            self.assertEqual((saved["status"], saved["reservedUsd"]), ("pending", 0.1))
            raise gsm.ApiError(f"HTTP 500 em POST /api/v1/images: upstream echoed {FAKE_KEY}", 500)

        with mock.patch.object(gsm, "generate_image", boom):
            self.assertEqual(gsm.run_image(run, image_item()), "failed")
        saved = gsm.MANIFEST.read_text(encoding="utf-8")
        self.assertNotIn(FAKE_KEY, saved)
        self.assertEqual(json.loads(saved)["calls"][0]["status"], "failed")
        self.assertAlmostEqual(gsm.recorded_usd(run.m), 0.10)

    def test_fatal_error_stops_the_run(self):
        run, _ = self.start_run()
        with mock.patch.object(gsm, "generate_image", side_effect=gsm.ApiError("HTTP 402", 402)):
            self.assertEqual(gsm.run_image(run, image_item()), "stop")

    def test_image_request_pins_verified_provider_and_records_reported_cost(self):
        run, key = self.start_run()
        sent = []

        def fake_generate(k, item, body):
            sent.append(body)
            key.charge(0.1)
            return self.png_original(item["slug"]), {"cost": 0.1}

        with mock.patch.object(gsm, "generate_image", fake_generate):
            self.assertEqual(gsm.run_image(run, image_item(widths=[64])), "ok")
            self.assertEqual(
                gsm.run_image(run, image_item("outra", widths=[64])), "ok"
            )  # gasto explicado: segue
        self.assertEqual(sent[0]["provider"], {"only": ["black-forest-labs"], "allow_fallbacks": False})
        asset = run.m["assets"]["images"]["hero-still"]
        self.assertEqual((asset["costUsd"], asset["costSource"], asset["seed"]), (0.1, "api", None))

    def test_cost_above_reservation_keeps_the_asset_and_stops(self):
        run, _ = self.start_run()
        with mock.patch.object(
            gsm, "generate_image", lambda k, item, body: (self.png_original(item["slug"]), {"cost": 0.15})
        ):
            self.assertEqual(gsm.run_image(run, image_item(widths=[64])), "stop")
        self.assertIn("hero-still", run.m["assets"]["images"])
        self.assertTrue(run.m["calls"][0]["overrun"])

    def test_token_priced_image_is_skipped_without_a_key_limit(self):
        run, _ = self.start_run()
        with mock.patch.object(gsm, "generate_image") as gen:
            self.assertEqual(gsm.run_image(run, nano_item()), "failed")
        gen.assert_not_called()
        self.assertEqual(run.m["calls"], [])

    def test_call_with_unknown_outcome_is_not_paid_again_without_explicit_retry(self):
        m = gsm.empty_manifest()
        m["calls"].append({**call(FLUX, None, 0.1), "slug": "hero-still", "status": "pending"})
        run, _ = self.start_run(m)
        with mock.patch.object(gsm, "generate_image") as gen:
            self.assertEqual(gsm.run_image(run, image_item()), "failed")
            gen.assert_not_called()
            run.retry = {"hero-still"}
            gen.side_effect = gsm.ApiError("HTTP 500", 500)
            self.assertEqual(gsm.run_image(run, image_item()), "failed")
            gen.assert_called_once()
        self.assertEqual([c["status"] for c in m["calls"]], ["unknown", "failed"])
        self.assertAlmostEqual(gsm.recorded_usd(m), 0.2)  # a chamada incerta continua contando

    def test_image_with_declared_type_that_does_not_match_content_is_refused(self):
        png = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\0" * 32).decode()
        for media_type in ("image/jpeg", "text/html"):
            resp = {"data": [{"b64_json": png, "media_type": media_type}], "usage": {"cost": 0.1}}
            with mock.patch.object(gsm, "call_api", return_value=resp), self.assertRaises(gsm.ApiError):
                gsm.generate_image(FAKE_KEY, image_item(), {})
        self.assertFalse(gsm.ORIGINALS.exists() and any(gsm.ORIGINALS.iterdir()))

    def test_video_seed_is_sent_and_recorded_and_there_is_no_fallback(self):
        run, _ = self.start_run()
        bodies = []
        with (
            mock.patch.object(gsm, "video_body", lambda v, m, seed: bodies.append(seed) or {}),
            mock.patch.object(gsm, "submit_video", side_effect=gsm.ApiError("HTTP 503", 503)) as submit,
        ):
            self.assertEqual(gsm.run_video(run, video_item()), "failed")
        submit.assert_called_once()  # sem fallback para outro modelo
        self.assertEqual(len(run.m["calls"]), 1)
        self.assertIsInstance(bodies[0], int)
        self.assertEqual(run.m["calls"][0]["seed"], bodies[0])
        self.assertAlmostEqual(gsm.recorded_usd(run.m), 0.8)

    def test_failed_video_download_keeps_job_for_resume_without_new_job(self):
        run, _ = self.start_run()
        done = {"id": "job-9", "status": "completed", "usage": {"cost": 0.8}, "generation_id": "gen-9"}
        with (
            mock.patch.object(gsm, "video_body", return_value={}),
            mock.patch.object(gsm, "submit_video", return_value={"id": "job-9"}) as submit,
            mock.patch.object(gsm, "wait_video", return_value=done),
            mock.patch.object(gsm, "fetch_video", side_effect=gsm.ApiError("Falha de rede no download")),
        ):
            self.assertEqual(gsm.run_video(run, video_item()), "stop")
        submit.assert_called_once()
        self.assertEqual(len(run.m["calls"]), 1)
        self.assertEqual((run.m["calls"][0]["status"], run.m["calls"][0]["costUsd"]), ("submitted", 0.8))

    def test_submitted_video_is_resumed_in_the_current_run_without_new_paid_call(self):
        m = gsm.empty_manifest()
        m["calls"].append(
            {
                **call(VEO, None, 0.8),
                "kind": "video",
                "slug": "hero-loop",
                "status": "submitted",
                "jobId": "job-1",
            }
        )
        run, _ = self.start_run(m)
        with (
            mock.patch.object(gsm, "submit_video") as submit,
            mock.patch.object(gsm, "_finish_video", return_value="ok") as finish,
        ):
            self.assertEqual(gsm.run_video(run, video_item()), "ok")
        submit.assert_not_called()
        self.assertEqual(finish.call_args.args[3]["id"], "job-1")
        self.assertEqual((len(m["calls"]), m["calls"][0]["run"]), (1, run.id))

    def test_run_lock_blocks_a_second_concurrent_run(self):
        with mock.patch.object(gsm, "LOCK", self.tmp / ".lock"):
            with gsm.run_lock():
                self.assertTrue((self.tmp / ".lock").exists())
                with self.assertRaises(SystemExit), gsm.run_lock():
                    pass
            self.assertFalse((self.tmp / ".lock").exists())


class MainFlow(TempPaths):
    def fake_api(self, flux_cost: float = 0.1):
        seen = []

        def fake_call(method, path, key=None, body=None):
            seen.append((method, path, key))
            if path.startswith("images/models/"):
                return {"endpoints": flux_endpoints(cost=flux_cost) if FLUX in path else nano_endpoints()}
            return {"data": list(video_models().values())}

        return fake_call, seen

    def test_dry_run_never_reads_key_nor_posts(self):
        self.write_spec([image_item(), nano_item()], [video_item()])
        fake_call, seen = self.fake_api()
        out = io.StringIO()
        with (
            mock.patch.object(gsm, "call_api", fake_call),
            mock.patch.object(gsm, "read_key", side_effect=AssertionError("dry-run leu a chave")),
            mock.patch.object(gsm, "key_state", side_effect=AssertionError("dry-run consultou a chave")),
            mock.patch.object(sys, "argv", ["x", "--dry-run"]),
            mock.patch("sys.stdout", out),
        ):
            self.assertEqual(gsm.main(), 0)
        self.assertTrue(seen)
        self.assertTrue(all(method == "GET" and key is None for method, _, key in seen))
        self.assertFalse(gsm.MANIFEST.exists())
        self.assertIn("exige limite de crédito na chave", out.getvalue())

    def test_live_price_above_approved_blocks_generation(self):
        self.write_spec([image_item()])
        fake_call, _ = self.fake_api(flux_cost=0.2)
        with (
            mock.patch.object(gsm, "call_api", fake_call),
            mock.patch.object(gsm, "read_key", side_effect=AssertionError("não devia ler a chave")),
            mock.patch.object(sys, "argv", ["x"]),
            mock.patch("sys.stdout", io.StringIO()),
        ):
            self.assertEqual(gsm.main(), 1)


class Transport(TempPaths):
    def test_call_api_refuses_non_json_and_oversized_responses(self):
        with (
            mock.patch.object(gsm, "_OPENER", FakeOpener(FakeResp(b"<html>", "text/html"))),
            self.assertRaises(gsm.ApiError),
        ):
            gsm.call_api("GET", "videos/models")
        with (
            mock.patch.object(gsm, "MAX_JSON_BYTES", 10),
            mock.patch.object(
                gsm, "_OPENER", FakeOpener(FakeResp(b'{"data": [1, 2, 3, 4]}', "application/json"))
            ),
            self.assertRaises(gsm.ApiError),
        ):
            gsm.call_api("GET", "videos/models")
        opener = FakeOpener(FakeResp(b'{"ok": true}', "application/json; charset=utf-8"))
        with mock.patch.object(gsm, "_OPENER", opener):
            self.assertEqual(gsm.call_api("GET", "key", FAKE_KEY), {"ok": True})
        self.assertEqual(opener.requests[0].full_url, "https://openrouter.ai/api/v1/key")

    def test_download_validates_type_size_and_signature_before_moving(self):
        gsm.ORIGINALS.mkdir(parents=True)
        dst = gsm.ORIGINALS / "hero-loop.mp4"
        mp4 = b"\0\0\0\x18ftypisom" + b"\0" * 64
        bad = [
            (FakeResp(mp4, "text/html"), 1000),  # Content-Type errado
            (FakeResp(mp4, "video/mp4"), 10),  # passa do tamanho máximo
            (FakeResp(b"<html>not a video</html>", "video/mp4"), 1000),  # assinatura não é MP4
        ]
        for resp, limit in bad:
            with mock.patch.object(gsm, "_OPENER", FakeOpener(resp)), self.assertRaises(gsm.ApiError):
                gsm.download("videos/j/content?index=0", dst, FAKE_KEY, limit, {"video/mp4"}, gsm.is_mp4)
            self.assertEqual(list(gsm.ORIGINALS.iterdir()), [])  # nem o destino nem o .part ficam
        with mock.patch.object(gsm, "_OPENER", FakeOpener(FakeResp(mp4, "video/mp4"))):
            self.assertEqual(
                gsm.download("videos/j/content?index=0", dst, FAKE_KEY, 1000, {"video/mp4"}, gsm.is_mp4),
                len(mp4),
            )
        self.assertEqual([p.name for p in gsm.ORIGINALS.iterdir()], ["hero-loop.mp4"])

    def test_download_never_targets_hosts_outside_the_api(self):
        with self.assertRaises(gsm.ApiError):
            gsm.download(
                "https://storage.example/v.mp4", self.tmp / "x.mp4", FAKE_KEY, 10, {"video/mp4"}, gsm.is_mp4
            )


class Outputs(TempPaths):
    def test_optimized_images_have_no_metadata(self):
        from PIL import Image

        src = self.tmp / "src.jpg"
        exif = Image.Exif()
        exif[0x010F] = "CameraMaker"  # Make
        Image.new("RGB", (256, 144), (52, 77, 104)).save(
            src, "JPEG", exif=exif.tobytes(), icc_profile=b"\0" * 128
        )
        variants = gsm.optimize_image("hero-still", src, [64, 128])
        self.assertEqual(len(variants), 4)
        for v in variants:
            path = gsm.PUBLIC / Path(v["file"]).name
            with Image.open(path) as im:
                self.assertFalse({"exif", "xmp", "icc_profile"} & set(im.info), path.name)
                self.assertEqual(len(im.getexif()), 0)

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg ausente")
    def test_video_encode_strips_audio_and_metadata_trims_loop_frame_and_hits_size(self):
        src = self.tmp / "src.mp4"
        gsm._run(
            [
                shutil.which("ffmpeg"),
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "testsrc2=size=640x360:rate=24:duration=2",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=440:duration=2",
                "-metadata",
                "title=origem",
                "-c:v",
                "libx264",
                "-c:a",
                "aac",
                "-shortest",
                str(src),
            ]
        )
        self.assertTrue(gsm.probe(src)["audio"])
        out = gsm.encode_video(
            "hero-loop",
            src,
            {"loop": True, "target_bytes": 150_000, "output_width": 480, "poster_widths": [240, 480]},
        )
        self.assertFalse(out["checks"]["outputAudio"])
        self.assertTrue(out["checks"]["sourceAudio"])
        self.assertEqual(out["width"], 480)
        self.assertEqual(
            gsm.probe(gsm.PUBLIC / "hero-loop.mp4")["frames"], 47
        )  # 48 quadros menos o repetido do loop
        self.assertTrue(all(s["bytes"] <= out["checks"]["maxBytes"] for s in out["sources"]))
        self.assertEqual(out["checks"]["frames"], 47)
        self.assertEqual([s["type"] for s in out["sources"]], ["video/webm", "video/mp4"])
        self.assertEqual(len(out["poster"]), 4)
        tags = json.loads(
            gsm._run(
                [
                    shutil.which("ffprobe"),
                    "-v",
                    "error",
                    "-print_format",
                    "json",
                    "-show_format",
                    str(gsm.PUBLIC / "hero-loop.mp4"),
                ]
            )
        )["format"].get("tags", {})
        self.assertNotIn("title", tags)

    def test_video_limits_fail_closed(self):
        ok = {
            "codec": "h264",
            "duration": 8.0,
            "width": 1920,
            "height": 1080,
            "frames": 192,
            "audio": False,
            "bytes": 2_900_000,
        }
        gsm.check_video(ok, "ok", max_seconds=8.1, width=1920, max_frames=192, max_bytes=3_300_000)
        gsm.check_video({**ok, "audio": True}, "original", max_seconds=8.5, audio_ok=True)
        bad = [
            ({"duration": 9.0}, {}),
            ({"width": 2560, "height": 1440}, {}),
            ({"width": 1080, "height": 1920}, {"width": 1920}),  # vertical: largura não confere
            ({"frames": 600}, {}),
            ({"frames": 0}, {}),
            ({"audio": True}, {}),
            ({"bytes": 4_000_000}, {"max_bytes": 3_300_000}),
            ({"codec": "mjpeg"}, {}),
            ({"frames": 193}, {"max_frames": 192}),
        ]
        for change, extra in bad:
            with self.assertRaises(SystemExit, msg=str(change)):
                gsm.check_video({**ok, **change}, "teste", max_seconds=8.1, **extra)

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg ausente")
    def test_out_of_limit_source_is_rejected_before_encoding_and_nothing_is_published(self):
        for name, lavfi in (
            ("longo", "testsrc2=size=320x180:rate=5:duration=10"),
            ("grande", "testsrc2=size=2048x256:rate=5:duration=1"),
        ):
            src = self.tmp / f"{name}.mp4"
            gsm._run(
                [
                    shutil.which("ffmpeg"),
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    lavfi,
                    "-c:v",
                    "libx264",
                    str(src),
                ]
            )
            with (
                mock.patch.object(gsm, "_run", wraps=gsm._run) as run,
                self.assertRaises(SystemExit, msg=name),
            ):
                gsm.encode_video(
                    "hero-loop", src, {"loop": True, "target_bytes": 150_000, "output_width": 320}
                )
            self.assertTrue(all("ffprobe" in Path(c.args[0][0]).name for c in run.call_args_list), name)
            self.assertFalse(gsm.PUBLIC.exists() and any(gsm.PUBLIC.iterdir()), name)

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg ausente")
    def test_encoded_video_over_size_ceiling_is_not_published(self):
        src = self.tmp / "src.mp4"
        gsm._run(
            [
                shutil.which("ffmpeg"),
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "testsrc2=size=640x360:rate=24:duration=2",
                "-c:v",
                "libx264",
                str(src),
            ]
        )
        with self.assertRaises(SystemExit):  # 2 KB é impossível para 2 s de vídeo: a saída passa do teto
            gsm.encode_video("hero-loop", src, {"loop": True, "target_bytes": 2_000, "output_width": 640})
        self.assertFalse(gsm.PUBLIC.exists() and any(gsm.PUBLIC.iterdir()))

    def test_image_payload_is_capped_before_decoding_and_checked_after(self):
        huge = "A" * (gsm.MAX_IMAGE_BYTES * 4 // 3 + 8)
        with (
            mock.patch.object(gsm, "call_api", return_value={"data": [{"b64_json": huge}]}),
            mock.patch.object(
                gsm.base64, "b64decode", side_effect=AssertionError("decodificou antes do teto")
            ),
            self.assertRaises(gsm.ApiError),
        ):
            gsm.generate_image(FAKE_KEY, image_item(), {})
        from PIL import Image

        for size in ((5000, 10), (10, 5000)):
            buf = io.BytesIO()
            Image.new("RGB", size).save(buf, "PNG")
            with self.assertRaises(gsm.ApiError, msg=str(size)):
                gsm.check_image(buf.getvalue())
        with self.assertRaises(gsm.ApiError):
            gsm.check_image(b"\x89PNG\r\n\x1a\n" + b"\0" * 64)  # assinatura certa, conteúdo corrompido
        buf = io.BytesIO()
        Image.new("RGB", (2048, 1152)).save(buf, "PNG")
        gsm.check_image(buf.getvalue())

    def test_ui_data_exposes_only_files_dimensions_and_alt(self):
        self.write_spec([image_item()], [])
        m = gsm.empty_manifest()
        m["assets"]["images"]["hero-still"] = {
            "prompt": "segredo de prompt",
            "model": "x",
            "costUsd": 0.1,
            "original": "hero-still.png",
            "variants": [{"file": "/site/hero-still-64.avif", "width": 64, "height": 36, "bytes": 10}],
        }
        gsm.write_ui_data(m, gsm.load_spec())
        ui = gsm.UI_DATA.read_text(encoding="utf-8")
        for leaked in ("segredo de prompt", "costUsd", "original", "bytes", "model"):
            self.assertNotIn(leaked, ui)
        self.assertEqual(json.loads(ui)["images"]["hero-still"]["alt"], "a")


if __name__ == "__main__":
    unittest.main()
