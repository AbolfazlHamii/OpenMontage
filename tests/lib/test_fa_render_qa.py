"""fa render QA: parsers and checks (pure), plus the editorial helpers. No media, no network."""

from __future__ import annotations

import json

import pytest

from lib import fa_editorial as ed
from lib.fa_render_qa import (
    check_av_sync,
    check_black,
    check_captions,
    check_duration,
    check_freeze,
    check_images_text,
    check_loudness,
    check_workspace_rtl,
    parse_blackdetect,
    parse_freezedetect,
    parse_srt,
    persian_summary,
)

RLM = "‏"


def test_loudness_check_matches_the_samsung_numbers():
    bad = check_loudness({"integrated_lufs": -11.5, "true_peak_dbtp": -2.9})
    assert bad.status == "fail" and "-11.5" in bad.detail
    assert check_loudness({"integrated_lufs": -14.03, "true_peak_dbtp": -5.2}).status == "pass"
    assert check_loudness({"integrated_lufs": -14.0, "true_peak_dbtp": -0.4}).status == "fail"


def test_ffmpeg_detector_parsers():
    black = "[blackdetect @ 0] black_start:0 black_end:0.4 black_duration:0.4\n" \
            "[blackdetect @ 0] black_start:7.1 black_end:7.5 black_duration:0.4"
    spans = parse_blackdetect(black)
    assert len(spans) == 2
    assert check_black(spans, 15).status == "fail"
    assert check_black(spans[:1], 15).status == "warn"
    freeze = "lavfi.freezedetect.freeze_start: 2.0\nlavfi.freezedetect.freeze_duration: 7.5\n"
    assert check_freeze(parse_freezedetect(freeze), 6).status == "warn"
    assert check_freeze([], 6).status == "pass"


def test_av_sync_and_duration():
    ok = [{"codec_type": "video", "start_time": "0", "duration": "15"},
          {"codec_type": "audio", "start_time": "0", "duration": "15.02"}]
    assert check_av_sync(ok).status == "pass"
    late = [ok[0], {"codec_type": "audio", "start_time": "0.2", "duration": "15"}]
    assert check_av_sync(late).status == "fail"
    assert check_av_sync(ok[:1]).status == "fail"
    assert check_duration(90.0, {"total_duration_seconds": 90}).status == "pass"
    assert check_duration(80.0, {"sections": [{"end_seconds": 90}]}).status == "fail"
    assert check_duration(80.0, None).status == "skipped"


def test_srt_captions_checks():
    srt = (f"1\n00:00:00,000 --> 00:00:02,000\n{RLM}سلام به همه\n\n"
           f"2\n00:00:01,500 --> 00:00:03,000\nبدون علامت راست‌به‌چپ\n\n"
           f"3\n00:00:03,000 --> 00:00:16,000\n{RLM}آخر\n")
    cues = parse_srt(srt)
    assert [c["start"] for c in cues] == [0.0, 1.5, 3.0]
    checks = {c.name: c for c in check_captions(cues, 15.0)}
    assert checks["caption_timing"].status == "fail"
    assert checks["caption_rtl"].status == "warn" and checks["caption_rtl"].evidence["cues"] == [1]
    assert checks["caption_safe_area"].status == "skipped"
    layout = {"boxes": [{"x": 0.1, "y": 0.8, "w": 0.8, "h": 0.17}], "safe_y": 0.05}
    safe = {c.name: c for c in check_captions(cues, 15.0, layout=layout)}["caption_safe_area"]
    assert safe.status == "fail"


def test_workspace_rtl_and_image_text():
    assert check_workspace_rtl('<html lang="fa"><div dir="rtl">سلام</div>').status == "pass"
    assert check_workspace_rtl('<html lang="fa"><div>سلام</div>').status == "warn"
    assert check_workspace_rtl("<html><p>hi</p>").status == "skipped"
    assert check_images_text([{"has_text": True, "script": "persian"}]).status == "fail"
    assert check_images_text([{"has_text": False, "script": "none"}]).status == "pass"


def test_persian_summary():
    report = {"render": "x/final.mp4", "status": "fail", "cost_usd": 0.0009, "checks": [
        {"name": "loudness", "status": "fail", "detail": "-11.5 LUFS"}]}
    text = persian_summary(report)
    assert "بلندی صدا" in text and "❌" in text and "$0.0009" in text


# -- editorial ------------------------------------------------------------------

def test_hook_decision_and_log(tmp_path):
    hooks = [{"text": f"هوک شماره {i}", "type": "number"} for i in range(12)]
    shortlist = [{"index": 2, "reason": "عدد بزرگ", "score": 0.9},
                 {"index": 5, "reason": "پارادوکس", "score": 0.8},
                 {"index": 9, "reason": "سؤال", "score": 0.7}]
    log = tmp_path / "decision_log.json"
    pending = ed.append_decision(log, ed.hook_decision(hooks, shortlist, None), "demo")
    assert pending["decision_id"] == "d1" and pending["selected"] == "pending_owner"
    chosen = ed.append_decision(log, ed.hook_decision(hooks, shortlist, 5))
    assert chosen["decision_id"] == "d2" and chosen["selected"] == "h5" and chosen["user_approved"]
    data = json.loads(log.read_text(encoding="utf-8"))
    assert [d["category"] for d in data["decisions"]] == ["hook_selection", "hook_selection"]
    assert data["decisions"][0]["subject"] == data["decisions"][1]["subject"]


def test_fact_check_requires_sources(tmp_path):
    claims = [{"claim": "سامسونگ ۱۹۳۸ تأسیس شد", "verdict": "verified", "source": "samsung.com/history"},
              {"claim": "۱۵۰ هزار گوشی", "verdict": "corrected", "source": "Korea Herald 1995"},
              {"claim": "۲۰٪ اقتصاد کره", "verdict": "removed", "note": "no reliable source"}]
    entry = ed.append_decision(tmp_path / "decision_log.json", ed.fact_check_decision(claims), "demo")
    assert entry["category"] == "fact_check" and entry["selected"] == "script_cleared"
    with pytest.raises(ValueError):
        ed.fact_check_decision([{"claim": "x", "verdict": "verified"}])
    with pytest.raises(ValueError):
        ed.fact_check_decision([{"claim": "x", "verdict": "maybe"}])
    pending = ed.fact_check_decision([{"claim": "x", "verdict": "unverified"}])
    assert pending["selected"] == "script_has_unverified_claims"


def test_prompts_and_script_text():
    assert "12" in ed.hooks_prompt("سامسونگ") and "no invented numbers" in ed.hooks_prompt("x")
    script = {"sections": [{"id": "s1", "text": "سلام"}, {"id": "s2", "text": "دنیا"}]}
    assert ed.script_text(script) == "[s1] سلام\n[s2] دنیا"
    assert "[s1] سلام" in ed.claims_prompt(ed.script_text(script))
