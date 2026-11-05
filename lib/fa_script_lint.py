"""Retention lint for a Persian narration script.

Reads a plain-text draft or a script artifact (schemas/artifacts/script.schema.json)
and places every sentence on a timeline from the narrator's measured pace
(cps = spoken letters per second, voices.yaml). Then it reports hook timing,
open loops, re-hook spacing, sentence rhythm, specificity, the ending type,
register and TTS-text problems, with a retention-risk summary in Persian.

The patterns are heuristics for spoken Tehrani Persian. They flag, they do
not decide: the report feeds the script director's review and the owner's
approval (skills/creative/narration-craft.md explains each check).

Open loops can be marked explicitly:
- plain text: ``{{open:fish}}`` ... ``{{close:fish}}`` (stripped before timing);
- script JSON: ``metadata.loops = [{"id", "question", "opens": <section id>,
  "closes": <section id or null>}]`` (section text goes to TTS verbatim, so
  markers do not belong there).
Without markers, questions are reported as possible loops and the optional
worker-tier pass (``llm_loops``) drafts opened/closed pairs for the agent to
review.
"""

from __future__ import annotations

import json
import re
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from lib import fa_text

DEFAULT_CPS = 9.5  # narrator audition 2026-11-04: 8.6-10.5, most voices 9-10

# Inline TTS events are not spoken but take time (estimates, not measured).
PAUSE_SECONDS = {"short pause": 0.4, "pause": 0.8, "long pause": 1.5, "laugh": 0.6, "sigh": 0.6}
_TAG = re.compile(r"[<\[]\s*([a-z][a-z ]{1,20}?)\s*[>\]]")
_MARKER = re.compile(r"\{\{\s*(open|close)\s*:\s*([\w-]+)\s*\}\}")
_SENTENCE_END = re.compile(r"[^.!?؟\n]+(?:[.!?؟]+|\n|$)")

# Thresholds (seconds unless noted). Sources and evidence level per rule are
# in skills/creative/narration-craft.md.
HOOK_WARN, HOOK_FAIL = 3.0, 5.0
LOOP_BY = 10.0
REHOOK_WARN, REHOOK_FAIL = 8.0, 12.0
MAX_OPEN_LOOPS = 3
LONG_SENTENCE = 7.0
PUNCH_SENTENCE = 1.5
MONOTONE_CV = 0.25
SPECIFIC_PER_10S = 0.5
END_SIGNAL_BEFORE = 0.85  # share of the runtime
CTA_TOO_EARLY = 30.0
OUTRO_MAX = 8.0  # seconds of trailing subscribe/comment requests


def _fold(text: str) -> str:
    """Same-length folding for matching: one spelling per letter, ZWNJ as space."""
    return text.translate(str.maketrans({"ي": "ی", "ى": "ی", "ك": "ک", fa_text.ZWNJ: " "}))


def _words(*items: str, suffix: bool = False) -> re.Pattern:
    """Whole-word alternation. suffix=True also takes the attached spoken
    copula/object/ezafe endings («دستته»، «سامسونگه»، «گوشیتو»)."""
    # re.escape writes a space as "\ "; replace the escaped form, or the
    # pattern asks for a literal backslash and multi-word items never match.
    alts = sorted({re.escape(_fold(w)).replace(r"\ ", r"\s+") for w in items}, key=len, reverse=True)
    tail = r"(?:ه|ی|و|رو)?" if suffix else ""
    return re.compile(r"(?<!\w)(?:" + "|".join(alts) + r")" + tail + r"(?!\w)")


YOU = _words("دستت", "جیبت", "گوشیت", "خودت", "بهت", "برات", "ازت", "باهات", "می‌دونستی",
             "میدونستی", "شنیدی", "دیدی", "فکرشو بکن", "فکرشو کن", "فکر کن", "تصور کن", "حدس بزن", "ببین",
             "می‌گی", "میگی",
             "بذار بگم", "باورت می‌شه", "باورت میشه", "شما", "خودتون", "بهتون", suffix=True)
TURN = _words("ولی", "اما", "امّا", "یهو", "یکهو", "ناگهان", "تا این‌که", "تا اینکه", "برعکس",
              "در عوض", "با این‌که", "با اینکه", "در حالی که", "عجیبه", "اینجا بود که",
              "این‌جا بود که", "اینجاست که", "نکته اینه", "حدس بزن")
THEREFORE = _words("پس", "برای همین", "واسه همین", "به همین خاطر", "در نتیجه", "باعث شد",
                   "این شد که")
AND_THEN = _words("و بعد", "بعدش", "و بعدش", "بعد از اون", "بعد هم", "سپس")
VAGUE = _words("خیلی", "کلی", "یه عالمه", "عالمه", "چندین", "صدها", "هزاران", "میلیون‌ها",
               "میلیونها", "میلیاردها", "بسیار", "تعداد زیادی", "یه سری", "بعضی")
CTA_SUBSCRIBE = _words("سابسکرایب", "ساب کن", "لایک", "زنگوله", "فالو", "دنبال کن", "عضو شو",
                       "عضو بشو", "عضو کانال")
CTA_COMMENT = _words("کامنت", "کامنت‌ها", "بنویس", "برامون بنویس", "نظرت", "نظرتون")
NEXT_EPISODE = _words("قسمت بعد", "قسمت بعدی", "ویدیوی بعد", "ویدیوی بعدی", "ویدیو بعدی",
                      "دفعه‌ی بعد", "دفعه بعد", "اپیزود بعد", "هفته‌ی بعد")
END_SIGNAL = _words("خلاصه", "در کل", "در آخر", "در پایان", "خب دیگه", "تموم شد", "جمع‌بندی",
                    "حرف آخر", "اینم از")
FORMAL = _words("است", "هستند", "می‌باشد", "می‌باشند", "می‌شود", "نمی‌شود", "می‌کند",
                "می‌کنند", "می‌گوید", "می‌گویند", "آن", "آنها", "آن‌ها", "را", "همچنین",
                "بنابراین", "لذا", "سپس", "گردید", "نمود", "نمودند", "می‌گردد", "وی", "ایشان")
_SPOKEN_NUMBERS = ["پونصد", "شیش", "شیشصد", "هفصد", "هیفده", "هیجده", "پونزده", "شونزده", "یه"]
_NUMBER_WORDS = [w for w in fa_text._ONES + fa_text._TEENS + fa_text._TENS + fa_text._HUNDREDS
                 + fa_text._SCALES if w] + _SPOKEN_NUMBERS
_NUM = "(?:" + "|".join(sorted(_NUMBER_WORDS, key=len, reverse=True)) + ")"
NUMBER_RUN = re.compile(rf"(?<!\w){_NUM}(?:\s+و\s+{_NUM}|\s+{_NUM})*(?!\w)")
# «یک/یه» is usually "a", «نه» usually "no": a run of only these is not a number.
_AMBIGUOUS = {"یک", "یه", "نه"}
YEAR = re.compile(rf"(?<!\w)سال(?:ِ)?\s+{_NUM}(?:\s+و\s+{_NUM}|\s+{_NUM})*")
LATIN_NAME = re.compile(r"[A-Za-z][A-Za-z.-]+")
STOPWORDS = {"و", "که", "از", "به", "با", "در", "این", "اون", "یه", "رو", "را", "تو", "توی", "هم",
             "ولی", "اما", "شد", "بود", "کرد", "می", "ها", "های", "اینه", "یعنی", "برای", "واسه",
             "همه", "چی", "کی", "هر", "تا", "اگه", "دیگه", "خب", "حالا"}


@dataclass
class Sentence:
    index: int
    section_id: str
    text: str
    spoken: str
    letters: int
    start: float = 0.0
    end: float = 0.0
    pause_before: float = 0.0
    marks: list[tuple[str, str]] = field(default_factory=list)
    features: dict[str, Any] = field(default_factory=dict)

    @property
    def seconds(self) -> float:
        return self.end - self.start


# -- loading ---------------------------------------------------------------------

def load_script(path: Path) -> dict[str, Any]:
    """Plain text (one section per non-empty line, '#' lines are the title) or
    a script artifact. Returns {title, sections, loops, names, target_seconds, source}."""
    raw = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        data = json.loads(raw)
        meta = data.get("metadata") or {}
        sections = []
        for s in data.get("sections", []):
            cues = s.get("delivery_cues") or {}
            sections.append({"id": s["id"], "text": s["text"], "spoken": cues.get("provider_text") or s["text"],
                             "start_seconds": s.get("start_seconds"), "end_seconds": s.get("end_seconds"),
                             "pause_before": cues.get("pause_before_seconds", 0.0),
                             "pause_after": cues.get("pause_after_seconds", 0.0)})
        return {"title": data.get("title", path.stem), "sections": sections, "loops": meta.get("loops", []),
                "names": meta.get("names", []), "target_seconds": data.get("total_duration_seconds"),
                "source": "json"}
    title, sections = path.stem, []
    for line in raw.splitlines():
        line = line.strip()
        if line.startswith("#"):
            title = line.lstrip("# ").strip() or title
        elif line:
            sections.append({"id": f"s{len(sections) + 1}", "text": line, "spoken": line})
    return {"title": title, "sections": sections, "loops": [], "names": [], "target_seconds": None,
            "source": "text"}


def _spoken_form(text: str) -> tuple[str, float, list[tuple[str, str]]]:
    """Text as heard, without loop markers and TTS tags. Returns the text, the
    seconds the tags add, and the markers as (open|close, id)."""
    marks = [(m.group(1), m.group(2)) for m in _MARKER.finditer(text)]
    text = _MARKER.sub(" ", text)
    pause = sum(PAUSE_SECONDS.get(m.group(1).strip(), 0.3) for m in _TAG.finditer(text))
    return _TAG.sub(" ", text), pause, marks


def _letters(text: str) -> int:
    return sum(1 for ch in fa_text.normalize(fa_text.spell_numbers(text)) if not ch.isspace())


def split_sentences(script: dict[str, Any], cps: float) -> list[Sentence]:
    """Sentences with estimated start/end seconds. A section with a later
    start_seconds (music gap) starts there; otherwise speech runs on."""
    sentences: list[Sentence] = []
    clock = 0.0
    for sec in script["sections"]:
        spoken_src = sec.get("spoken") or sec["text"]
        clock = max(clock, float(sec.get("start_seconds") or 0.0)) + float(sec.get("pause_before") or 0.0)
        for m in _SENTENCE_END.finditer(spoken_src):
            chunk = m.group().strip()
            if not chunk or not _letters(_spoken_form(chunk)[0]):
                if chunk:  # a lone tag or marker: keep its pause and markers
                    _, pause, marks = _spoken_form(chunk)
                    clock += pause
                    if sentences:
                        sentences[-1].marks += marks
                continue
            spoken, pause, marks = _spoken_form(chunk)
            spoken = " ".join(fa_text.spell_numbers(spoken).split())
            s = Sentence(index=len(sentences), section_id=sec["id"],
                         text=" ".join(_MARKER.sub(" ", chunk).split()),
                         spoken=spoken, letters=_letters(spoken), pause_before=pause, marks=marks)
            s.start = clock + pause
            s.end = s.start + s.letters / cps
            clock = s.end
            sentences.append(s)
        clock += float(sec.get("pause_after") or 0.0)
    return sentences


# -- features --------------------------------------------------------------------

def _number_runs(folded: str) -> list[re.Match]:
    return [m for m in NUMBER_RUN.finditer(folded)
            if any(w not in _AMBIGUOUS for w in m.group().split() if w != "و")]


def _at(s: Sentence, offset: int, cps: float) -> float:
    """Seconds at which the listener has heard s.spoken up to offset."""
    return round(s.start + _letters(s.spoken[:offset]) / cps, 2)


def analyse(s: Sentence, cps: float, names: list[str]) -> dict[str, Any]:
    folded = _fold(s.spoken)
    numbers = _number_runs(folded)
    you = YOU.search(folded)
    name_hits = [n for n in names if _words(n, suffix=True).search(folded)] + LATIN_NAME.findall(s.text)
    f = {
        "question": "؟" in s.text or "?" in s.text,
        "exclaim": "!" in s.text,
        "turn": bool(TURN.search(folded)),
        "therefore": len(THEREFORE.findall(folded)),
        "and_then": len(AND_THEN.findall(folded)),
        "you_at": _at(s, you.end(), cps) if you else None,
        "numbers": [m.group() for m in numbers],
        "number_at": _at(s, numbers[0].end(), cps) if numbers else None,
        "years": len(YEAR.findall(folded)),
        "names": sorted(set(name_hits)),
        "vague": [m.group() for m in VAGUE.finditer(folded)],
        "cta_subscribe": bool(CTA_SUBSCRIBE.search(folded)),
        "cta_comment": bool(CTA_COMMENT.search(folded)),
        "next_episode": bool(NEXT_EPISODE.search(folded)),
        "end_signal": bool(END_SIGNAL.search(folded)),
        "formal": [m.group() for m in FORMAL.finditer(folded)],
        "digits": bool(re.search(r"[0-9۰-۹٠-٩]", s.text)),
    }
    f["rehook"] = f["question"] or f["exclaim"] or f["turn"] or bool(numbers) or bool(you)
    return f


def _content_words(sentences: list[Sentence], skip: set[str] = frozenset()) -> set[str]:
    words = fa_text.canonical_words(" ".join(s.spoken for s in sentences))
    return {w for w in words if len(w) >= 3 and w not in STOPWORDS and w not in skip}


def _topic_words(sentences: list[Sentence]) -> set[str]:
    """Words in a quarter or more of the sentences (the company's name...):
    sharing them does not make an ending a callback."""
    counts: dict[str, int] = {}
    for s in sentences:
        for w in _content_words([s]):
            counts[w] = counts.get(w, 0) + 1
    return {w for w, n in counts.items() if n >= max(2, len(sentences) / 4)}


# -- checks ----------------------------------------------------------------------

def _finding(code: str, severity: str, fa: str, at: Optional[float] = None) -> dict[str, Any]:
    out = {"code": code, "severity": severity, "fa": fa}
    if at is not None:
        out["at_seconds"] = round(at, 1)
    return out


def check_hook(sentences: list[Sentence]) -> tuple[dict[str, Any], list[dict]]:
    times: dict[str, float] = {}
    for s in sentences:
        f = s.features
        for kind, t in (("you", f["you_at"]), ("number", f["number_at"]),
                        ("question", s.end if f["question"] else None),
                        ("paradox", s.end if f["turn"] else None)):
            if t is not None and kind not in times:
                times[kind] = round(t, 2)
    first = min(times.items(), key=lambda kv: kv[1]) if times else (None, None)
    report = {"first_hook_seconds": first[1], "first_hook_kind": first[0], "elements": times,
              "first_sentence": sentences[0].text if sentences else ""}
    findings = []
    if first[1] is None:
        findings.append(_finding("hook_missing", "high", "هیچ قلابی (سؤال، عدد، پارادوکس یا «تو») توی متن پیدا نشد."))
    elif first[1] > HOOK_FAIL:
        findings.append(_finding("hook_late", "high", f"اولین قلاب ثانیه‌ی {first[1]:.1f} می‌رسه؛ باید توی ۳ ثانیه‌ی اول باشه.", first[1]))
    elif first[1] > HOOK_WARN:
        findings.append(_finding("hook_late", "medium", f"اولین قلاب ثانیه‌ی {first[1]:.1f} می‌رسه؛ بهتره زیر ۳ ثانیه باشه.", first[1]))
    return report, findings


def collect_loops(script: dict[str, Any], sentences: list[Sentence],
                  llm_loops: Optional[list[dict]] = None) -> list[dict[str, Any]]:
    """Explicit loops (markers or metadata.loops), else the reviewed/draft LLM
    loops. Each: {id, question, opened_at, closed_at, source}."""
    loops: dict[str, dict[str, Any]] = {}
    for s in sentences:
        for kind, loop_id in s.marks:
            loop = loops.setdefault(loop_id, {"id": loop_id, "question": "", "opened_at": None,
                                              "closed_at": None, "source": "marker"})
            loop["opened_at" if kind == "open" else "closed_at"] = round(s.end, 2)
    by_section: dict[str, list[Sentence]] = {}
    for s in sentences:
        by_section.setdefault(s.section_id, []).append(s)
    for item in script.get("loops", []):
        opens, closes = by_section.get(item.get("opens")), by_section.get(item.get("closes") or "")
        loops[item.get("id", item.get("opens"))] = {
            "id": item.get("id", item.get("opens")), "question": item.get("question", ""),
            "opened_at": round(opens[0].end, 2) if opens else None,
            "closed_at": round(closes[-1].end, 2) if closes else None, "source": "metadata"}
    if not loops and llm_loops:
        for i, item in enumerate(llm_loops):
            o, c = item.get("opens"), item.get("closes")
            if not isinstance(o, int) or not 0 <= o < len(sentences):
                continue
            closed = sentences[c].end if isinstance(c, int) and 0 <= c < len(sentences) else None
            loops[f"llm{i + 1}"] = {"id": f"llm{i + 1}", "question": item.get("question", ""),
                                    "opened_at": round(sentences[o].end, 2),
                                    "closed_at": round(closed, 2) if closed is not None else None,
                                    "source": "llm_draft"}
    return [lp for lp in loops.values() if lp["opened_at"] is not None]


def check_loops(loops: list[dict[str, Any]], sentences: list[Sentence], ending: dict[str, Any],
                duration: float) -> tuple[dict[str, Any], list[dict]]:
    questions = [{"at": round(s.end, 1), "text": s.text} for s in sentences if s.features["question"]]
    events = sorted([(lp["opened_at"], 1) for lp in loops]
                    + [(lp["closed_at"], -1) for lp in loops if lp["closed_at"] is not None])
    open_now = max_open = 0
    for _, step in events:
        open_now += step
        max_open = max(max_open, open_now)
    unclosed = sorted((lp for lp in loops if lp["closed_at"] is None), key=lambda lp: lp["opened_at"])
    first_gap = min([lp["opened_at"] for lp in loops] + [q["at"] for q in questions]
                    + [s.end for s in sentences if s.features["turn"]], default=None)
    report = {"loops": loops, "opened": len(loops), "closed": len(loops) - len(unclosed),
              "max_open_at_once": max_open, "questions": questions, "first_gap_seconds": first_gap}
    findings = []
    if first_gap is None or first_gap > min(LOOP_BY, duration):
        sev = "high" if first_gap is None or first_gap > 30 else "medium"
        findings.append(_finding("loop_late", sev, "تا ثانیه‌ی ۱۰ هیچ خلأیی (سؤالی که بیننده بخواد جوابشو بدونه) باز نشده."))
    if max_open > MAX_OPEN_LOOPS:
        findings.append(_finding("loops_too_many", "medium", f"{max_open} خلأ هم‌زمان بازه؛ بیشتر از ۳ تا بیننده رو گیج می‌کنه."))
    # A next-episode ending may carry its last loop over as the cliffhanger.
    carried = 1 if ending["primary"] == "next_episode" and unclosed else 0
    for lp in unclosed[:len(unclosed) - carried]:
        findings.append(_finding("loop_unclosed", "medium", f"خلأ «{lp['question'] or lp['id']}» باز شد ولی آخرش بسته نشد.", lp["opened_at"]))
    for lp in loops:
        if lp["closed_at"] is not None and lp["closed_at"] - lp["opened_at"] < 3:
            findings.append(_finding("loop_too_short", "low", f"خلأ «{lp['question'] or lp['id']}» کمتر از ۳ ثانیه باز موند؛ تعلیقی نمی‌سازه.", lp["opened_at"]))
    return report, findings


def check_rehooks(sentences: list[Sentence], duration: float) -> tuple[dict[str, Any], list[dict]]:
    marks = [0.0] + [s.end for s in sentences if s.features["rehook"]] + [duration]
    gaps = [(round(b - a, 1), a, b) for a, b in zip(marks, marks[1:])]
    worst = max(gaps, default=(0.0, 0.0, 0.0))
    report = {"rehook_times": [round(t, 1) for t in marks[1:-1]], "max_gap_seconds": worst[0],
              "gaps_over_warn": [{"from": round(a, 1), "to": round(b, 1), "seconds": g}
                                 for g, a, b in gaps if g > REHOOK_WARN]}
    findings = []
    for g, a, b in gaps:
        if g > REHOOK_WARN:
            sev = "high" if g > REHOOK_FAIL else "medium"
            findings.append(_finding("rehook_gap", sev, f"از ثانیه‌ی {a:.0f} تا {b:.0f} ({g:.0f} ثانیه) هیچ «ولی»، سؤال، عدد یا چرخشی نیست.", a))
    return report, findings


def check_rhythm(sentences: list[Sentence]) -> tuple[dict[str, Any], list[dict]]:
    secs = [round(s.seconds, 2) for s in sentences]
    if not secs:
        return {}, []
    mean = statistics.mean(secs)
    cv = statistics.pstdev(secs) / mean if mean else 0.0
    runs, run = 0, 1
    for a, b in zip(secs, secs[1:]):
        run = run + 1 if abs(a - b) <= 0.2 * max(a, b) else 1
        if run == 3:
            runs += 1
    long_ones = [s for s in sentences if s.seconds > LONG_SENTENCE]
    abt = {"but": sum(1 for s in sentences if s.features["turn"]),
           "therefore": sum(s.features["therefore"] for s in sentences),
           "and_then": sum(s.features["and_then"] for s in sentences)}
    report = {"sentences": len(secs), "mean_seconds": round(mean, 2), "cv": round(cv, 2),
              "longest_seconds": max(secs), "punches": sum(1 for x in secs if x <= PUNCH_SENTENCE),
              "same_length_runs": runs, "but_therefore_and_then": abt}
    findings = []
    for s in long_ones:
        findings.append(_finding("sentence_long", "medium", f"جمله‌ی «{s.text[:40]}…» حدود {s.seconds:.0f} ثانیه‌ست؛ برای گوش زیادیه، بشکنش.", s.start))
    if len(secs) >= 6 and cv < MONOTONE_CV:
        findings.append(_finding("rhythm_flat", "medium", "طول جمله‌ها خیلی شبیه همه؛ چند جمله‌ی خیلی کوتاه بین جمله‌های بلند بذار."))
    if abt["and_then"] > abt["but"] + abt["therefore"]:
        findings.append(_finding("and_then", "low", "«و بعد» بیشتر از «ولی/برای همین» اومده؛ قصه شبیه فهرست می‌شه."))
    return report, findings


def check_specificity(sentences: list[Sentence], duration: float) -> tuple[dict[str, Any], list[dict]]:
    numbers = sum(len(s.features["numbers"]) for s in sentences)
    names = sorted({n for s in sentences for n in s.features["names"]})
    years = sum(s.features["years"] for s in sentences)
    vague = [v for s in sentences for v in s.features["vague"]]
    specifics = numbers + len(names)
    per10 = specifics / duration * 10 if duration else 0.0
    report = {"numbers": numbers, "years": years, "names": names, "vague": vague,
              "specifics_per_10s": round(per10, 2)}
    findings = []
    if duration >= 20 and per10 < SPECIFIC_PER_10S:
        findings.append(_finding("vague", "medium", f"جزئیات دقیق (عدد، سال، اسم) کمه: {per10:.1f} در هر ۱۰ ثانیه."))
    if len(vague) > specifics:
        findings.append(_finding("vague_words", "low", f"کلمه‌های مبهم ({'، '.join(vague[:4])}) بیشتر از عدد و اسم دقیقه."))
    return report, findings


def detect_ending(sentences: list[Sentence]) -> dict[str, Any]:
    if not sentences:
        return {"primary": "flat", "types": []}
    tail = sentences[-2:] if len(sentences) > 3 else sentences[-1:]
    last = tail[-1].features
    types = []
    topic = _topic_words(sentences)
    shared = (_content_words(sentences[:2], topic) & _content_words(tail, topic)
              if len(sentences) > 3 else set())
    if len(shared) >= 2:
        types.append("loop")
    if any(s.features["next_episode"] for s in tail):
        types.append("next_episode")
    if last["question"]:
        types.append("question")
    if last["turn"] or last["numbers"] or last["exclaim"]:
        types.append("twist")
    if any(s.features["cta_comment"] for s in tail):
        types.append("comment_cta")
    if any(s.features["cta_subscribe"] for s in tail):
        types.append("subscribe_cta")
    if any(s.features["end_signal"] for s in tail):
        types.append("summary")
    order = ["loop", "next_episode", "question", "twist", "comment_cta", "subscribe_cta", "summary"]
    primary = next((t for t in order if t in types), "flat")
    return {"primary": primary, "types": types, "shared_with_opening": sorted(shared),
            "last_sentence": tail[-1].text}


def check_ending(ending: dict[str, Any], sentences: list[Sentence], duration: float) -> list[dict]:
    findings = []
    if ending["primary"] == "flat":
        findings.append(_finding("ending_flat", "high", "پایان نه به شروع برمی‌گرده، نه سؤال یا چرخش داره؛ بیننده دلیلی برای موندن تا آخر نداره."))
    elif ending["primary"] in ("summary", "subscribe_cta"):
        findings.append(_finding("ending_weak", "medium", "پایان فقط جمع‌بندی یا درخواست سابسکرایبه؛ یه برگشت به هوک یا سرنخ قسمت بعد قوی‌تره."))
    # "Most replayed" curves of the reference videos fall to ~0 in the outro
    # (5 of 5, 2026-11-05): nothing said after the last story beat is heard.
    outro = 0.0
    for s in reversed(sentences):
        if not (s.features["cta_subscribe"] or s.features["cta_comment"]):
            break
        outro += s.end - s.start
    if outro > OUTRO_MAX:
        findings.append(_finding("outro_long", "medium", f"درخواست‌های آخر ویدیو {outro:.0f} ثانیه‌ست؛ بیننده‌ها همین‌جا می‌رن. زیر {OUTRO_MAX:.0f} ثانیه نگهش دار.",
                                 sentences[-1].start))
    for s in sentences:
        if s.features["end_signal"] and s.end < END_SIGNAL_BEFORE * duration:
            findings.append(_finding("end_signal_early", "medium", f"«{s.text[:30]}…» زودتر از آخر ویدیو بوی تموم شدن می‌ده؛ بیننده همین‌جا می‌ره.", s.start))
        if (s.features["cta_subscribe"] or s.features["cta_comment"]) and s.start < CTA_TOO_EARLY:
            findings.append(_finding("cta_early", "medium", "درخواست سابسکرایب/کامنت توی ۳۰ ثانیه‌ی اول؛ اول یه چیزی بده، بعد بخواه.", s.start))
    return findings


def check_text(script: dict[str, Any], sentences: list[Sentence], est: float,
               target: Optional[float]) -> tuple[dict[str, Any], list[dict]]:
    formal = [w for s in sentences for w in s.features["formal"]]
    digits = [s.text for s in sentences if s.features["digits"]]
    marker_in_tts = script["source"] == "json" and any(_MARKER.search(sec["spoken"]) for sec in script["sections"])
    report = {"estimated_seconds": round(est, 1), "target_seconds": target, "formal_words": formal,
              "digits_in_narration": len(digits)}
    findings = []
    if len(formal) >= 2:
        findings.append(_finding("register_mixed", "medium", f"کلمه‌های کتابی توی متن محاوره: {'، '.join(sorted(set(formal))[:5])}."))
    elif formal:
        findings.append(_finding("register_mixed", "low", f"یه کلمه‌ی کتابی: {formal[0]}."))
    if digits:
        findings.append(_finding("digits", "medium", "عدد با رقم توی متن صدا هست؛ برای TTS با حروف بنویس (رقم فقط برای زیرنویس)."))
    if marker_in_tts:
        findings.append(_finding("marker_in_tts", "high", "نشانه‌ی {{open/close}} توی متن صداست؛ TTS اینو می‌خونه. ببرش توی metadata.loops."))
    if target:
        over = est / target - 1
        if over > 0.15:
            findings.append(_finding("too_long", "high", f"متن حدود {est:.0f} ثانیه‌ست، هدف {target:.0f} ثانیه."))
        elif over > 0.05:
            findings.append(_finding("too_long", "medium", f"متن حدود {est:.0f} ثانیه‌ست، کمی بیشتر از {target:.0f} ثانیه."))
        elif over < -0.15:
            findings.append(_finding("too_short", "low", f"متن حدود {est:.0f} ثانیه‌ست، کمتر از {target:.0f} ثانیه."))
    by_id = {sec["id"]: sec for sec in script["sections"]}
    for sid in dict.fromkeys(s.section_id for s in sentences):
        sec = by_id[sid]
        if sec.get("start_seconds") is None or sec.get("end_seconds") is None:
            continue
        slot = sec["end_seconds"] - sec["start_seconds"]
        spoken = sum(s.seconds + s.pause_before for s in sentences if s.section_id == sid)
        if slot > 0 and spoken > slot * 1.1:
            findings.append(_finding("section_overflow", "medium", f"بخش {sid}: حرفش {spoken:.1f} ثانیه‌ست ولی جاش {slot:.1f} ثانیه.", sec["start_seconds"]))
    return report, findings


# -- LLM pass (worker tier, draft for the agent) -----------------------------------

LOOPS_TASK = "script_loop_review"
LOOPS_SCHEMA = {
    "type": "object", "required": ["loops"],
    "properties": {"loops": {"type": "array", "items": {
        "type": "object", "required": ["question", "opens"],
        "properties": {"question": {"type": "string"}, "opens": {"type": "integer"},
                       "closes": {"type": ["integer", "null"]}},
    }}},
}


def loops_prompt(sentences: list[Sentence]) -> str:
    numbered = "\n".join(f"[{s.index}] {s.text}" for s in sentences)
    return (
        "You review a Persian narration script for open loops: a question or gap the narration "
        "puts in the viewer's head that makes them keep watching (an unexplained fact, a teased "
        "event, a direct question). For each loop give the question in one short Persian line, "
        "the sentence index where it opens and the index where the script answers it, or null "
        "if it is never answered. Ignore rhetorical questions that are answered in the same "
        "sentence. Do not rewrite the script.\n"
        'Return JSON {"loops": [{"question": "...", "opens": 0, "closes": 4}]}\n\n' + numbered
    )


def llm_loops(llm, sentences: list[Sentence]) -> tuple[list[dict], float, Optional[str], Optional[str]]:
    """Worker-tier draft of open loops. Returns (loops, cost, model, error)."""
    r = llm.execute({"task": LOOPS_TASK, "prompt": loops_prompt(sentences), "json_schema": LOOPS_SCHEMA,
                     "temperature": 0})
    data = r.data or {}
    return (data.get("json") or {}).get("loops", []), r.cost_usd or 0.0, data.get("model"), \
        None if r.success else r.error


# -- report ----------------------------------------------------------------------

SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}


def lint(script: dict[str, Any], cps: float = DEFAULT_CPS, target: Optional[float] = None,
         names: Optional[list[str]] = None, llm=None) -> dict[str, Any]:
    sentences = split_sentences(script, cps)
    names = list(dict.fromkeys((names or []) + script.get("names", [])))
    for s in sentences:
        s.features = analyse(s, cps, names)
    est = sentences[-1].end if sentences else 0.0
    target = target or script.get("target_seconds")
    duration = max(est, 1.0)

    llm_part = None
    if llm is not None and sentences:
        drafted, cost, model, err = llm_loops(llm, sentences)
        llm_part = {"status": "draft_for_agent_review", "task": LOOPS_TASK, "model": model,
                    "loops": drafted, "cost_usd": round(cost, 6), "error": err}

    hook, f_hook = check_hook(sentences)
    ending = detect_ending(sentences)
    loops = collect_loops(script, sentences, llm_part["loops"] if llm_part else None)
    loop_report, f_loops = check_loops(loops, sentences, ending, duration)
    rehook, f_rehook = check_rehooks(sentences, duration)
    rhythm, f_rhythm = check_rhythm(sentences)
    spec, f_spec = check_specificity(sentences, duration)
    text, f_text = check_text(script, sentences, est, target)
    findings = sorted(f_hook + f_loops + f_rehook + f_rhythm + f_spec + check_ending(ending, sentences, duration)
                      + f_text, key=lambda f: (SEVERITY_ORDER[f["severity"]], f.get("at_seconds", 0)))
    risk = "high" if any(f["severity"] == "high" for f in findings) else \
        "medium" if any(f["severity"] == "medium" for f in findings) else "low"
    return {
        "title": script.get("title"), "cps": cps, "risk": risk,
        "hook": hook, "open_loops": loop_report, "rehooks": rehook, "rhythm": rhythm,
        "specificity": spec, "ending": ending, "text": text, "llm": llm_part,
        "findings": findings,
        "timeline": [{"i": s.index, "section": s.section_id, "start": round(s.start, 1), "end": round(s.end, 1),
                      "text": s.text, "rehook": s.features["rehook"]} for s in sentences],
    }


FA_RISK = {"high": "🔴 ریسک بالا", "medium": "🟡 ریسک متوسط", "low": "🟢 ریسک کم"}
FA_SEVERITY = {"high": "🔴", "medium": "🟡", "low": "⚪"}
FA_ENDING = {"loop": "برگشت به شروع (لوپ)", "next_episode": "سرنخ قسمت بعد", "question": "سؤال از بیننده",
             "twist": "چرخش آخر", "comment_cta": "دعوت به کامنت", "subscribe_cta": "درخواست سابسکرایب",
             "summary": "جمع‌بندی", "flat": "بی‌قلاب"}
FA_HOOK = {"you": "خطاب به «تو»", "number": "عدد", "question": "سؤال", "paradox": "پارادوکس/«ولی»"}


def persian_summary(report: dict[str, Any]) -> str:
    h, lp, rh, r, sp, e, t = (report[k] for k in ("hook", "open_loops", "rehooks", "rhythm", "specificity",
                                                   "ending", "text"))
    lines = [f"## بررسی متن روایت: {report['title']} — {FA_RISK[report['risk']]}", "",
             f"- سرعت فرض‌شده: {report['cps']} حرف در ثانیه؛ طول تخمینی: {t['estimated_seconds']} ثانیه"
             + (f" (هدف {t['target_seconds']:.0f})" if t.get("target_seconds") else "")]
    if h["first_hook_seconds"] is not None:
        lines.append(f"- اولین قلاب: ثانیه‌ی {h['first_hook_seconds']:.1f} ({FA_HOOK[h['first_hook_kind']]})")
    gap = lp["first_gap_seconds"]
    lines.append(f"- خلأها: {lp['opened']} باز، {lp['closed']} بسته، حداکثر هم‌زمان {lp['max_open_at_once']}؛ "
                 f"{len(lp['questions'])} سؤال؛ اولین خلأ: "
                 + (f"ثانیه‌ی {gap:.1f}" if gap is not None else "ندارد"))
    lines.append(f"- ری‌هوک: {len(rh['rehook_times'])} بار، بیشترین فاصله {rh['max_gap_seconds']:.1f} ثانیه")
    if r:
        lines.append(f"- ریتم: {r['sentences']} جمله، میانگین {r['mean_seconds']:.1f} ثانیه، بلندترین "
                     f"{r['longest_seconds']:.1f}، {r['punches']} جمله‌ی کوتاه ضربه‌ای، تنوع طول (CV) {r['cv']}")
    lines.append(f"- دقت: {sp['numbers']} عدد ({sp['years']} سال)، {len(sp['names'])} اسم، "
                 f"{len(sp['vague'])} کلمه‌ی مبهم؛ {sp['specifics_per_10s']} جزئیات دقیق در هر ۱۰ ثانیه")
    lines.append(f"- پایان: {FA_ENDING[e['primary']]}"
                 + (f" (کلمه‌های مشترک با شروع: {'، '.join(e['shared_with_opening'][:4])})"
                    if e.get("shared_with_opening") else ""))
    if report.get("llm"):
        llm = report["llm"]
        lines.append(f"- پیش‌نویس خلأها با مدل ارزان ({llm.get('model') or '—'}، ${llm['cost_usd']:.4f}): "
                     f"{len(llm['loops'])} مورد — باید بازبینی بشه، تصمیم نیست"
                     + (f"؛ خطا: {llm['error']}" if llm.get("error") else ""))
    lines += ["", "### نکته‌ها" if report["findings"] else "### نکته‌ای پیدا نشد"]
    for f in report["findings"]:
        at = f" (ثانیه‌ی {f['at_seconds']:.0f})" if "at_seconds" in f else ""
        lines.append(f"- {FA_SEVERITY[f['severity']]} {f['fa']}{at}")
    return "\n".join(lines)
