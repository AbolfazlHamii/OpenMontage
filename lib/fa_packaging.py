"""Packaging for the Persian channel: title drafts, title and topic rubrics,
description, chapters and tags.

Title drafts come from the worker tier (llm_selector task
`title_tag_variants`); they are raw material. The agent picks, rewrites and
signs off every Persian line that reaches viewers. The rubrics below check
what can be checked mechanically (length, where the subject sits, spelling,
bidi, clickbait words); they do not judge taste.

Rules and evidence: skills/creative/youtube-packaging.md.
"""

from __future__ import annotations

import json
import re
from typing import Any, Optional

TITLE_MAX = 100          # YouTube's limit
TITLE_RANGE = (20, 60)   # what we aim for; short is fine, phones cut long ones
FRONT_CHARS = 40         # what survives truncation on a phone
TAGS_MAX_CHARS = 500     # YouTube's limit for the tags field
HASHTAGS_SHOWN = 3       # shown above the title

CHAPTER_MIN_SECONDS = 10
CHAPTER_MIN_COUNT = 3

ZWNJ = "‌"
_ARABIC_LETTERS = re.compile(r"[يكى]")
_LATIN_WORD = re.compile(r"[A-Za-z][A-Za-z0-9'.-]*")
_ANY_DIGIT = re.compile(r"[0-9۰-۹٠-٩]")
_LATIN_DIGIT = re.compile(r"[0-9]")
_PERSIAN_LETTER = re.compile(r"[؀-ۿ]")
_SPACED_MI = re.compile(r"(?:^|\s)(ن?می) (?=\S)")
_SPACED_HA = re.compile(r"\S (ها|های|هایی)(?=\s|$|[!؟?.،])")
_TIME_BOX = re.compile(r"در\s+\S+\s+(ثانیه|دقیقه|ساعت)")
_CONTRAST = re.compile(r"(^|\s)از\s.+\sتا\s|(^|\s)(ولی|اما)(\s|$)")

CLICKBAIT = ["باورنکردنی", "باور نکردنی", "شوکه", "حتما ببینید", "حتماً ببینید", "فوری",
             "جنجالی", "وحشتناک", "هرگز ندیده", "۱۰۰٪ واقعی", "افشاگری"]

_TO_FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
_TO_LATIN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "0123456789" * 2)


# ---- titles ---------------------------------------------------------------

TITLE_SCHEMA = {
    "type": "object",
    "properties": {
        "titles": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "pattern": {"type": "string"},
                    "why": {"type": "string"},
                },
                "required": ["title"],
            },
        },
        "tags": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["titles"],
}

PATTERNS = {
    "time_box": "the whole story in a fixed time («کل تاریخ X در ۹۰ ثانیه»)",
    "origin_twist": "the surprising origin («X با ماهی خشک شروع شد»)",
    "event": "one dramatic event («روزی که X ... کرد»)",
    "how_question": "a how/why question people search («X چطور ... شد؟»)",
    "then_now": "two eras («از ماهی خشک تا گلکسی»)",
}


def title_prompt(brief: dict[str, Any]) -> str:
    """Prompt for the worker tier. The brief: topic, keyword, facts, hook,
    register, count, optional working_title and avoid list."""
    count = int(brief.get("count", 15))
    facts = "\n".join(f"- {f}" for f in brief.get("facts", []))
    patterns = "\n".join(f"- {name}: {desc}" for name, desc in PATTERNS.items())
    avoid = ", ".join(brief.get("avoid", [])) or "none"
    register = brief.get("register", "spoken Tehrani Persian for verbs, standard spelling for the keyword")
    return f"""Write {count} YouTube title options in Persian for a short cartoon history video.

Topic: {brief.get("topic", "")}
Search keyword that must appear in every title, early: {brief.get("keyword", "")}
Working title: {brief.get("working_title", "-")}
Hook of the video (said in its first seconds): {brief.get("hook", "-")}
Facts the video really contains (titles may only promise these):
{facts or "-"}

Patterns to cover (at least two titles per pattern):
{patterns}

Rules:
- 20 to 60 characters; never over 100.
- Register: {register}.
- Persian digits (۹۰ not 90); Persian letters ی and ک, never ي or ك; half-space (ZWNJ) where standard.
- No Latin word at the start or end of a title.
- No clickbait words (باورنکردنی، شوکه‌کننده، حتماً ببینید), no «!!» or «؟؟».
- Never promise something the facts above do not support.
- Avoid: {avoid}.

Also return 10 search tags (Persian and Latin spellings, common misspellings).
Answer as JSON: {{"titles": [{{"title": "...", "pattern": "<pattern name>", "why": "<short reason>"}}], "tags": ["..."]}}"""


def draft_titles(brief: dict[str, Any], selector: Any = None,
                 cost_log_path: Optional[str] = None) -> dict[str, Any]:
    """Send the brief to the worker tier and score every draft."""
    if selector is None:
        from tools.text.llm_selector import LLMSelector
        selector = LLMSelector()
    # Persian costs many tokens: 15 titles + tags overflow the router's default 2048
    # and come back as cut-off JSON.
    inputs: dict[str, Any] = {"task": "title_tag_variants", "prompt": title_prompt(brief),
                              "json_schema": TITLE_SCHEMA, "temperature": 0.9, "max_tokens": 6000}
    if cost_log_path:
        inputs["cost_log_path"] = cost_log_path
    result = selector.execute(inputs)
    data = result.data or {}
    answer = data.get("json")
    if answer is None and data.get("text"):
        answer = _loose_json(data["text"])
    drafts = (answer or {}).get("titles", []) if result.success else []
    keyword = brief.get("keyword", "")
    aliases = brief.get("aliases", [])
    scored = [{**d, **score_title(d.get("title", ""), keyword, aliases)} for d in drafts
              if isinstance(d, dict) and d.get("title")]
    scored.sort(key=lambda d: d["score"], reverse=True)
    return {
        "success": result.success,
        "error": result.error,
        "model": data.get("model"),
        "tier": data.get("tier"),
        "cost_usd": result.cost_usd,
        "fallback_from": data.get("fallback_from", []),
        "attempts": data.get("attempts", []),
        "drafts": scored,
        "tags": (answer or {}).get("tags", []),
        "note": "Drafts from a cheap model: the agent picks, rewrites and signs off the final titles.",
    }


def _loose_json(text: str) -> Optional[dict[str, Any]]:
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def score_title(title: str, keyword: str = "", aliases: Optional[list[str]] = None) -> dict[str, Any]:
    """Mechanical rubric, 100 points: length 20, subject early 20, hook device 20,
    spelling 20, no clickbait 10, bidi 10."""
    title = title.strip()
    notes: list[str] = []
    parts: dict[str, int] = {}
    n = len(title)

    lo, hi = TITLE_RANGE
    if n > TITLE_MAX:
        parts["length"] = 0
        notes.append(f"{n} characters: over YouTube's {TITLE_MAX}")
    elif lo <= n <= hi:
        parts["length"] = 20
    elif hi < n <= 70 or 12 <= n < lo:
        parts["length"] = 12
        notes.append(f"{n} characters (aim for {lo}-{hi})")
    else:
        parts["length"] = 5
        notes.append(f"{n} characters (aim for {lo}-{hi})")

    names = [k for k in [keyword, *(aliases or [])] if k]
    positions = [title.find(k) for k in names if k in title]
    if not names:
        parts["subject"] = 10
    elif positions and min(positions) < FRONT_CHARS:
        parts["subject"] = 20
    elif positions:
        parts["subject"] = 10
        notes.append(f"the subject comes after character {FRONT_CHARS}; phones may cut it")
    else:
        parts["subject"] = 0
        notes.append(f"the subject ({keyword}) is missing")

    devices = [name for name, hit in (
        ("number", bool(_ANY_DIGIT.search(title))),
        ("question", "؟" in title or "?" in title),
        ("contrast", bool(_CONTRAST.search(title))),
        ("time_box", bool(_TIME_BOX.search(title))),
    ) if hit]
    parts["hook"] = 20 if devices else 8
    if not devices:
        notes.append("no number, question, contrast or time box; is the curiosity in the thumbnail?")

    spelling = 20
    if _ARABIC_LETTERS.search(title):
        spelling -= 10
        notes.append("Arabic ي/ك/ى; use Persian ی/ک")
    if _SPACED_MI.search(title):
        spelling -= 5
        notes.append("«می» written with a space; use a half-space («می‌»)")
    if _SPACED_HA.search(title):
        spelling -= 5
        notes.append("plural «ها» written with a space; use a half-space")
    if _LATIN_DIGIT.search(title) and _PERSIAN_LETTER.search(title):
        spelling -= 5
        notes.append("Latin digits in a Persian title; use Persian digits")
    if "  " in title:
        spelling -= 5
        notes.append("double space")
    parts["spelling"] = max(spelling, 0)

    bait = [w for w in CLICKBAIT if w in title]
    shouting = re.search(r"[!！]{2,}|[؟?]{2,}", title) or re.search(r"\b[A-Z]{4,}\b", title)
    parts["clickbait"] = max(10 - 5 * len(bait) - (5 if shouting else 0), 0)
    if bait:
        notes.append("clickbait words: " + "، ".join(bait))
    if shouting:
        notes.append("repeated !/؟ or shouting capitals")

    latin = list(_LATIN_WORD.finditer(title))
    edge = latin and _PERSIAN_LETTER.search(title) and (
        latin[0].start() == 0 or latin[-1].end() >= len(title.rstrip("!؟?. ")))
    parts["bidi"] = 0 if edge else 10
    if edge:
        notes.append("Latin word at the start or end: punctuation will jump sides in RTL")

    return {"title": title, "score": sum(parts.values()), "chars": n,
            "devices": devices, "parts": parts, "notes": notes}


# ---- topics ---------------------------------------------------------------

TOPIC_WEIGHTS = {
    "demand": 25,       # people search/watch this in Persian
    "twist": 20,        # one-sentence surprise
    "familiarity": 15,  # Persian viewers own/use/remember it
    "visual": 15,       # thumbnail in 3 words + 1 image; distinct eras
    "series_fit": 10,   # pairs with another episode
    "evergreen": 10,    # still searched in two years
    "cost": 5,          # 5 = few distinct scenes, cheap
}
RISK_PENALTY = 6        # per risk point (0-5): politics, religion, sanctions, defamation
VERDICTS = ((70, "make it"), (55, "owner's call"), (0, "drop or find a better angle"))


def score_topic(topic: dict[str, Any]) -> dict[str, Any]:
    """Each criterion is the agent's 1-5 judgement (with evidence in `why`)."""
    breakdown = {}
    for name, weight in TOPIC_WEIGHTS.items():
        value = float(topic.get(name, 0))
        if not 0 <= value <= 5:
            raise ValueError(f"{topic.get('name', '?')}: {name} must be 0-5, got {value}")
        breakdown[name] = round(value / 5 * weight, 1)
    risk = float(topic.get("risk", 0))
    if not 0 <= risk <= 5:
        raise ValueError(f"{topic.get('name', '?')}: risk must be 0-5, got {risk}")
    total = round(sum(breakdown.values()) - risk * RISK_PENALTY, 1)
    verdict = next(label for floor, label in VERDICTS if total >= floor)
    return {**topic, "score": total, "breakdown": breakdown,
            "risk_penalty": round(risk * RISK_PENALTY, 1), "verdict": verdict}


def rank_topics(topics: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ranked = sorted((score_topic(t) for t in topics), key=lambda t: t["score"], reverse=True)
    for i, t in enumerate(ranked, 1):
        t["rank"] = i
    return ranked


# ---- chapters, description, tags -------------------------------------------

def timestamp(seconds: float) -> str:
    seconds = int(round(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def build_chapters(sections: list[dict[str, Any]], min_seconds: float = CHAPTER_MIN_SECONDS
                   ) -> tuple[list[dict[str, Any]], list[str]]:
    """Chapters from script sections (or scenes): `start_seconds`, `end_seconds`
    and `chapter` / `label` / `title`. Sections shorter than min_seconds are
    merged into the chapter before them. Returns ([], notes) when YouTube would
    not show the result (fewer than 3 chapters)."""
    notes: list[str] = []
    items = sorted((s for s in sections if "start_seconds" in s), key=lambda s: s["start_seconds"])
    chapters: list[dict[str, Any]] = []
    for s in items:
        title = (s.get("chapter") or s.get("label") or s.get("title") or "").strip()
        start = float(s["start_seconds"])
        end = float(s.get("end_seconds", start))
        if chapters and (not title or title == chapters[-1]["title"]):
            chapters[-1]["end_seconds"] = max(chapters[-1]["end_seconds"], end)
            continue
        chapters.append({"start_seconds": start, "end_seconds": end, "title": title})
    if chapters:
        chapters[0]["start_seconds"] = 0.0

    merged: list[dict[str, Any]] = []
    for ch in chapters:
        if merged and ch["end_seconds"] - ch["start_seconds"] < min_seconds:
            merged[-1]["end_seconds"] = ch["end_seconds"]
            notes.append(f"merged «{ch['title']}» ({ch['end_seconds'] - ch['start_seconds']:.0f} s) "
                         f"into «{merged[-1]['title']}»")
            continue
        merged.append(dict(ch))
    if len(merged) > 1 and merged[0]["end_seconds"] - merged[0]["start_seconds"] < min_seconds:
        merged[1]["start_seconds"] = 0.0
        notes.append(f"merged «{merged[0]['title']}» into the next chapter")
        merged.pop(0)

    untitled = [i for i, ch in enumerate(merged) if not ch["title"]]
    if untitled:
        notes.append(f"chapters {untitled} have no title; give the sections a `chapter` label")
    if len(merged) < CHAPTER_MIN_COUNT:
        notes.append(f"only {len(merged)} chapters of ≥{min_seconds:.0f} s; YouTube needs "
                     f"{CHAPTER_MIN_COUNT}, so no chapters are written")
        return [], notes
    return [{"start_seconds": ch["start_seconds"], "title": ch["title"]} for ch in merged], notes


def chapter_lines(chapters: list[dict[str, Any]]) -> list[str]:
    return [f"{timestamp(ch['start_seconds'])} {ch['title']}" for ch in chapters]


def spelling_variants(term: str) -> list[str]:
    """Spellings people type: Arabic letters, a space for the half-space, no space."""
    out = [term]
    out.append(term.replace("ی", "ي").replace("ک", "ك"))
    if ZWNJ in term:
        out.append(term.replace(ZWNJ, " "))
        out.append(term.replace(ZWNJ, ""))
    out.append(term.translate(_TO_LATIN_DIGITS))
    seen, unique = set(), []
    for v in out:
        if v not in seen:
            seen.add(v)
            unique.append(v)
    return unique


def build_tags(keyword: str, aliases: Optional[list[str]] = None, extra: Optional[list[str]] = None,
               series: str = "", limit: int = TAGS_MAX_CHARS) -> list[str]:
    """Keyword phrases first, then spelling variants (what tags are for), then
    the rest, cut to YouTube's 500-character field (tags joined with commas)."""
    phrases = [keyword, f"تاریخچه {keyword}", f"داستان {keyword}", f"داستان موفقیت {keyword}"]
    phrases += list(aliases or [])
    if aliases:
        phrases += [f"{aliases[0]} history"]
    if series:
        phrases.append(series)
    phrases += list(extra or [])
    candidates: list[str] = []
    for p in phrases:
        candidates += spelling_variants(p) if _PERSIAN_LETTER.search(p) else [p]
    tags: list[str] = []
    used = 0
    seen = set()
    for tag in candidates:
        tag = re.sub(r"\s+", " ", tag.replace(",", " ")).strip()
        if not tag or tag.lower() in seen:
            continue
        cost = len(tag) + (1 if tags else 0)
        if used + cost > limit:
            continue
        seen.add(tag.lower())
        tags.append(tag)
        used += cost
    return tags


def hashtag(text: str) -> str:
    return "#" + re.sub(r"[\s‌]+", "_", text.strip().lstrip("#"))


def build_description(hook: str, summary: str, chapters: list[dict[str, Any]],
                      sources: Optional[list[dict[str, str]]] = None, music: str = "",
                      series_line: str = "", hashtags: Optional[list[str]] = None,
                      cta: str = "") -> str:
    """Assemble the description. Every Persian line (hook, summary, chapter
    titles, CTA) is the agent's reviewed text; this only lays it out."""
    blocks = [f"{hook.strip()}\n{summary.strip()}".strip()]
    if chapters:
        blocks.append("فصل‌ها:\n" + "\n".join(chapter_lines(chapters)))
    if sources:
        lines = [f"- {s.get('title', '').strip()}: {s['url']}" if s.get("title") else f"- {s['url']}"
                 for s in sources if s.get("url")]
        blocks.append("منابع:\n" + "\n".join(lines))
    if series_line:
        blocks.append(series_line.strip())
    if music:
        blocks.append(f"موسیقی: {music.strip()}")
    if cta:
        blocks.append(cta.strip())
    tags = [hashtag(h) for h in (hashtags or [])][:HASHTAGS_SHOWN]
    if tags:
        blocks.append(" ".join(tags))
    return "\n\n".join(b for b in blocks if b) + "\n"


def description_report(description: str, keyword: str) -> dict[str, Any]:
    """Checks on the assembled description."""
    first_two = "\n".join(description.strip().splitlines()[:2])
    problems = []
    if keyword and keyword not in first_two:
        problems.append(f"keyword «{keyword}» is not in the first two lines (shown in search)")
    if len(description) > 5000:
        problems.append(f"{len(description)} characters: YouTube allows 5000")
    if len(re.findall(r"(?:^|\s)#\S+", description)) > 60:
        problems.append("more than 60 hashtags: YouTube ignores all of them")
    if "<" in description or ">" in description:
        problems.append("angle brackets are not allowed in YouTube descriptions")
    return {"chars": len(description), "problems": problems}
