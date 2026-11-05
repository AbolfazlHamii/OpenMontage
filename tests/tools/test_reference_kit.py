"""reference_kit: URL handling, captions, budgets, rights, and the kit it writes. No network."""

from __future__ import annotations

import json

import pytest

from tools.analysis import reference_kit as rk
from tools.analysis.reference_kit import (
    ReferenceKit,
    chunk_transcript,
    classify_url,
    parse_vtt,
    persian_summary,
)


@pytest.mark.parametrize("url,platform,kind,vid", [
    ("https://www.youtube.com/shorts/-62C9R_41Sc", "youtube", "short", "-62C9R_41Sc"),
    ("https://youtube.com/shorts/abc123XYZ?feature=share", "youtube", "short", "abc123XYZ"),
    ("https://www.youtube.com/watch?v=_OuJBX6Q4Cc", "youtube", "long", "_OuJBX6Q4Cc"),
    ("https://www.youtube.com/watch?list=PL1&v=_OuJBX6Q4Cc&t=4", "youtube", "long", "_OuJBX6Q4Cc"),
    ("https://youtu.be/_OuJBX6Q4Cc", "youtube", "long", "_OuJBX6Q4Cc"),
    ("https://www.instagram.com/reel/DCyQ3ySOlBb/", "instagram", "reel", "DCyQ3ySOlBb"),
    ("https://www.instagram.com/nasa/reels/DCyQ3ySOlBb/", "instagram", "reel", "DCyQ3ySOlBb"),
    ("https://www.instagram.com/p/DCyQ3ySOlBb/", "instagram", "post", "DCyQ3ySOlBb"),
    ("https://www.tiktok.com/@nasa/video/7301234567890", "tiktok", "short", "7301234567890"),
    ("https://x.com/nasa/status/1850000000", "x", "video", "1850000000"),
    ("https://vimeo.com/123", "other", "unknown", None),
])
def test_classify_url(url, platform, kind, vid):
    assert classify_url(url) == {"platform": platform, "kind": kind, "id": vid}


ROLLING_VTT = """WEBVTT
Kind: captions
Language: en

00:00:00.320 --> 00:00:03.040
Every day, around 2 billion

00:00:03.040 --> 00:00:05.520
Every day, around 2 billion servings of one drink

00:00:05.520 --> 00:00:07.000 align:start
<c>It started</c> as a failed medicine.
"""


def test_parse_vtt_drops_rolling_repeats():
    segs = parse_vtt(ROLLING_VTT)
    assert [s["text"] for s in segs] == ["Every day, around 2 billion", "servings of one drink",
                                          "It started as a failed medicine."]
    assert segs[0]["start"] == 0.32 and segs[-1]["end"] == 7.0


def test_chunk_transcript():
    segs = [{"start": t, "end": t + 5, "text": f"w{t}"} for t in range(0, 300, 10)]
    chunks = chunk_transcript(segs, 90)
    assert [c["start"] for c in chunks] == [0, 90, 180, 270]
    assert chunks[0]["text"].startswith("w0 w10")


def test_costs_scale_with_length_and_captions():
    kit = ReferenceKit()
    short = kit.plan_costs(60, has_captions=True, steps=ReferenceKit.ALL_STEPS)
    long = kit.plan_costs(661, has_captions=False, steps=ReferenceKit.ALL_STEPS)
    assert short["transcript"] == 0.0 and long["transcript"] == pytest.approx(0.0661)
    assert short["total"] < 0.03 < long["total"] < 0.15
    assert kit.plan_costs(661, True, ("outline",))["style"] == 0.0
    # Gemini measured on AvalAI 2026-11-05: 39 s $0.0084, first 480 s of a long video $0.0562.
    assert kit.plan_costs(39, True, ("gemini",))["gemini"] == pytest.approx(0.0084, rel=0.1)
    assert kit.plan_costs(661, True, ("gemini",))["gemini"] == pytest.approx(0.0562, rel=0.1)


def test_dub_without_rights_is_refused():
    r = ReferenceKit().execute({"url": "https://youtu.be/x1234567", "mode": "dub"})
    assert not r.success and r.data["needs"] == "rights" and "transcreate" in r.error


def test_instagram_access_error_explains_cookies(monkeypatch):
    kit = ReferenceKit()
    monkeypatch.setattr(kit, "direct_reachable", lambda url: True)
    monkeypatch.setattr(kit, "metadata", lambda url, cookies: (_ for _ in ()).throw(
        RuntimeError("direct: Instagram sent an empty media response; proxy: same")))
    r = kit.execute({"url": "https://www.instagram.com/reel/ABCdef123/"})
    assert not r.success and r.data["needs"] == "access"
    assert "cookies_file" in r.error and "input_path" in r.error


def _fake_kit(monkeypatch, tmp_path, captions=True, vertical=True, duration=58.0, stt_cost=0.0058):
    kit = ReferenceKit()
    meta = {"title": "From the Moon to the 50-Yard Line", "duration": duration, "uploader": "NASA",
            "view_count": 12345, "language": "en", "has_subtitles": [], "has_auto_captions": ["en"]}
    monkeypatch.setattr(kit, "direct_reachable", lambda url: True)
    monkeypatch.setattr(kit, "metadata", lambda url, cookies: (meta, "direct"))

    def download(url, folder, cookies, expected):
        p = folder / "source.mp4"
        p.write_bytes(b"video")
        return p, "direct"

    segs = [{"start": 0.0, "end": 4.0, "text": "In 1969 Apollo 11 landed on the Moon."},
            {"start": 4.0, "end": 9.0, "text": "Fifty years later the same flag flew over a stadium."}]
    monkeypatch.setattr(kit, "download", download)
    monkeypatch.setattr(kit, "captions", lambda *a: segs if captions else [])
    monkeypatch.setattr(kit, "transcribe", lambda video, folder, language=None: (segs, stt_cost))
    monkeypatch.setattr(rk, "probe_seconds", lambda p: duration)
    monkeypatch.setattr(rk, "probe_size", lambda p: (720, 1280) if vertical else (1280, 720))
    calls = []

    def step(name, value, cost=0.001):
        def fn(*a, **k):
            calls.append(name)
            return value, cost, None
        return fn

    monkeypatch.setattr(kit, "_style", step("style", {"card_path": str(tmp_path / "x-learned.yaml"),
                                                      "asl_seconds": 2.4, "shots": 24}, 0.009))
    monkeypatch.setattr(kit, "_gemini", step("gemini", {"hook": {"technique": "cold open", "why_it_works": "x"},
                                                        "story_beats": [{"time": "00:01", "beat": "landing"}],
                                                        "visual_style": {"medium": "archival footage"}}, 0.004))
    monkeypatch.setattr(kit, "_outline", step("outline", [{"start": "00:00", "end": "00:58", "summary": "s"}]))
    monkeypatch.setattr(kit, "_claims", step("claims", [{"claim": "1969 landing", "kind": "date",
                                                         "verdict": "unverified", "source": None}]))
    monkeypatch.setattr(kit, "_translate", step("translate", "در سال ۱۹۶۹ آپولو ۱۱ روی ماه نشست."))
    return kit, calls


def test_full_kit_for_a_short(monkeypatch, tmp_path):
    kit, calls = _fake_kit(monkeypatch, tmp_path)
    r = kit.execute({"url": "https://www.youtube.com/shorts/-62C9R_41Sc", "out_root": str(tmp_path)})
    assert r.success, r.error
    folder = tmp_path / "from-the-moon-to-the-50-yard-line"
    for name in ("transcript.json", "outline.json", "claims.json", "transcript_fa_draft.txt",
                 "remake_brief.json", "REMAKE_fa.md"):
        assert (folder / name).exists(), name
    brief = json.loads((folder / "remake_brief.json").read_text(encoding="utf-8"))
    assert brief["source"]["kind"] == "short" and brief["format"]["aspect"] == "9:16"
    assert brief["format"]["profile"] == "youtube_shorts" and brief["format"]["target_seconds"] == 58
    assert brief["mode"] == "transcreate" and "never the source's footage" in brief["rights"]["rule"]
    assert brief["pacing"]["edit_style_card"] == "x-learned"
    assert "live footage of the source is never reused" in brief["recommendation"]["pipeline"]
    assert brief["estimate"]["final_usd"] > brief["estimate"]["draft_usd"] > 0
    assert r.cost_usd == pytest.approx(0.009 + 0.004 + 0.003)
    assert brief["cost"]["actual"] == {"style": 0.009, "gemini": 0.004, "outline": 0.001, "claims": 0.001,
                                       "translate": 0.001}
    assert calls == ["style", "gemini", "outline", "claims", "translate"]
    assert "Raw material" in (folder / "transcript_fa_draft.txt").read_text(encoding="utf-8")
    md = (folder / "REMAKE_fa.md").read_text(encoding="utf-8")
    assert "شورتس" in md and "بازتولید" in md


def test_long_video_without_captions_pays_for_stt_and_respects_budget(monkeypatch, tmp_path):
    # 11 min without captions: whisper-1 costs ~$0.066, which leaves room for
    # the cheap text steps but not for frame labels or Gemini under $0.07.
    kit, calls = _fake_kit(monkeypatch, tmp_path, captions=False, vertical=False, duration=661.0,
                           stt_cost=0.0661)
    r = kit.execute({"url": "https://www.youtube.com/watch?v=_OuJBX6Q4Cc", "out_root": str(tmp_path),
                     "budget_usd": 0.07, "target_seconds": 90})
    assert r.success
    brief = r.data["brief"]
    assert brief["source"]["kind"] == "long" and brief["format"]["aspect"] == "16:9"
    assert brief["format"]["target_seconds"] == 90
    assert any("whisper-1" in n for n in brief["notes"])
    skipped = {n.split(":")[0] for n in brief["notes"] if "skipped" in n}
    assert {"style", "gemini"} <= skipped and "outline" in calls
    assert brief["cost"]["spent_usd"] <= 0.07 + 1e-9


def test_dub_with_rights_points_to_the_dub_pipeline(monkeypatch, tmp_path):
    kit, _ = _fake_kit(monkeypatch, tmp_path)
    r = kit.execute({"url": "https://www.youtube.com/shorts/-62C9R_41Sc", "out_root": str(tmp_path),
                     "mode": "dub", "rights": "own", "steps": ["gemini"]})
    assert r.success
    b = r.data["brief"]
    assert b["recommendation"]["pipeline"].startswith("localization-dub")
    assert "--rights own" in b["next_steps"][0]


def test_summary_mentions_skips_and_cost():
    b = {"slug": "x", "mode": "transcreate", "source": {"platform": "youtube", "kind": "long", "title": "T",
         "duration_seconds": 661, "views": 1000, "uploader": "U"}, "format": {"aspect": "16:9", "target_seconds": 90},
         "transcript": {"segments": 10, "words_per_minute": 157.0}, "pacing": {}, "hook": {}, "visual_style": {},
         "outline": [], "claims_to_verify": 0, "estimate": None, "rights": {"rule": "r"},
         "next_steps": ["n"], "notes": ["gemini: skipped"], "cost": {"spent_usd": 0.01, "budget_usd": 0.1}}
    md = persian_summary(b)
    assert "ویدیوی بلند" in md and "gemini: skipped" in md and "$0.0100" in md


def test_avalai_goes_direct_during_the_run_and_env_is_restored(monkeypatch):
    monkeypatch.setenv("NO_PROXY", "localhost,127.0.0.1")
    monkeypatch.delenv("AVALAI_BASE_URL", raising=False)
    seen = {}
    kit = ReferenceKit()
    monkeypatch.setattr(kit, "_execute", lambda inputs: seen.setdefault("no_proxy", rk.os.environ["NO_PROXY"]))
    kit.execute({"url": "https://youtu.be/x1234567"})
    assert seen["no_proxy"] == "localhost,127.0.0.1,api.avalai.ir"
    assert rk.os.environ["NO_PROXY"] == "localhost,127.0.0.1"


class _FakeSTT:
    calls: list = []

    def execute(self, request):
        _FakeSTT.calls.append(request)
        from tools.base_tool import ToolResult
        if len(_FakeSTT.calls) == 1:
            return ToolResult(success=False, error="avalai_stt: ReadTimeout: read timed out")
        return ToolResult(success=True, data={"segments": [{"start": 0, "end": 2, "text": " Hello "}]},
                          cost_usd=0.0002)


def test_transcribe_sends_the_source_language_and_retries_once(monkeypatch, tmp_path):
    import tools.analysis.avalai_stt as stt

    _FakeSTT.calls = []
    monkeypatch.setattr(stt, "AvalAISTT", _FakeSTT)
    monkeypatch.setattr(rk.subprocess, "run", lambda *a, **k: None)
    segs, cost = ReferenceKit().transcribe(tmp_path / "source.mp4", tmp_path, "en")
    assert [c["language"] for c in _FakeSTT.calls] == ["en", "en"]
    assert segs == [{"start": 0.0, "end": 2.0, "text": "Hello"}] and cost == 0.0002
    _FakeSTT.calls = []
    ReferenceKit().transcribe(tmp_path / "source.mp4", tmp_path)
    assert _FakeSTT.calls[0]["language"] == ""  # unknown: the model detects it


def test_the_route_that_worked_goes_first_next_time():
    kit = ReferenceKit()
    tried = []

    def youtube(proxy):
        tried.append(proxy)
        if proxy is None:
            raise ConnectionRefusedError("[WinError 10061] refused")
        return "ok"

    assert kit._with_routes(youtube)[:2] == ("ok", "proxy")
    assert kit._with_routes(youtube)[:2] == ("ok", "proxy")
    assert tried == [None, rk.PROXY, rk.PROXY]


def test_unreachable_direct_route_means_proxy_only(monkeypatch, tmp_path):
    # Studio FA has no HTTPS_PROXY: YouTube refuses the direct route, and a
    # 429 on the proxy must not send captions back there for ~3 minutes.
    kit, _ = _fake_kit(monkeypatch, tmp_path)
    monkeypatch.setattr(kit, "direct_reachable", lambda url: False)
    r = kit.execute({"url": "https://www.youtube.com/shorts/-62C9R_41Sc", "out_root": str(tmp_path),
                     "steps": ["outline"]})
    assert "direct route does not reach the site; proxy only" in r.data["brief"]["notes"]
    tried = []

    def captions(proxy):
        tried.append(proxy)
        raise RuntimeError("HTTP Error 429: Too Many Requests")

    with pytest.raises(RuntimeError, match="429"):
        kit._with_routes(captions)
    assert tried == [rk.PROXY]
