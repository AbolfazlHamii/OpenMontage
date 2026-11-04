"""AvalAI Gemini image adapter and the google_imagen -> AvalAI mirror fall-through.

No network: requests.post is replaced with a fake.
"""

from __future__ import annotations

import base64
import io
from pathlib import Path

import pytest
from PIL import Image

from tools.base_tool import ToolResult, ToolStatus
from tools.graphics.avalai_gemini_image import AvalAIGeminiImage
from tools.graphics.google_imagen import GoogleImagen
from tools.graphics.image_selector import MIRROR_ORDER, ImageSelector
from tools.provider_routing import short_error

GOOGLE_403_PAGE = (
    "<!DOCTYPE html><html lang=en><meta charset=utf-8>"
    "<title>Error 403 (Forbidden)!!1</title>"
    "<style>*{margin:0;padding:0}html,code{font:15px/22px arial,sans-serif}"
    "html{background:#fff;color:#222;padding:15px}</style>"
    "<a href=//www.google.com/><span id=logo aria-label=Google></span></a>"
    "<p><b>403.</b> <ins>That&#8217;s an error.</ins><p>Your client does not have "
    "permission to get URL <code>/v1beta/models</code> from this server. "
    "<ins>That&#8217;s all we know.</ins>"
)


def _image_bytes(fmt="PNG") -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), "red").save(buf, format=fmt)
    return buf.getvalue()


class _FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


def _image_payload(data: bytes, mime="image/png"):
    return {
        "candidates": [{
            "content": {"parts": [
                {"text": "Here is your image."},
                {"inlineData": {"mimeType": mime, "data": base64.b64encode(data).decode()}},
            ]}
        }]
    }


@pytest.fixture
def avalai_key(monkeypatch):
    monkeypatch.setenv("AVALAI_API_KEY", "test-key")
    monkeypatch.delenv("AVALAI_BASE_URL", raising=False)


@pytest.fixture
def posts(monkeypatch):
    """Record each request and answer with a PNG."""
    calls: list = []

    def fake_post(url, headers, json, timeout):
        calls.append({"url": url, "headers": headers, "json": json})
        return _FakeResponse(payload=_image_payload(_image_bytes()))

    monkeypatch.setattr("requests.post", fake_post)
    return calls


def test_request_carries_prompt_aspect_ratio_and_size():
    request = AvalAIGeminiImage().build_request(
        {"prompt": "a dried-fish shop in 1938 Daegu", "aspect_ratio": "16:9", "resolution": "2K"}
    )
    assert request["model"] == "gemini-3.1-flash-image"
    body = request["body"]
    assert body["contents"][0]["parts"] == [{"text": "a dried-fish shop in 1938 Daegu"}]
    assert body["generationConfig"]["imageConfig"] == {"aspectRatio": "16:9", "imageSize": "2K"}
    assert "IMAGE" in body["generationConfig"]["responseModalities"]


def test_width_height_map_to_aspect_ratio():
    request = AvalAIGeminiImage().build_request({"prompt": "x", "width": 1920, "height": 1080})
    assert request["body"]["generationConfig"]["imageConfig"]["aspectRatio"] == "16:9"


def test_reference_images_become_inline_data(tmp_path):
    ref = tmp_path / "ref.jpg"
    ref.write_bytes(_image_bytes("JPEG"))
    request = AvalAIGeminiImage().build_request(
        {"prompt": "same phone, on a desk", "generation_mode": "edit", "image_path": str(ref)}
    )
    part = request["body"]["contents"][0]["parts"][1]["inlineData"]
    assert part["mimeType"] == "image/jpeg"
    assert base64.b64decode(part["data"]) == ref.read_bytes()


@pytest.mark.parametrize(
    "inputs, message",
    [
        ({"model": "imagen-4.0-generate-001"}, "Unsupported"),
        ({"image_url": "https://example.com/a.png"}, "not image URLs"),
        ({"generation_mode": "edit"}, "Edit requires"),
        ({"model": "gemini-2.5-flash-image", "resolution": "2K"}, "does not offer 2K"),
        ({"image_paths": ["a.png"] * 15}, "At most 14"),
    ],
)
def test_bad_inputs_are_rejected(inputs, message):
    with pytest.raises(ValueError, match=message):
        AvalAIGeminiImage().build_request({"prompt": "x", **inputs})


def test_status_follows_key(monkeypatch):
    monkeypatch.delenv("AVALAI_API_KEY", raising=False)
    assert AvalAIGeminiImage().get_status() == ToolStatus.UNAVAILABLE
    monkeypatch.setenv("AVALAI_API_KEY", "k")
    assert AvalAIGeminiImage().get_status() == ToolStatus.AVAILABLE


def test_cost_is_per_image_and_size():
    tool = AvalAIGeminiImage()
    assert tool.estimate_cost({}) == 0.0672
    assert tool.estimate_cost({"resolution": "4K", "number_of_images": 2}) == 0.302
    assert tool.estimate_cost({"model": "gemini-3-pro-image", "resolution": "2K"}) == 0.134


def test_execute_writes_png(tmp_path, avalai_key, posts):
    out = tmp_path / "hook.png"
    result = AvalAIGeminiImage().execute({"prompt": "x", "output_path": str(out)})
    assert result.success, result.error
    assert posts[0]["url"] == "https://api.avalai.ir/v1beta/models/gemini-3.1-flash-image:generateContent"
    assert posts[0]["headers"]["Authorization"] == "Bearer test-key"
    assert out.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    assert result.cost_usd == 0.0672
    assert result.data["provider"] == "avalai"


def test_several_images_get_numbered_paths(tmp_path, avalai_key, posts):
    result = AvalAIGeminiImage().execute(
        {"prompt": "x", "number_of_images": 2, "output_path": str(tmp_path / "s.png")}
    )
    assert result.success, result.error
    assert len(posts) == 2
    assert [Path(p).name for p in result.data["outputs"]] == ["s_1.png", "s_2.png"]
    assert result.cost_usd == 0.1344


def test_jpeg_answer_is_reencoded_for_png_path(monkeypatch, tmp_path, avalai_key):
    monkeypatch.setattr(
        "requests.post",
        lambda *a, **k: _FakeResponse(payload=_image_payload(_image_bytes("JPEG"), "image/jpeg")),
    )
    out = tmp_path / "a.png"
    assert AvalAIGeminiImage().execute({"prompt": "x", "output_path": str(out)}).success
    assert out.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_http_error_is_reported(monkeypatch, tmp_path, avalai_key):
    monkeypatch.setattr(
        "requests.post", lambda *a, **k: _FakeResponse(status_code=402, text="insufficient credit")
    )
    result = AvalAIGeminiImage().execute({"prompt": "x", "output_path": str(tmp_path / "a.png")})
    assert not result.success
    assert "402" in result.error and "credit" in result.error


def test_text_only_answer_is_a_clear_error(monkeypatch, tmp_path, avalai_key):
    payload = {"candidates": [{"content": {"parts": [{"text": "I can't draw that."}]}}]}
    monkeypatch.setattr("requests.post", lambda *a, **k: _FakeResponse(payload=payload))
    result = AvalAIGeminiImage().execute({"prompt": "x", "output_path": str(tmp_path / "a.png")})
    assert not result.success
    assert "No image data" in result.error


def test_short_error_keeps_only_the_text_of_html_pages():
    short = short_error("Gemini image generation failed: 403 " + GOOGLE_403_PAGE)
    assert "<" not in short and "margin" not in short
    assert "403" in short and "does not have permission" in short
    assert short_error("x" * 500).endswith("…") and len(short_error("x" * 500)) == 300
    # google-genai's ClientError repr()s the payload, newlines escaped.
    sdk = "403 Forbidden. {'message': ' \\n \\n Error 403 (Forbidden)!!1 \\n', 'status': 'Forbidden'}"
    assert short_error(sdk) == "403 Forbidden. {'message': ' Error 403 (Forbidden)!!1 ', 'status': 'Forbidden'}"


# ---- selector mirror fall-through ------------------------------------------

def _install(monkeypatch, behaviours, calls):
    """behaviours: list of (tool_class, error or None for success)."""
    for cls, error in behaviours:
        def fake_execute(self, inputs, _error=error):
            calls.append((self.name, inputs.get("model")))
            if _error:
                return ToolResult(success=False, error=_error)
            return ToolResult(success=True, data={"output": "a.png", "model": inputs.get("model")})

        monkeypatch.setattr(cls, "get_status", lambda self: ToolStatus.AVAILABLE)
        monkeypatch.setattr(cls, "execute", fake_execute)
    monkeypatch.setattr(ImageSelector, "_providers", lambda self: [c() for c, _ in behaviours])


def test_google_comes_before_avalai():
    assert MIRROR_ORDER.index("avalai_gemini_image") > MIRROR_ORDER.index("google_imagen")


def test_pinned_model_tries_google_first(monkeypatch):
    calls: list = []
    _install(monkeypatch, [(AvalAIGeminiImage, None), (GoogleImagen, None)], calls)
    result = ImageSelector().execute({"prompt": "x", "model": "gemini-3.1-flash-image"})
    assert result.success, result.error
    assert calls == [("google_imagen", "gemini-3.1-flash-image")]


def test_google_refusal_falls_back_to_avalai_with_same_model(monkeypatch):
    calls: list = []
    error = "Gemini image generation failed: 403 Forbidden. " + GOOGLE_403_PAGE
    _install(monkeypatch, [(GoogleImagen, error), (AvalAIGeminiImage, None)], calls)
    result = ImageSelector().execute({"prompt": "x", "model": "gemini-3.1-flash-image"})
    assert result.success, result.error
    assert calls == [
        ("google_imagen", "gemini-3.1-flash-image"),
        ("avalai_gemini_image", "gemini-3.1-flash-image"),
    ]
    assert result.data["selected_tool"] == "avalai_gemini_image"
    failure = result.data["fallback_from"][0]
    assert failure["tool"] == "google_imagen"
    assert "<" not in failure["error"] and "403" in failure["error"]


def test_both_failing_reports_both(monkeypatch):
    calls: list = []
    _install(monkeypatch, [(GoogleImagen, "403 Forbidden"), (AvalAIGeminiImage, "402 no credit")], calls)
    result = ImageSelector().execute({"prompt": "x", "model": "gemini-3.1-flash-image"})
    assert not result.success
    assert "google_imagen: 403 Forbidden" in result.error and "402 no credit" in result.error


def test_explicit_provider_does_not_fall_through(monkeypatch):
    calls: list = []
    _install(monkeypatch, [(GoogleImagen, "403 Forbidden"), (AvalAIGeminiImage, None)], calls)
    result = ImageSelector().execute({
        "prompt": "x", "model": "gemini-3.1-flash-image", "preferred_provider": "google_imagen",
    })
    assert not result.success
    assert [name for name, _ in calls] == ["google_imagen"]


def test_no_fall_through_when_avalai_lacks_the_model(monkeypatch):
    calls: list = []
    _install(monkeypatch, [(GoogleImagen, "403 Forbidden"), (AvalAIGeminiImage, None)], calls)
    result = ImageSelector().execute({"prompt": "x", "model": "gemini-nano-banana-2.1"})
    assert not result.success
    assert [name for name, _ in calls] == ["google_imagen"]


def test_allowed_providers_can_exclude_avalai(monkeypatch):
    calls: list = []
    _install(monkeypatch, [(GoogleImagen, "403 Forbidden"), (AvalAIGeminiImage, None)], calls)
    result = ImageSelector().execute({
        "prompt": "x", "model": "gemini-3.1-flash-image", "allowed_providers": ["google_imagen"],
    })
    assert not result.success
    assert [name for name, _ in calls] == ["google_imagen"]
