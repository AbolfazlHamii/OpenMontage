"""Retention lint for Persian narration: each check on a crafted script. No network."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from lib.fa_script_lint import lint, load_script, persian_summary
from tools.base_tool import ToolResult

REPO = Path(__file__).resolve().parents[2]


def _script(tmp_path, lines, title="آزمایش"):
    p = tmp_path / "draft.txt"
    p.write_text(f"# {title}\n" + "\n".join(lines), encoding="utf-8")
    return load_script(p)


def codes(report):
    return {f["code"] for f in report["findings"]}


def test_samsung_sample_estimate_is_close_to_the_real_narration(tmp_path):
    s = _script(tmp_path, [
        "احتمالاً گوشیِ توی دستت سامسونگه… ولی می‌دونستی این شرکت با فروش ماهی خشک شروع شد؟",
        "سال هزار و نهصد و نود و پنج، رئیس سامسونگ صد و پنجاه هزار تا گوشیِ خراب رو جلوی کارگرهاش آتیش زد!",
    ])
    r = lint(s, cps=9.0, target=15)
    # Real TTS lines (Kore, energetic): 6.60 s + 7.76 s.
    assert r["text"]["estimated_seconds"] == pytest.approx(14.36, rel=0.08)
    assert r["hook"]["first_hook_seconds"] < 3
    assert r["ending"]["primary"] == "twist"
    assert "sentence_long" in codes(r)


def test_late_hook_and_flat_ending_are_high_risk(tmp_path):
    s = _script(tmp_path, [
        "این شرکت در کره تأسیس شد و کار خود را با تجارت آغاز کرد و به تدریج رشد کرد.",
        "امروز این شرکت محصولات زیادی تولید می‌کند و در بازار حضور دارد.",
    ])
    r = lint(s, cps=9.5)
    assert r["risk"] == "high"
    assert {"hook_late", "ending_flat"} & codes(r) or "hook_missing" in codes(r)
    assert "register_mixed" in codes(r)


def test_digits_and_early_cta_are_flagged(tmp_path):
    s = _script(tmp_path, [
        "می‌دونستی سامسونگ ۱۹۳۸ شروع شد؟",
        "قبل از هر چیز سابسکرایب کن!",
        "ولی داستان اصلی از یه مغازه‌ی ماهی‌فروشی شروع شد.",
    ])
    r = lint(s, cps=9.5)
    assert {"digits", "cta_early"} <= codes(r)


def test_explicit_loops_open_and_close(tmp_path):
    s = _script(tmp_path, [
        "{{open:fish}}چرا یه شرکت ماهی‌فروشی الان گوشی می‌سازه؟",
        "سال هزار و نهصد و سی و هشت، توی دائگو، یه مغازه‌ی کوچیک باز شد.",
        "ولی سی سال بعد، یه تصمیم همه‌چی رو عوض کرد.",
        "{{close:fish}}جوابش یه کارخونه‌ی تلویزیون بود؛ همون‌جا ماهی‌فروشی شد غول الکترونیک.",
    ])
    r = lint(s, cps=9.5)
    loops = r["open_loops"]
    assert loops["opened"] == 1 and loops["closed"] == 1
    assert "loop_unclosed" not in codes(r)
    assert all("{{" not in t["text"] for t in r["timeline"])


def test_too_long_for_target(tmp_path):
    s = _script(tmp_path, ["ولی می‌دونستی؟ " + "این یه جمله‌ی خیلی طولانی برای تست طول متن است " * 6])
    r = lint(s, cps=9.5, target=5)
    assert "too_long" in codes(r)


def test_llm_loops_are_a_draft_only(tmp_path):
    class FakeLLM:
        def execute(self, inputs):
            assert inputs["task"] == "script_loop_review"
            return ToolResult(success=True, cost_usd=0.0005, data={
                "model": "deepseek-v4.1-flash",
                "json": {"loops": [{"question": "چرا؟", "opens": 0, "closes": None}]}})

    s = _script(tmp_path, ["می‌دونستی این شرکت با ماهی شروع شد؟", "ولی بعدش همه‌چی عوض شد!"])
    r = lint(s, cps=9.5, llm=FakeLLM())
    assert r["llm"]["status"] == "draft_for_agent_review" and r["llm"]["cost_usd"] == 0.0005
    assert r["open_loops"]["loops"][0]["source"] == "llm_draft"
    assert "مدل ارزان" in persian_summary(r)


def test_routing_has_the_lint_task():
    import yaml

    cfg = yaml.safe_load((REPO / "config" / "llm_routing.yaml").read_text(encoding="utf-8"))
    assert cfg["tasks"]["script_loop_review"]["tier"] == "worker"


def test_cli_reads_voice_pace_and_writes_report(tmp_path):
    sys.path.insert(0, str(REPO / "scripts"))
    import fa_script_lint as cli

    voices = tmp_path / "voices.yaml"
    voices.write_text("roles:\n  narrator: {cps: 9.0}\naudition_x:\n  - {voice: Charon, style: calm, cps: 9.61}\n",
                      encoding="utf-8")
    assert cli.voice_cps("narrator", path=voices) == 9.0
    assert cli.voice_cps("charon", "calm", path=voices) == 9.61
    assert cli.voice_cps("nobody", path=voices) is None
    draft = tmp_path / "d.txt"
    draft.write_text("می‌دونستی؟ ولی صبر کن!\n", encoding="utf-8")
    code = cli.main([str(draft), "--cps", "9.5", "--out", str(tmp_path / "r.json")])
    report = json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))
    assert code in (0, 1, 2) and report["cps"] == 9.5
