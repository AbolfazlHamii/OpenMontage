"""gemini_video_analyze: request shape, routes, fallback, cost. No network."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools.analysis import gemini_video_analyze as gva
from tools.base_tool import ToolResult

URL = "https://www.youtube.com/watch?v=_OuJBX6Q4Cc"
ANSWER = {
    "duration_seconds": 180,
    "story_beats": [{"time": "00:00", "beat": "big number hook"}],
    "hook": {"summary": "s", "technique": "paradox", "why_it_works": "w", "first_line": "f"},
    "average_shot_length_seconds": 3.75,
    "cuts_per_minute": 16,
    "visual_style": {"medium": "2D stills"},
    "on_screen_text": [],
    "segments": [{"start": "00:00", "end": "00:12", "speaker": "narrator",
                  "emotion": "excited", "energy": "high", "summary": "intro"}],
    "music_and_sound": "upbeat",
}


class FakeModels:
    def __init__(self, text=None, error=None):
        self.text, self.error, self.calls = text, error, []

    def generate_content(self, model, contents, config):
        self.calls.append({"model": model, "contents": contents, "config": config})
        if self.error:
            raise self.error
        usage = SimpleNamespace(prompt_token_count=17_640, candidates_token_count=1_200)
        return SimpleNamespace(text=self.text, usage_metadata=usage)


@pytest.fixture
def google(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "g-key")
    models = FakeModels(text=json.dumps(ANSWER))
    monkeypatch.setattr("tools.google_credentials.get_genai_client",
                        lambda *a, **k: SimpleNamespace(models=models))
    return models


def test_youtube_url_is_passed_by_link_with_offsets(google, tmp_path):
    out = tmp_path / "analysis.json"
    result = gva.GeminiVideoAnalyze().execute({
        "source": URL, "start_offset": "0:00", "end_offset": "3:00", "fps": 1,
        "output_path": str(out),
    })
    assert result.success, result.error
    part = google.calls[0]["contents"][0]["parts"][0]
    assert part["file_data"] == {"file_uri": URL, "mime_type": "video/*"}
    assert part["video_metadata"] == {"start_offset": "0s", "end_offset": "180s", "fps": 1.0}
    assert google.calls[0]["config"]["media_resolution"] == "MEDIA_RESOLUTION_LOW"
    assert google.calls[0]["config"]["response_mime_type"] == "application/json"
    assert result.data["route"] == "google"
    assert result.data["analysis"]["average_shot_length_seconds"] == 3.75
    assert result.cost_usd == pytest.approx((17_640 * 0.75 + 1_200 * 3.75) / 1e6)
    saved = json.loads(out.read_text(encoding="utf-8"))
    assert saved["_meta"]["model"] == "gemini-3.8-flash"


def test_google_refusal_falls_through_to_avalai(monkeypatch, tmp_path):
    monkeypatch.setenv("GOOGLE_API_KEY", "g-key")
    monkeypatch.setenv("AVALAI_API_KEY", "a-key")
    monkeypatch.delenv("AVALAI_BASE_URL", raising=False)
    models = FakeModels(error=RuntimeError("403 <html><title>Forbidden</title></html>"))
    monkeypatch.setattr("tools.google_credentials.get_genai_client",
                        lambda *a, **k: SimpleNamespace(models=models))
    video = tmp_path / "ref.mp4"
    video.write_bytes(b"fake-mp4")
    posted = {}

    def fake_post(url, headers, json, timeout):
        posted.update(url=url, body=json)
        return SimpleNamespace(status_code=200, json=lambda: {
            "candidates": [{"content": {"parts": [{"text": "```json\n" + _dumps(ANSWER) + "\n```"}]}}],
            "usageMetadata": {"promptTokenCount": 6_500, "candidatesTokenCount": 100},
        })

    monkeypatch.setattr("requests.post", fake_post)
    result = gva.GeminiVideoAnalyze().execute({"source": str(video), "end_offset": 60})

    assert result.success, result.error
    assert result.data["route"] == "avalai"
    assert result.data["fallback_from"][0]["route"] == "google"
    assert "<html>" not in result.data["fallback_from"][0]["error"]
    assert result.data["analysis"]["_meta"]["ingest_check"] == "ok"
    assert posted["url"] == "https://api.avalai.ir/v1beta/models/gemini-3.8-flash:generateContent"
    part = posted["body"]["contents"][0]["parts"][0]
    assert part["inlineData"]["mimeType"] == "video/mp4"
    assert part["videoMetadata"]["endOffset"] == "60s"
    assert posted["body"]["generationConfig"]["mediaResolution"] == "MEDIA_RESOLUTION_LOW"


def test_avalai_refuses_youtube_links_without_calling(monkeypatch):
    monkeypatch.setenv("AVALAI_API_KEY", "a-key")
    monkeypatch.setattr("requests.post", lambda *a, **k: pytest.fail("must not call"))
    result = gva.GeminiVideoAnalyze().execute(
        {"source": URL, "route": "avalai", "fallback_local": False})
    assert not result.success and "YouTube links" in result.error


def test_answer_written_without_the_video_is_refused_and_still_billed(google, monkeypatch):
    monkeypatch.delenv("AVALAI_API_KEY", raising=False)
    usage = SimpleNamespace(prompt_token_count=434, candidates_token_count=1310)
    google.generate_content = lambda model, contents, config: SimpleNamespace(
        text=json.dumps(ANSWER), usage_metadata=usage)
    result = gva.GeminiVideoAnalyze().execute(
        {"source": URL, "end_offset": 180, "fallback_local": False})
    assert not result.success
    assert "without the video" in result.error
    assert result.cost_usd == pytest.approx((434 * 0.75 + 1310 * 3.75) / 1e6)


def test_large_local_file_is_sent_as_a_small_proxy(monkeypatch, tmp_path):
    monkeypatch.setattr(gva, "INLINE_LIMIT_BYTES", 10)
    video = tmp_path / "big.mp4"
    video.write_bytes(b"x" * 100)
    commands = []

    def fake_run(self, cmd, timeout=None, **kwargs):
        commands.append(cmd)
        Path(cmd[-1]).write_bytes(b"small")

    monkeypatch.setattr(gva.GeminiVideoAnalyze, "run_command", fake_run)
    part = gva.GeminiVideoAnalyze()._inline_part({"local_path": str(video)})
    assert "scale=-2:360" in commands[0]
    assert part["inline_data"]["data"] == "c21hbGw="


def _dumps(value):
    return json.dumps(value, ensure_ascii=False)


def test_local_file_goes_inline_on_avalai(monkeypatch, tmp_path):
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr("tools.google_credentials.service_account_configured", lambda: False)
    monkeypatch.setenv("AVALAI_API_KEY", "a-key")
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"fake-mp4")
    bodies = []
    monkeypatch.setattr("requests.post", lambda url, headers, json, timeout: (
        bodies.append(json) or SimpleNamespace(status_code=200, json=lambda: {
            "candidates": [{"content": {"parts": [{"text": _dumps(ANSWER)}]}}]})))
    result = gva.GeminiVideoAnalyze().execute({"source": str(video), "fallback_local": False})
    assert result.success, result.error
    inline = bodies[0]["contents"][0]["parts"][0]["inlineData"]
    assert inline["mimeType"] == "video/mp4" and inline["data"]
    assert result.data["fallback_from"][0]["error"].endswith("no Google credentials")


def test_every_route_failing_falls_back_to_local_analyzer(monkeypatch):
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("AVALAI_API_KEY", raising=False)
    monkeypatch.setattr("tools.google_credentials.service_account_configured", lambda: False)
    seen = {}

    def fake_local(self, inputs):
        seen.update(inputs)
        return ToolResult(success=True, data={"scenes": []})

    monkeypatch.setattr("tools.analysis.video_analyzer.VideoAnalyzer.execute", fake_local)
    result = gva.GeminiVideoAnalyze().execute({"source": URL})
    assert result.success
    assert seen["source"] == URL
    assert result.data["analysis_source"] == "video_analyzer"
    assert [f["route"] for f in result.data["fallback_from"]] == ["google", "avalai"]


def test_without_local_fallback_reports_all_failures(monkeypatch):
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("AVALAI_API_KEY", raising=False)
    monkeypatch.setattr("tools.google_credentials.service_account_configured", lambda: False)
    result = gva.GeminiVideoAnalyze().execute({"source": URL, "fallback_local": False})
    assert not result.success
    assert "google" in result.error and "avalai" in result.error


def test_bad_answer_is_a_route_failure(google, monkeypatch):
    monkeypatch.delenv("AVALAI_API_KEY", raising=False)
    google.text = '{"duration_seconds": 10}'
    result = gva.GeminiVideoAnalyze().execute({"source": URL, "fallback_local": False})
    assert not result.success and "missing" in result.error


def test_non_youtube_links_are_refused():
    result = gva.GeminiVideoAnalyze().execute({"source": "https://example.com/v.mp4"})
    assert not result.success and "YouTube" in result.error


@pytest.mark.parametrize("value, seconds", [(90, 90.0), ("90", 90.0), ("90s", 90.0),
                                            ("1:30", 90.0), ("01:02:03", 3723.0), (None, None)])
def test_parse_offset(value, seconds):
    assert gva.parse_offset(value) == seconds


def test_estimate_is_about_100_tokens_per_second():
    tool = gva.GeminiVideoAnalyze()
    three_minutes = tool.estimate_cost({"source": URL, "end_offset": "3:00"})
    assert three_minutes == pytest.approx((180 * 98 * 0.75 + 3000 * 3.75) / 1e6, abs=1e-4)
    assert tool.estimate_cost({"source": URL, "media_resolution": "default",
                               "duration_hint_seconds": 60}) > tool.estimate_cost(
        {"source": URL, "duration_hint_seconds": 60})
