"""The Archivist prototype: retrieval, moderation routing, fact-check, cipher.

No network: the LLM is a fake that answers by system prompt.
"""

from __future__ import annotations

import numpy as np

from lib.archivist.archive import Archive, Chunk, normalize
from lib.archivist.brain import NOT_IN_ARCHIVE, Brain, cipher_guess, rule_gate, split_sentences
from lib.archivist.cipher import ROUNDS, CipherGame, encode
from lib.archivist.show import mouth_track
from tools.base_tool import ToolResult


def small_archive() -> Archive:
    return Archive([
        Chunk("MI6-s01", "MI6", "script", "بیروت، ژانویه‌ی هزار و نهصد و شصت و سه. فیلبی غیب می‌شه. مقصد؟ مسکو."),
        Chunk("MI6-s02", "MI6", "script", "کامینگ نامه‌ها رو فقط با یه حرف امضا می‌کرد: «سی». همیشه با جوهرِ سبز."),
        Chunk("KGB-s01", "KGB", "script", "یه گروه بچه‌مدرسه‌ای به سفیرِ آمریکا یه نشانِ چوبی هدیه می‌دن؛ توش شنود بود."),
    ])


class FakeLLM:
    def __init__(self, replies: dict):
        self.replies = replies
        self.calls = []

    def execute(self, inputs):
        self.calls.append(inputs)
        for key, reply in self.replies.items():
            if key in inputs["system"]:
                return ToolResult(success=True, data={"json": reply}, cost_usd=0.0)
        raise AssertionError("unexpected prompt")


def test_normalize_folds_agency_spellings():
    assert normalize("KGB") == normalize("کاگ ب") == "کا گ ب"
    assert "ام آی سیکس" in normalize("رئیس MI6")


def test_search_finds_the_named_person():
    hits = small_archive().search("فیلبی چطوری فرار کرد؟", k=1)
    assert hits[0][1].id == "MI6-s01"


def test_search_brings_the_next_chunk_of_a_story():
    hits = small_archive().search("فیلبی", k=1)
    assert [c.id for _, c in hits] == ["MI6-s01", "MI6-s02"]


def test_rule_gate_catches_links_spam_and_cipher():
    assert rule_gate("ببین www.example.com")[0] == "spam"
    assert rule_gate("aaaaaaaaaaaa")[0] == "spam"
    assert rule_gate("!کد ENIGMA")[0] == "cipher"
    assert cipher_guess("!code  enigma ") == "enigma"
    assert rule_gate("کیم فیلبی کی بود؟") == (None, "")


def test_abusive_and_political_messages_are_dropped_without_an_answer():
    for category in ("abusive", "political_bait", "spam"):
        llm = FakeLLM({"moderate the live chat": {"category": category, "reason": "x"}})
        turn = Brain(small_archive(), llm).handle("u", "متن")
        assert turn.action == "drop" and turn.answer == ""
        assert len(llm.calls) == 1


def test_off_topic_gets_the_canned_refusal():
    llm = FakeLLM({"moderate the live chat": {"category": "off_topic"}})
    turn = Brain(small_archive(), llm).handle("u", "آیفون بخرم یا سامسونگ؟")
    assert turn.action == "not_in_archive" and turn.answer == NOT_IN_ARCHIVE


def test_question_outside_the_files_is_refused():
    llm = FakeLLM({"moderate the live chat": {"category": "question"},
                   "You are \"The Archivist\"": {"in_archive": False, "answer": ""}})
    turn = Brain(small_archive(), llm).handle("u", "سیا کی تأسیس شد؟")
    assert turn.action == "not_in_archive"


def test_fact_check_removes_unsupported_sentences():
    good = "سلام آرمان، پرونده‌ش این‌جاست. " + "کامینگ با جوهرِ سبز امضا می‌کرد. " * 6
    bad = "این سنت صد و بیست و شش ساله‌ست."
    llm = FakeLLM({"moderate the live chat": {"category": "question"},
                   "You are \"The Archivist\"": {"in_archive": True, "answer": good + " " + bad,
                                                 "files": ["MI6-s02", "nope"]},
                   "You fact-check": {"unsupported": [bad]}})
    turn = Brain(small_archive(), llm).handle("Arman.R", "چرا جوهر سبز؟")
    assert turn.action == "answer"
    assert "بیست و شش" not in turn.answer
    assert turn.files == ["MI6-s02"]
    assert any("fact-check removed" in n for n in turn.notes)


def test_split_sentences_keeps_persian_question_marks():
    assert split_sentences("کی بود؟ فیلبی. رفت…  مسکو!") == ["کی بود؟", "فیلبی.", "رفت…", "مسکو!"]


def test_cipher_encodings():
    assert encode(ROUNDS[0]) == "HQLJPD"
    assert encode(ROUNDS[1]) == "OFYBZMPZ"


def test_cipher_scores_first_three_once():
    game = CipherGame(board={"a": 1})
    game.start(ROUNDS[0])
    assert game.guess("a", "enigma") == 3
    assert game.guess("a", "ENIGMA") == 0  # same agent twice
    assert game.guess("b", "wrong") == 0
    assert game.guess("b", "E N I G M A") == 2
    assert game.guess("c", "enigma") == 1
    assert game.guess("d", "enigma") == 0
    assert game.top(2) == [("a", 4), ("b", 2)]


def test_mouth_track_opens_on_loud_frames_only():
    rate = 24000
    silence = np.zeros(rate // 2, np.float32)
    tone = 0.5 * np.sin(np.arange(rate // 2) / rate * 2 * np.pi * 150).astype(np.float32)
    shapes = mouth_track(np.concatenate([silence, tone, silence]), rate)
    assert shapes[:10].max() == 0
    assert shapes[16:22].min() == 2
    assert shapes[-8:].max() == 0
