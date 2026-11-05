"""Packaging helper: title rubric, worker drafts (fake selector), topic rubric,
chapters, tags and description. No network."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from lib import fa_packaging as fp

KEYWORD = "سامسونگ"


# ---- title rubric ------------------------------------------------------------

def test_good_title_scores_full():
    r = fp.score_title("کل تاریخ سامسونگ در ۹۰ ثانیه", KEYWORD)
    assert r["score"] == 100, r["notes"]
    assert set(r["devices"]) >= {"number", "time_box"}


@pytest.mark.parametrize("title, part, note", [
    ("کل تاريخ سامسونگ در ۹۰ ثانيه", "spelling", "Arabic"),
    ("سامسونگ چطور غول گوشی ها شد؟", "spelling", "plural"),
    ("سامسونگ چرا گوشی‌هاشو می سوزوند؟", "spelling", "half-space"),
    ("کل تاریخ سامسونگ در 90 ثانیه", "spelling", "Latin digits"),
    ("تاریخ باورنکردنی سامسونگ!!", "clickbait", "clickbait"),
    ("Samsung از ماهی تا گوشی", "bidi", "Latin word"),
    ("کل تاریخ برند کره‌ای در ۹۰ ثانیه", "subject", "missing"),
])
def test_title_problems(title, part, note):
    r = fp.score_title(title, KEYWORD)
    assert r["parts"][part] < {"spelling": 20, "clickbait": 10, "bidi": 10, "subject": 20}[part]
    assert any(note in n for n in r["notes"]), r["notes"]


def test_title_length_and_late_subject():
    long_title = "داستان یک شرکت کوچک کره‌ای که از فروش ماهی خشک شروع کرد و امروز " + KEYWORD + " " + "ب" * 40
    r = fp.score_title(long_title, KEYWORD)
    assert r["parts"]["length"] == 0 and r["chars"] > fp.TITLE_MAX
    assert r["parts"]["subject"] == 10


def test_alias_counts_as_subject():
    assert fp.score_title("تاریخ Samsung در ۹۰ ثانیه", "سامسونگ", ["Samsung"])["parts"]["subject"] == 20


def test_title_prompt_carries_the_brief():
    prompt = fp.title_prompt({"topic": "Samsung", "keyword": KEYWORD, "count": 12,
                              "facts": ["1938: dried fish"], "avoid": ["اپل"]})
    assert "12 YouTube title options" in prompt
    assert KEYWORD in prompt and "1938: dried fish" in prompt and "اپل" in prompt
    for name in fp.PATTERNS:
        assert name in prompt


class FakeSelector:
    def __init__(self, result):
        self.result = result
        self.inputs = None

    def execute(self, inputs):
        self.inputs = inputs
        return self.result


def test_draft_titles_scores_and_sorts():
    answer = {"titles": [{"title": "سامسونگ با ماهی شروع شد", "pattern": "origin_twist"},
                         {"title": "کل تاریخ سامسونگ در ۹۰ ثانیه", "pattern": "time_box"},
                         {"pattern": "broken"}],
              "tags": ["سامسونگ"]}
    selector = FakeSelector(SimpleNamespace(success=True, error=None, cost_usd=0.004,
                                            data={"json": answer, "model": "m", "tier": "worker",
                                                  "attempts": [{"outcome": "accepted"}]}))
    out = fp.draft_titles({"keyword": KEYWORD}, selector=selector, cost_log_path="log.json")
    assert selector.inputs["task"] == "title_tag_variants"
    assert selector.inputs["json_schema"] == fp.TITLE_SCHEMA
    assert selector.inputs["max_tokens"] >= 4000 and selector.inputs["cost_log_path"] == "log.json"
    assert [d["title"] for d in out["drafts"]] == ["کل تاریخ سامسونگ در ۹۰ ثانیه", "سامسونگ با ماهی شروع شد"]
    assert out["tags"] == ["سامسونگ"] and out["cost_usd"] == 0.004


def test_draft_titles_reads_json_inside_text_and_reports_failure():
    text = 'Here: {"titles": [{"title": "تاریخ سامسونگ"}]} done'
    ok = FakeSelector(SimpleNamespace(success=True, error=None, cost_usd=0.0, data={"text": text}))
    assert fp.draft_titles({"keyword": KEYWORD}, selector=ok)["drafts"][0]["title"] == "تاریخ سامسونگ"
    failed = FakeSelector(SimpleNamespace(success=False, error="ESCALATE TO AGENT", cost_usd=0.002,
                                          data={"attempts": [{"outcome": "rejected"}]}))
    out = fp.draft_titles({"keyword": KEYWORD}, selector=failed)
    assert not out["success"] and out["drafts"] == [] and out["attempts"]


# ---- topic rubric ------------------------------------------------------------

def topic(**kw):
    base = {"name": "t", **{k: 5 for k in fp.TOPIC_WEIGHTS}, "risk": 0}
    return {**base, **kw}


def test_topic_weights_sum_to_100():
    assert sum(fp.TOPIC_WEIGHTS.values()) == 100
    assert fp.score_topic(topic())["score"] == 100


def test_topic_risk_and_verdicts():
    risky = fp.score_topic(topic(risk=5))
    assert risky["score"] == 70 and risky["risk_penalty"] == 30 and risky["verdict"] == "make it"
    assert fp.score_topic(topic(demand=1, twist=1))["score"] == 64
    assert fp.score_topic(topic(demand=1, twist=1))["verdict"] == "owner's call"
    assert fp.score_topic(topic(demand=1, twist=1, visual=1))["verdict"].startswith("drop")
    with pytest.raises(ValueError):
        fp.score_topic(topic(demand=7))


def test_rank_topics_orders_and_numbers():
    ranked = fp.rank_topics([topic(name="b", twist=2), topic(name="a")])
    assert [(t["rank"], t["name"]) for t in ranked] == [(1, "a"), (2, "b")]


def test_repo_topic_list_is_valid():
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "docs" / "fa" / "packaging" / "topics_candidates.json"
    ranked = fp.rank_topics(json.loads(path.read_text(encoding="utf-8")))
    assert len(ranked) >= 10 and all(t.get("why") and t.get("hook") for t in ranked)


# ---- chapters, tags, description -------------------------------------------

def test_timestamp():
    assert fp.timestamp(0) == "0:00"
    assert fp.timestamp(76.4) == "1:16"
    assert fp.timestamp(3725) == "1:02:05"


def test_build_chapters_merges_short_sections_and_starts_at_zero():
    sections = [
        {"id": "s1", "chapter": "هوک", "start_seconds": 0.5, "end_seconds": 6},
        {"id": "s2", "chapter": "۱۹۳۸", "start_seconds": 6, "end_seconds": 22},
        {"id": "s3", "chapter": "۱۹۶۹", "start_seconds": 22, "end_seconds": 38},
        {"id": "s3b", "start_seconds": 38, "end_seconds": 45},  # no label: continues ۱۹۶۹
        {"id": "s4", "chapter": "۱۹۹۳", "start_seconds": 45, "end_seconds": 52},
        {"id": "s5", "chapter": "امروز", "start_seconds": 52, "end_seconds": 90},
    ]
    chapters, notes = fp.build_chapters(sections)
    assert [(c["start_seconds"], c["title"]) for c in chapters] == [(0.0, "۱۹۳۸"), (22, "۱۹۶۹"), (52, "امروز")]
    assert any("۱۹۹۳" in n for n in notes) and any("هوک" in n for n in notes)
    assert fp.chapter_lines(chapters)[0] == "0:00 ۱۹۳۸"


def test_build_chapters_needs_three():
    chapters, notes = fp.build_chapters([
        {"label": "a", "start_seconds": 0, "end_seconds": 40},
        {"label": "b", "start_seconds": 40, "end_seconds": 90},
    ])
    assert chapters == [] and "YouTube needs 3" in notes[-1]


def test_spelling_variants():
    variants = fp.spelling_variants("ماهی‌فروشی ۱۹۳۸")
    assert "ماهي‌فروشي ۱۹۳۸" in variants
    assert "ماهی فروشی ۱۹۳۸" in variants and "ماهیفروشی ۱۹۳۸" in variants
    assert "ماهی‌فروشی 1938" in variants
    assert fp.spelling_variants("Samsung") == ["Samsung"]


def test_build_tags_fits_youtube_limit():
    tags = fp.build_tags(KEYWORD, ["Samsung"], ["گلکسی"] * 3 + [f"tag {i}" for i in range(80)], "سری")
    assert tags[0] == KEYWORD and "Samsung" in tags and "Samsung history" in tags
    assert "تاريخچه سامسونگ" in tags  # misspelling variant: what tags are for
    assert len(tags) == len({t.lower() for t in tags})
    assert len(",".join(tags)) <= fp.TAGS_MAX_CHARS


def test_build_description_layout_and_checks():
    chapters = [{"start_seconds": 0, "title": "الف"}, {"start_seconds": 20, "title": "ب"},
                {"start_seconds": 40, "title": "ج"}]
    text = fp.build_description("هوک", f"کل تاریخچه {KEYWORD}", chapters,
                                sources=[{"title": "TechCrunch", "url": "https://t.co/x"}, {"title": "no url"}],
                                music="Track — Artist", hashtags=["سامسونگ", "#تاریخ", "a", "b"])
    lines = text.splitlines()
    assert lines[:2] == ["هوک", f"کل تاریخچه {KEYWORD}"]
    assert "0:20 ب" in text and "- TechCrunch: https://t.co/x" in text and "no url" not in text
    assert lines[-1] == "#سامسونگ #تاریخ #a"
    assert fp.description_report(text, KEYWORD)["problems"] == []
    bad = fp.description_report("هوک\n<b>متن</b>", KEYWORD)["problems"]
    assert any("keyword" in p for p in bad) and any("angle" in p for p in bad)


# ---- CLI -----------------------------------------------------------------------

def test_cli_topics_and_describe(tmp_path):
    from scripts import fa_packaging as cli

    topics = tmp_path / "topics.json"
    topics.write_text(json.dumps([topic(name="نوکیا"), topic(name="ال‌جی", twist=1)], ensure_ascii=False),
                      encoding="utf-8")
    assert cli.main(["topics", "--topics", str(topics), "--out", str(tmp_path / "ranked.json")]) == 0
    ranked = json.loads((tmp_path / "ranked.json").read_text(encoding="utf-8"))
    assert ranked[0]["name"] == "نوکیا"

    script = tmp_path / "script.json"
    script.write_text(json.dumps({"sections": [
        {"id": "a", "start_seconds": 0, "end_seconds": 30, "text": ""},
        {"id": "b", "start_seconds": 30, "end_seconds": 60, "text": ""},
        {"id": "c", "start_seconds": 60, "end_seconds": 90, "text": ""},
    ]}), encoding="utf-8")
    meta = tmp_path / "meta.json"
    meta.write_text(json.dumps({"title": "t", "keyword": KEYWORD, "hook": "هوک",
                                "summary": f"تاریخچه {KEYWORD}", "hashtags": [KEYWORD],
                                "chapters": {"a": "یک", "b": "دو", "c": "سه"},
                                "sources": [{"title": "s", "url": "https://x.org"}]},
                               ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "out"
    assert cli.main(["describe", "--script", str(script), "--meta", str(meta), "--out", str(out)]) == 0
    assert (out / "chapters.txt").read_text(encoding="utf-8").splitlines() == ["0:00 یک", "0:30 دو", "1:00 سه"]
    metadata = json.loads((out / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["chapters"][1] == {"start_seconds": 30, "title": "دو"}
    assert metadata["hashtags"] == ["#" + KEYWORD]


def test_cli_titles_dry_run_makes_no_call(tmp_path, monkeypatch):
    from scripts import fa_packaging as cli

    monkeypatch.setattr(fp, "draft_titles", lambda *a, **k: pytest.fail("no API call in a dry run"))
    brief = tmp_path / "brief.json"
    brief.write_text(json.dumps({"keyword": KEYWORD, "topic": "Samsung"}, ensure_ascii=False), encoding="utf-8")
    assert cli.main(["titles", "--brief", str(brief), "--out", str(tmp_path), "--dry-run"]) == 0
    assert KEYWORD in (tmp_path / "title_prompt.txt").read_text(encoding="utf-8")
