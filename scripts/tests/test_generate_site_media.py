"""Testes do gerador de mídia da landing (sem rede e sem chave real).

python -m unittest discover -s scripts/tests -v
"""

from __future__ import annotations

import io
import json
import shutil
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
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
        "fallback": "google/veo-3.1-lite",
        "resolution": "1080p",
        "aspect_ratio": "16:9",
        "duration": 8,
        "frame": "hero-still",
        "loop": True,
        "prompt": "p",
        "alt": "",
        **extra,
    }


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

    def test_authorization_is_not_forwarded_on_redirect(self):
        req, _ = gsm._request("GET", "videos/abc/content?index=0", FAKE_KEY, None)
        self.assertNotIn("Authorization", req.headers)  # fica em unredirected_hdrs
        self.assertEqual(req.unredirected_hdrs["Authorization"], f"Bearer {FAKE_KEY}")
        new = gsm._HttpsOnlyRedirect().redirect_request(
            req, None, 302, "Found", {}, "https://storage.example/v.mp4?sig=1"
        )
        self.assertIsNone(new.get_header("Authorization"))
        self.assertNotIn("Authorization", new.unredirected_hdrs)

    def test_redirect_to_plain_http_is_refused(self):
        req, _ = gsm._request("GET", "videos/abc/content", FAKE_KEY, None)
        with self.assertRaises(gsm.ApiError):
            gsm._HttpsOnlyRedirect().redirect_request(
                req, None, 302, "Found", {}, "http://storage.example/v.mp4"
            )

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


class Budget(unittest.TestCase):
    def test_failed_and_pending_calls_count_at_estimate(self):
        m = gsm.empty_manifest()
        m["calls"] = [
            {"kind": "image", "status": "ok", "costUsd": 0.1, "estimateUsd": 0.1},
            {"kind": "image", "status": "failed", "costUsd": None, "estimateUsd": 0.1},
            {"kind": "video", "status": "pending", "costUsd": None, "estimateUsd": 0.8},
        ]
        self.assertAlmostEqual(gsm.recorded_usd(m), 1.0)

    def test_call_limits_and_ceiling(self):
        m = gsm.empty_manifest()
        m["calls"] = [{"kind": "image", "status": "ok", "costUsd": 0.1, "estimateUsd": 0.1}] * 12
        self.assertIn("limite de 12", gsm.can_spend(m, "image", 0.1))
        m["calls"] = [{"kind": "video", "status": "ok", "costUsd": 0.8, "estimateUsd": 0.8}] * 4
        self.assertIn("limite de 4", gsm.can_spend(m, "video", 0.8))
        m["calls"] = [{"kind": "video", "status": "ok", "costUsd": 2.5, "estimateUsd": 0.8}]
        self.assertIn("orçamento", gsm.can_spend(m, "video", 0.8))
        self.assertIsNone(gsm.can_spend(m, "image", 0.1))
        self.assertIn("orçamento", gsm.can_spend(m, "image", 0.6))

    def test_ceiling_keeps_the_po_split_and_stops_before_exceeding(self):
        self.assertLessEqual(
            gsm.BUDGET_USD, 3.00
        )  # saldo de US$ 5: até US$ 3 para o site, US$ 2 reservados à IA
        m = gsm.empty_manifest()
        plan = [("image", 0.10)] * gsm.LIMITS["image"]["calls"] + [("video", 0.80)] * gsm.LIMITS["video"][
            "calls"
        ]
        for kind, estimate in plan:
            if gsm.can_spend(m, kind, estimate) is None:
                m["calls"].append(
                    {"kind": kind, "status": "failed", "costUsd": None, "estimateUsd": estimate}
                )
        self.assertLessEqual(gsm.recorded_usd(m), gsm.BUDGET_USD)


class SpecValidation(TempPaths):
    def test_rejects_unapproved_model_slug_duration_and_counts(self):
        cases = [
            ([image_item(model="openai/gpt-image-2")], []),
            ([image_item(resolution="4K")], []),
            ([image_item(slug="../../etc")], []),
            ([image_item()], [video_item(duration=10)]),
            ([image_item()], [video_item(model="google/veo-3.1")]),
            ([image_item(aspect_ratio="4:3")], [video_item()]),
            ([image_item(f"img-{i}") for i in range(9)], []),
        ]
        for images, videos in cases:
            self.write_spec(images, videos)
            with self.assertRaises(SystemExit, msg=json.dumps(images[0])[:80]):
                gsm.load_spec()

    def test_accepts_allowlisted_plan(self):
        self.write_spec([image_item()], [video_item()])
        self.assertEqual(len(gsm.load_spec()["videos"]), 1)


class Generation(TempPaths):
    def test_failed_image_call_is_recorded_before_sending_and_sanitized(self):
        self.write_spec([image_item()])
        m = gsm.empty_manifest()

        def boom(key, item, body):
            self.assertEqual(
                json.loads(gsm.MANIFEST.read_text(encoding="utf-8"))["calls"][0]["status"], "pending"
            )
            raise gsm.ApiError(f"HTTP 500 em POST /api/v1/images: upstream echoed {FAKE_KEY}", 500)

        with mock.patch.object(gsm, "generate_image", boom):
            self.assertEqual(gsm.run_image(FAKE_KEY, image_item(), m), "failed")
        saved = gsm.MANIFEST.read_text(encoding="utf-8")
        self.assertNotIn(FAKE_KEY, saved)
        self.assertEqual(json.loads(saved)["calls"][0]["status"], "failed")
        self.assertAlmostEqual(gsm.recorded_usd(m), 0.10)

    def test_fatal_error_stops_the_run(self):
        m = gsm.empty_manifest()
        with mock.patch.object(
            gsm, "generate_image", side_effect=gsm.ApiError("HTTP 402 em POST /api/v1/images", 402)
        ):
            self.assertEqual(gsm.run_image(FAKE_KEY, image_item(), m), "stop")

    def test_submitted_video_is_resumed_without_new_paid_call(self):
        m = gsm.empty_manifest()
        m["calls"].append(
            {
                "kind": "video",
                "slug": "hero-loop",
                "model": "google/veo-3.1-fast",
                "status": "submitted",
                "jobId": "job-1",
                "estimateUsd": 0.8,
                "costUsd": None,
                "at": "t",
            }
        )
        with (
            mock.patch.object(gsm, "submit_video") as submit,
            mock.patch.object(gsm, "_finish_video", return_value="ok") as finish,
        ):
            self.assertEqual(gsm.run_video(FAKE_KEY, video_item(), m), "ok")
        submit.assert_not_called()
        self.assertEqual(finish.call_args.args[4]["id"], "job-1")
        self.assertEqual(len(m["calls"]), 1)

    def test_video_falls_back_once_and_counts_both_calls(self):
        m = gsm.empty_manifest()
        with (
            mock.patch.object(gsm, "video_body", return_value={}),
            mock.patch.object(
                gsm, "submit_video", side_effect=[gsm.ApiError("HTTP 503", 503), {"id": "job-2"}]
            ),
            mock.patch.object(gsm, "_finish_video", return_value="ok"),
        ):
            self.assertEqual(gsm.run_video(FAKE_KEY, video_item(), m), "ok")
        self.assertEqual([c["model"] for c in m["calls"]], ["google/veo-3.1-fast", "google/veo-3.1-lite"])
        self.assertAlmostEqual(gsm.recorded_usd(m), 0.8 + 0.4)

    def test_dry_run_never_reads_key_nor_posts(self):
        self.write_spec([image_item()], [video_item()])
        seen = []

        def fake_call(method, path, key=None, body=None):
            seen.append((method, path, key))
            if path.startswith("images/models/"):
                return {
                    "endpoints": [
                        {"pricing": [{"billable": "output_image", "variant": "2k", "cost_usd": 0.1}]}
                    ]
                }
            return {
                "data": [
                    {
                        "id": mid,
                        "pricing_skus": {gsm.VIDEO_SKU: str(rule["usd_per_s"])},
                        "supported_durations": [4, 6, 8],
                        "supported_resolutions": ["1080p"],
                        "supported_aspect_ratios": ["16:9"],
                        "supported_frame_images": ["first_frame", "last_frame"],
                    }
                    for mid, rule in gsm.VIDEO_MODELS.items()
                ]
            }

        with (
            mock.patch.object(gsm, "call_api", fake_call),
            mock.patch.object(gsm, "read_key", side_effect=AssertionError("dry-run leu a chave")),
            mock.patch.object(sys, "argv", ["x", "--dry-run"]),
            mock.patch("sys.stdout", io.StringIO()),
        ):
            self.assertEqual(gsm.main(), 0)
        self.assertTrue(seen)
        self.assertTrue(all(method == "GET" and key is None for method, _, key in seen))
        self.assertFalse(gsm.MANIFEST.exists())

    def test_live_price_above_approved_blocks_generation(self):
        self.write_spec([image_item()])
        expensive = {
            "endpoints": [{"pricing": [{"billable": "output_image", "variant": "2k", "cost_usd": 0.2}]}]
        }
        with (
            mock.patch.object(gsm, "call_api", return_value=expensive),
            mock.patch.object(gsm, "read_key", side_effect=AssertionError("não devia ler a chave")),
            mock.patch.object(sys, "argv", ["x"]),
            mock.patch("sys.stdout", io.StringIO()),
        ):
            self.assertEqual(gsm.main(), 1)


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
        self.assertTrue(out["checks"]["mp4WithinTarget"] and out["checks"]["webmWithinTarget"])
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
