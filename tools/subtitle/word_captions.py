"""Word-by-word RTL captions timed to the narration.

Caption text comes from the script (the words we want on screen, with
digits and our spelling); timing comes from whisper-1 word timestamps
(`avalai_stt` with `word_timestamps: true`). The two never match exactly
— the transcript writes «رحیث» for «رئیس», «1995» for «۱۹۹۵», drops the ZWNJ
in «می‌دونستی» — so script words are aligned to transcript words by fuzzy
similarity (dynamic programming, order kept). Unmatched script words share
the time between their neighbours by letter count.

Whisper's word edges are loose (the first word starts at 0.00 although the
voice starts at 0.19; «آتیش» comes 130 ms early), so every word is clamped
into the speech segments found by silencedetect, then its start moves to
the nearest attack in the audio (`audio_onsets`) when one is within 150 ms.

Markup in group text: `*ماهی خشک*` = key words (cobalt pill), `_آتیش زد!_` =
hot words (fire colour). Output HTML (one `.cg` per group):

    <div id="cg-2" class="cg" data-cs="4.11" data-ce="6.55"><span class="box">
      <span class="w" data-ws="4.14" data-we="4.48">فروش</span>
      <span class="em key" data-ws="4.48" data-we="5.6"><span class="w" ...>ماهی</span> ...</span>
    </span></div>

The composition's script reads `data-cs`/`data-ce` (group) and
`data-ws`/`data-we` (word) and builds the tweens, so retiming never touches
the JS. `data-start`/`data-end` are not used: HyperFrames treats them as clip
timing and its linter rejects them on plain elements.
"""

from __future__ import annotations

import html
import json
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Optional, Sequence

from tools.base_tool import (
    BaseTool,
    Determinism,
    ExecutionMode,
    ResourceProfile,
    ToolResult,
    ToolStability,
    ToolTier,
)

RLM = "‏"
DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
FOLD = str.maketrans({"ي": "ی", "ى": "ی", "ك": "ک", "ة": "ه", "أ": "ا", "إ": "ا", "ٱ": "ا",
                      "ؤ": "و", "ئ": "ی", "ء": None})
STRIP = re.compile(r"[ً-ٰٟـ‌‍‎‏،؛؟!?.,:;…«»\"'()\-–—]")
MARKERS = {"*": "key", "_": "hot"}


def normalize(word: str) -> str:
    return STRIP.sub("", word.translate(DIGITS).translate(FOLD))


def similarity(a: str, b: str) -> float:
    a, b = normalize(a), normalize(b)
    if not a or not b:
        return 0.0
    if a.isdigit() or b.isdigit():
        return 1.0 if a == b else 0.0
    return SequenceMatcher(None, a, b).ratio()


def parse_markup(text: str) -> list[dict[str, str]]:
    """Tokens with their style; punctuation after a closing marker stays outside it."""
    tokens, style = [], "plain"
    for raw in text.split():
        core, tail, token_style = "", "", None
        for ch in raw:
            if ch in MARKERS:
                style = MARKERS[ch] if style == "plain" else "plain"
                continue
            if token_style is None:
                token_style = style
            if style == token_style and not tail:
                core += ch
            else:
                tail += ch
        if core or tail:
            tokens.append({"text": core or tail, "tail": tail if core else "", "style": token_style or style})
    return tokens


def align(display: Sequence[str], spoken: Sequence[str], gap: float = 0.25) -> list[Optional[int]]:
    """For each display word, the index of its spoken word (or None)."""
    n, m = len(display), len(spoken)
    score = [[0.0] * (m + 1) for _ in range(n + 1)]
    move = [[""] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        score[i][0], move[i][0] = -gap * i, "up"
    for j in range(1, m + 1):
        score[0][j], move[0][j] = -gap * j, "left"
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            options = [(score[i - 1][j - 1] + similarity(display[i - 1], spoken[j - 1]) - 0.5, "diag"),
                       (score[i - 1][j] - gap, "up"), (score[i][j - 1] - gap, "left")]
            score[i][j], move[i][j] = max(options)
    out: list[Optional[int]] = [None] * n
    i, j = n, m
    while i > 0 and j > 0:
        step = move[i][j]
        if step == "diag":
            out[i - 1] = j - 1
            i, j = i - 1, j - 1
        elif step == "up":
            i -= 1
        else:
            j -= 1
    return out


def clamp_to_speech(start: float, end: float, speech: Sequence[Sequence[float]]) -> tuple[float, float]:
    if not speech:
        return start, end
    # A word belongs to the first segment that is not over yet; it cannot
    # start in the silence before it or run past its end.
    seg = next((s for s in speech if start < s[1]), speech[-1])
    start = min(max(start, seg[0]), seg[1] - 0.05)
    end = min(max(end, start + 0.05), max(seg[1], start + 0.05))
    return round(start, 3), round(end, 3)


def audio_onsets(path: Path, offset: float = 0.0, rise_db: float = 15.0, floor_db: float = -30.0) -> list[float]:
    """Word attacks: a jump of `rise_db` within 30 ms out of a dip below
    `floor_db`. Catches the 50-100 ms stops silencedetect cannot see
    (the gap before «آتیش» in the Samsung sample is 70 ms)."""
    import numpy as np

    from tools.audio.beat_detect import decode_mono

    x = decode_mono(path, rate=16000)
    hop = 160
    frames = len(x) // hop
    db = 20 * np.log10(np.sqrt(np.mean(x[: frames * hop].reshape(frames, hop) ** 2, axis=1)) + 1e-9)
    out, last = [], -1.0
    for i in range(3, frames):
        dip = db[i - 3:i].min()
        if dip < floor_db and db[i] - dip >= rise_db and i * 0.01 - last > 0.12:
            out.append(round(offset + i * 0.01, 3))
            last = i * 0.01
    return out


def snap_starts(spoken: list[dict], onsets: Sequence[float], window: float = 0.15) -> None:
    """Move each word start to the nearest attack within `window`, keeping order."""
    if not onsets:
        return
    for k, w in enumerate(spoken):
        near = min(onsets, key=lambda o: abs(o - w["start"]))
        lo = spoken[k - 1]["start"] + 0.05 if k else float("-inf")
        if abs(near - w["start"]) <= window and near > lo and near < w["end"]:
            w["start"] = near
            if k:
                spoken[k - 1]["end"] = min(spoken[k - 1]["end"], near)


def time_words(tokens: list[dict], words: Sequence[dict], offset: float = 0.0,
               speech: Sequence[Sequence[float]] = (), onsets: Sequence[float] = ()) -> list[dict]:
    """Give every display token a start/end on the timeline."""
    spoken = [{"word": w["word"], "start": float(w["start"]) + offset, "end": float(w["end"]) + offset}
              for w in words]
    for w in spoken:
        w["start"], w["end"] = clamp_to_speech(w["start"], w["end"], speech)
    snap_starts(spoken, onsets)
    match = align([t["text"] for t in tokens], [w["word"] for w in spoken])
    for tok, j in zip(tokens, match):
        if j is not None:
            tok["start"], tok["end"] = spoken[j]["start"], spoken[j]["end"]
    first = speech[0][0] if speech else (spoken[0]["start"] if spoken else offset)
    last = speech[-1][1] if speech else (spoken[-1]["end"] if spoken else offset)
    i = 0
    while i < len(tokens):
        if "start" in tokens[i]:
            i += 1
            continue
        k = i
        while k < len(tokens) and "start" not in tokens[k]:
            k += 1
        lo = tokens[i - 1]["end"] if i else first
        hi = tokens[k]["start"] if k < len(tokens) else last
        run = tokens[i:k]
        if hi - lo < 0.08 * len(run) and i:
            # No room between the neighbours: share the previous word's slot.
            i -= 1
            run = tokens[i:k]
            lo = tokens[i]["start"]
        letters = [max(1, len(normalize(t["text"]))) for t in run]
        t = lo
        for tok, n in zip(run, letters):
            tok["start"] = round(t, 3)
            t += (hi - lo) * n / sum(letters)
            tok["end"] = round(t, 3)
        i = k
    for a, b in zip(tokens, tokens[1:]):
        if a["end"] > b["start"]:
            a["end"] = b["start"]
    return tokens


def build_groups(groups: Sequence[dict], clips: dict[str, dict], duration: float, *, lead: float = 0.06,
                 hold: float = 0.3, bridge: float = 0.35, min_on: float = 0.8) -> list[dict]:
    """groups: [{text, clip}]; clips: {id: {start, words, speech}} with timeline speech."""
    out: list[dict] = []
    by_clip: dict[str, list[int]] = {}
    for gi, g in enumerate(groups):
        by_clip.setdefault(g["clip"], []).append(gi)
    timed: dict[int, list[dict]] = {}
    for cid, members in by_clip.items():
        clip = clips[cid]
        tokens = []
        for gi in members:
            for tok in parse_markup(groups[gi]["text"]):
                tok["group"] = gi
                tokens.append(tok)
        time_words(tokens, clip["words"], float(clip.get("start", 0)), clip.get("speech", ()),
                   clip.get("onsets", ()))
        for tok in tokens:
            timed.setdefault(tok.pop("group"), []).append(tok)
    for gi in range(len(groups)):
        words = timed[gi]
        start = max(0.0, words[0]["start"] - lead)
        if out:
            start = max(start, out[-1]["words"][-1]["end"])
        out.append({"id": f"cg-{gi}", "start": round(start, 3), "end": round(words[-1]["end"] + hold, 3),
                    "words": words, "text": groups[gi]["text"]})
    for a, b in zip(out, out[1:]):
        if b["start"] - a["end"] < bridge:
            a["end"] = b["start"]
        elif a["end"] - a["start"] < min_on:
            a["end"] = round(min(b["start"], a["start"] + min_on), 3)
    if out:
        last = out[-1]
        last["end"] = round(min(duration, max(last["end"], last["start"] + min_on)), 3)
    return out


def _word(tok: dict) -> str:
    return f'<span class="w" data-ws="{tok["start"]:g}" data-we="{tok["end"]:g}">{html.escape(tok["text"])}</span>'


def render_html(groups: Sequence[dict]) -> str:
    lines = []
    for g in groups:
        parts, k, words = [], 0, g["words"]
        while k < len(words):
            style = words[k]["style"]
            if style == "plain":
                parts.append(_word(words[k]) + html.escape(words[k]["tail"]))
                k += 1
                continue
            run = [words[k]]
            while k + len(run) < len(words) and words[k + len(run)]["style"] == style and not run[-1]["tail"]:
                run.append(words[k + len(run)])
            parts.append(f'<span class="em {style}" data-ws="{run[0]["start"]:g}" data-we="{run[-1]["end"]:g}">'
                         # Trailing punctuation rides inside the pill: outside, the pill's
                         # padding pushed «،» away from «۱۹۹۵».
                         + " ".join(_word(t) for t in run) + html.escape(run[-1]["tail"]) + "</span>")
            k += len(run)
        lines.append(f'<div id="{g["id"]}" class="cg" data-cs="{g["start"]:g}" data-ce="{g["end"]:g}">'
                     f'<span class="box">{" ".join(parts)}</span></div>')
    return "\n".join(lines)


def caption_cues(groups: Sequence[dict]) -> list[dict]:
    """The render QA's caption format: [{start, end, lines}] with RLM-marked lines."""
    return [{"start": g["start"], "end": g["end"],
             "lines": [RLM + " ".join(w["text"] + w["tail"] for w in g["words"])]} for g in groups]


class WordCaptions(BaseTool):
    name = "word_captions"
    version = "0.1.0"
    tier = ToolTier.CORE
    capability = "subtitle"
    provider = "openmontage"
    stability = ToolStability.EXPERIMENTAL
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.DETERMINISTIC

    dependencies = []
    install_instructions = "No install. Word timestamps: avalai_stt with word_timestamps (paid, cents)."
    agent_skills = ["hyperframes-media"]
    capabilities = ["word_level_captions", "caption_alignment"]
    best_for = [
        "word-by-word highlighted Persian captions timed to TTS narration",
        "aligning script text (digits, our spelling) to a noisy transcript",
    ]
    input_schema = {
        "type": "object",
        "required": ["groups", "clips", "duration"],
        "properties": {
            "groups": {"type": "array", "description": "[{text, clip}] in order; *key* and _hot_ markup"},
            "clips": {"type": "object",
                      "description": "{id: {start, words_path | words, speech: [[a, b]] (timeline), "
                                     "audio_path (for word attacks)}}"},
            "duration": {"type": "number"},
            "output_path": {"type": "string", "description": "JSON with groups, html and QA cues"},
        },
    }
    resource_profile = ResourceProfile(cpu_cores=1, ram_mb=128, vram_mb=0, disk_mb=5)
    side_effects = ["writes a caption JSON when output_path is given"]

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        try:
            clips = {}
            for cid, clip in inputs["clips"].items():
                words = clip.get("words")
                if words is None:
                    body = json.loads(Path(clip["words_path"]).read_text(encoding="utf-8"))
                    words = body.get("words", body) if isinstance(body, dict) else body
                clips[cid] = {**clip, "words": words}
                if clip.get("audio_path") and "onsets" not in clip:
                    clips[cid]["onsets"] = audio_onsets(Path(clip["audio_path"]), float(clip.get("start", 0)))
            groups = build_groups(inputs["groups"], clips, float(inputs["duration"]))
            data = {"groups": groups, "html": render_html(groups), "cues": caption_cues(groups)}
            if inputs.get("output_path"):
                out = Path(inputs["output_path"])
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            return ToolResult(success=True, data=data,
                              artifacts=[inputs["output_path"]] if inputs.get("output_path") else [])
        except (KeyError, IndexError, ValueError, FileNotFoundError) as exc:
            return ToolResult(success=False, error=f"{type(exc).__name__}: {exc}")
