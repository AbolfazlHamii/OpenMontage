"""Persian dub of an existing video: stems, speakers, lines, timing, mix, QA.

Everything lives under <project>/dub/:

    meta.json             source, language, channel, rights
    stems/                vocals.wav, accompaniment.wav (stem_separator)
    segments_en.json      speaker turns: Gemini tells the voices apart, whisper
                          word times place them (AvalAI cannot diarize)
    voice_map.json        source speaker -> Gemini voice, fixed for the video
    segments_fa.json      Persian lines: draft from the worker tier, then
                          reviewed ("review": "approved") before synthesis
    clips/, fits.json     synthesized (or recorded) lines and how they fit
    vo/<speaker>/         recording script + English reference clips
    mix/                  placed lines and the dub mix
    qa.json               overlap, round-trip, loudness, rights

Stages are separate functions (and `scripts/fa_dub.py` subcommands) because
the owner approves the Persian lines between translate and synth. Tools are
passed in so tests run without network or Demucs.
"""

from __future__ import annotations

import base64
import datetime
import difflib
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Callable, Optional

from lib.dub_timing import Fit, Segment, char_budget, fit_all, overlaps
from lib.fa_text import round_trip

DEFAULT_CPS = 9.5
RIGHTS = ("own", "permission_granted", "unknown")
MERGE_GAP = 0.35      # same-speaker turns closer than this become one line
MAX_LINE_SECONDS = 12.0
ROUND_TRIP_FLOOR = 0.90
# gpt-4o-mini-transcribe read two short Persian clips as Kurdish/Turkish
# (scores 0.36 and 0.47; gpt-4o-transcribe heard one of them right).
QA_STT_MODEL = "gpt-4o-transcribe"
# loudnorm lands on -1 dBTP before the AAC encode, which pushed peaks back
# to -0.7; aim lower so the encoded file stays under -1.
RENDER_TRUE_PEAK = -1.5
CLIP_GAIN_LIMIT_DB = 12.0
TURNS_MODEL = "gemini-3.8-flash"
TRANSLATE_CHUNK = 6
# Gemini prebuilt voices by gender (Gemini TTS voice list), so a dubbed
# speaker keeps the source speaker's gender.
VOICE_GENDER = {
    **dict.fromkeys(["Zephyr", "Kore", "Leda", "Aoede", "Callirrhoe", "Autonoe", "Despina",
                     "Erinome", "Laomedeia", "Achernar", "Gacrux", "Pulcherrima",
                     "Vindemiatrix", "Sulafat"], "female"),
    **dict.fromkeys(["Puck", "Charon", "Fenrir", "Orus", "Enceladus", "Iapetus", "Umbriel",
                     "Algieba", "Algenib", "Rasalgethi", "Alnilam", "Schedar", "Achird",
                     "Zubenelgenubi", "Sadachbia", "Sadaltager"], "male"),
}
AUDIO_TOKENS_PER_SECOND = 32

ENERGY_FA = {"low": "آرام و نرم", "medium": "طبیعی و گرم", "high": "پرانرژی"}
EMOTION_FA = {
    "excited": "هیجان‌زده", "calm": "آرام", "curious": "کنجکاو", "amused": "سرگرم",
    "laughing": "با خنده", "skeptical": "با تردید", "tense": "پرتنش", "sad": "غمگین",
    "angry": "عصبانی", "ironic": "کنایه‌آمیز", "warm": "گرم", "worried": "نگران",
    "playful": "بازیگوش", "joking": "شوخ", "alarmed": "جاخورده", "cheerful": "سرحال",
    "reassuring": "دلگرم‌کننده", "dramatic": "نمایشی", "proud": "با افتخار",
    "teasing": "سربه‌سر گذار", "enthusiastic": "مشتاق", "firm": "محکم",
    "surprised": "متعجب", "engaging": "گیرا", "engaged": "درگیر ماجرا",
    "anticipatory": "منتظر و مشتاق", "informative": "توضیح‌دهنده", "satisfied": "راضی",
    "friendly": "صمیمی",
}

TRANSLATE_SCHEMA = {
    "type": "object",
    "required": ["lines"],
    "properties": {"lines": {"type": "array", "items": {
        "type": "object", "required": ["id", "fa"],
        "properties": {"id": {"type": "string"}, "fa": {"type": "string"}},
    }}},
}


# -- files -------------------------------------------------------------------

def dub_dir(project: Path) -> Path:
    return Path(project) / "dub"


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, data: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_segments(project: Path, name: str = "segments_fa.json") -> list[dict]:
    return _read(dub_dir(project) / name)


def to_segment(row: dict) -> Segment:
    return Segment(id=row["id"], start=float(row["start"]), end=float(row["end"]),
                   text=row.get("text", ""), speaker=row.get("speaker", "speaker_1"),
                   source_text=row.get("source_text", ""), style=row.get("style", ""))


# -- prepare -----------------------------------------------------------------

def merge_turns(raw: list[dict], gap: float = MERGE_GAP, max_len: float = MAX_LINE_SECONDS) -> list[dict]:
    """Diarized chunks -> lines: join same-speaker chunks with a short gap."""
    lines: list[dict] = []
    for seg in sorted(raw, key=lambda s: s["start"]):
        text = seg["text"].strip()
        if not text:
            continue
        last = lines[-1] if lines else None
        if (last and last["speaker"] == seg["speaker"] and seg["start"] - last["end"] <= gap
                and seg["end"] - last["start"] <= max_len):
            last["end"] = seg["end"]
            last["text"] = f"{last['text']} {text}"
            continue
        lines.append({"speaker": seg["speaker"], "start": round(seg["start"], 3),
                      "end": round(seg["end"], 3), "text": text})
    for i, line in enumerate(lines, 1):
        line["id"] = f"s{i:03d}"
        line["end"] = round(line["end"], 3)
    return lines


def _speech_wav(src: Path, dst: Path, run: Callable[[list[str]], Any]) -> Path:
    """16 kHz mono copy for transcription (keeps uploads under 25 MB)."""
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(src),
         "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(dst)])
    return dst


def _run(cmd: list[str]) -> None:
    import subprocess

    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise RuntimeError(f"{cmd[0]} failed: {proc.stderr[-400:]}")


TURNS_PROMPT = """Transcribe this conversation verbatim as speaker turns, in order.
Tell the speakers apart by their voices and label them A, B, C... in order of
first appearance; the same voice always gets the same label. Start a new turn
whenever the speaker changes, even for one word. Write numbers as spoken.
Also say whether each voice sounds female or male.
Return JSON only:
{"speakers": {"A": "female", "B": "male"}, "turns": [{"speaker": "A", "text": "..."}]}"""


def gemini_turns(audio_path: Path, seconds: float, post: Optional[Callable] = None) -> tuple[dict, float]:
    """Speaker turns (who said what) and each speaker's gender, from Gemini
    listening to the audio through AvalAI's native endpoint.
    Returns ({"turns": [...], "speakers": {...}}, cost)."""
    from tools.analysis.gemini_video_analyze import GeminiVideoAnalyze

    if post is None:
        import requests

        post = requests.post
    key = os.environ.get("AVALAI_API_KEY")
    if not key:
        raise ValueError("speaker labels need AVALAI_API_KEY")
    body = {
        "contents": [{"role": "user", "parts": [
            {"inlineData": {"mimeType": "audio/wav",
                            "data": base64.b64encode(Path(audio_path).read_bytes()).decode()}},
            {"text": TURNS_PROMPT},
        ]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0},
    }
    base_url = os.environ.get("AVALAI_BASE_URL", "https://api.avalai.ir")
    response = post(f"{base_url.rstrip('/')}/v1beta/models/{TURNS_MODEL}:generateContent",
                    headers={"Authorization": f"Bearer {key}"}, json=body, timeout=300)
    if response.status_code != 200:
        raise RuntimeError(f"AvalAI returned HTTP {response.status_code}: {response.text[:300]}")
    payload = response.json()
    usage = payload.get("usageMetadata", {})
    prompt_tokens = int(usage.get("promptTokenCount", 0))
    cost = GeminiVideoAnalyze.usage_cost(TURNS_MODEL, prompt_tokens,
                                         int(usage.get("candidatesTokenCount", 0))) or 0.0
    # Same guard as gemini_video_analyze: an answer written without the
    # audio would invent speakers.
    if prompt_tokens and prompt_tokens < 0.4 * seconds * AUDIO_TOKENS_PER_SECOND:
        raise RuntimeError(f"the model answered without the audio ({prompt_tokens} prompt tokens)")
    text = "".join(part.get("text", "") for c in payload.get("candidates", [])
                   for part in c.get("content", {}).get("parts", []))
    answer = json.loads(text[text.find("{"): text.rfind("}") + 1])
    turns = [t for t in answer.get("turns", []) if t.get("text", "").strip()]
    return {"turns": turns, "speakers": answer.get("speakers") or {}}, cost


def _word_key(word: str) -> str:
    return re.sub(r"[^\w']", "", word.lower())


def align_turns(turns: list[dict], words: list[dict]) -> list[dict]:
    """Give each speaker turn the start/end of its words in the timed
    transcript. Turn words are matched to whisper words in order; a whisper
    word with no match belongs to the turn before it."""
    turn_words = [(i, _word_key(w)) for i, t in enumerate(turns) for w in t["text"].split()]
    turn_words = [(i, w) for i, w in turn_words if w]
    timed = [_word_key(w["word"]) for w in words]
    owner: list[Optional[int]] = [None] * len(words)
    matcher = difflib.SequenceMatcher(a=[w for _, w in turn_words], b=timed, autojunk=False)
    for a, b, size in matcher.get_matching_blocks():
        for k in range(size):
            owner[b + k] = turn_words[a + k][0]
    current = next((o for o in owner if o is not None), 0)
    for k, o in enumerate(owner):
        if o is None or o < current:  # keep turn order monotonic
            owner[k] = current
        else:
            current = o
    lines = []
    for i, turn in enumerate(turns):
        mine = [w for w, o in zip(words, owner) if o == i]
        if not mine:
            continue
        lines.append({"speaker": turn["speaker"], "start": round(mine[0]["start"], 3),
                      "end": round(mine[-1]["end"], 3), "text": turn["text"].strip()})
    return lines


def prepare(project: Path, source: Path, *, source_language: str = "en", channel: str = "fa-main",
            rights: str = "unknown", stems_tool=None, stt=None, labeler: Optional[Callable] = None,
            run: Callable[[list[str]], Any] = _run) -> dict:
    if rights not in RIGHTS:
        raise ValueError(f"rights must be one of {RIGHTS}")
    from tools.analysis.avalai_stt import AvalAISTT, audio_seconds
    from tools.audio.stem_separator import StemSeparator

    stems_tool = stems_tool or StemSeparator()
    stt = stt or AvalAISTT()
    labeler = labeler or gemini_turns
    root = dub_dir(project)
    meta = {"source": str(source), "source_language": source_language, "channel": channel,
            "rights": rights, "created": datetime.date.today().isoformat(), "cost_usd": {}}

    stems = stems_tool.execute({"input_path": str(source), "output_dir": str(root / "stems")})
    if not stems.success:
        raise RuntimeError(stems.error)
    speech = _speech_wav(Path(stems.data["vocals"]), root / "stems" / "vocals_16k.wav", run)
    heard = stt.execute({"audio_path": str(speech), "word_timestamps": True,
                         "language": source_language,
                         "output_path": str(root / "transcript_en.json")})
    if not heard.success:
        raise RuntimeError(heard.error)
    words = heard.data.get("words") or []
    if not words:
        raise RuntimeError("the transcript has no word timestamps")
    labels, label_cost = labeler(speech, audio_seconds(speech) or words[-1]["end"])
    _write(root / "turns_en.json", labels["turns"])
    _write(root / "speakers.json", labels["speakers"])
    lines = merge_turns(align_turns(labels["turns"], words))
    if not lines:
        raise RuntimeError("no speaker turn could be placed on the timeline")
    meta["cost_usd"].update(transcription=heard.cost_usd or 0.0, speaker_labels=label_cost)
    _write(root / "segments_en.json", lines)
    _write(root / "meta.json", meta)
    return {"lines": len(lines), "speakers": sorted({l["speaker"] for l in lines}),
            "cost_usd": round((heard.cost_usd or 0.0) + label_cost, 6)}


# -- voices and styles -------------------------------------------------------

def map_voices(segments: list[dict], pool: list[str], existing: Optional[dict] = None,
               genders: Optional[dict[str, str]] = None) -> dict[str, str]:
    """Source speakers in order of first appearance -> pool voices, same
    gender first when it is known. A speaker already mapped keeps its voice
    (re-runs must not swap voices)."""
    if not pool:
        raise ValueError("voices.yaml has no dub_pool")
    mapping = dict(existing or {})
    for seg in sorted(segments, key=lambda s: s["start"]):
        speaker = seg["speaker"]
        if speaker in mapping:
            continue
        free = [v for v in pool if v not in mapping.values()]
        gender = (genders or {}).get(speaker)
        same = [v for v in free if gender and VOICE_GENDER.get(v) == gender]
        mapping[speaker] = (same or free or [pool[len(mapping) % len(pool)]])[0]
    return mapping


def style_for(emotion: str = "", energy: str = "") -> str:
    words = [w.strip().lower() for w in (emotion or "").replace("/", ",").split(",") if w.strip()]
    feel = "، ".join(EMOTION_FA.get(w, w) for w in words)
    parts = ["محاوره‌ی تهرانی", ENERGY_FA.get((energy or "").lower(), ""), feel]
    return "، ".join(p for p in parts if p)


def _mmss(value: Any) -> float:
    from tools.analysis.gemini_video_analyze import parse_offset

    return parse_offset(value) or 0.0


def styles_from_analysis(segments: list[dict], analysis: dict) -> dict[str, str]:
    """Style per line from gemini_video_analyze segments, by largest overlap."""
    rows = [(_mmss(a.get("start")), _mmss(a.get("end")), a.get("emotion", ""), a.get("energy", ""))
            for a in analysis.get("segments") or []]
    styles = {}
    for seg in segments:
        best, best_overlap = None, 0.0
        for start, end, emotion, energy in rows:
            overlap = min(end, seg["end"]) - max(start, seg["start"])
            if overlap > best_overlap:
                best, best_overlap = (emotion, energy), overlap
        styles[seg["id"]] = style_for(*best) if best else style_for()
    return styles


# -- translate ---------------------------------------------------------------

def cps_for_voice(voices: dict, voice: str) -> float:
    """Measured cps for a voice from the channel's audition tables."""
    values = [row["cps"] for key, rows in voices.items() if key.startswith("audition")
              for row in rows or [] if row.get("voice") == voice and row.get("cps")]
    return round(sum(values) / len(values), 2) if values else DEFAULT_CPS


def translation_prompt(segments: list[dict], budgets: dict[str, int], glossary: list[dict],
                       context: Optional[list[dict]] = None) -> str:
    terms = "\n".join(f"- {g['en']} = {g['fa']}" for g in glossary) or "- (none)"
    before = "\n".join(f"{s['speaker']}: {s['text']}" for s in context or []) or "(start of the video)"
    lines = "\n".join(
        f'{{"id": "{s["id"]}", "speaker": "{s["speaker"]}", "max_letters": {budgets[s["id"]]}, '
        f'"en": {json.dumps(s["text"], ensure_ascii=False)}}}'
        for s in segments)
    return f"""Translate this dialogue into spoken Tehrani Persian for a dub.

- Natural, conversational Persian (محاوره), the way two friends talk on a
  YouTube show. Not written or formal Persian.
- Each line must be speakable in the same time as the English: keep it at or
  under max_letters (letters only, spaces and punctuation not counted).
  Shorten by dropping filler, never by dropping facts.
- Numbers and years as Persian words (هزار و نهصد و چهل و پنج).
- Foreign names in Persian spelling (پرسی اسپنسر، ریتیون).
- Keep the jokes working in Persian; adapt them if a literal one falls flat.
- Fixed terms:
{terms}

Return JSON: {{"lines": [{{"id": "...", "fa": "..."}}]}}, every id once, same order.

Said just before (context only, do not translate):
{before}

Lines to translate:
{lines}
"""


def draft_translation(project: Path, *, llm=None, channel=None, analysis: Optional[dict] = None) -> dict:
    from lib.channel_bible import load_channel
    from tools.text.llm_selector import LLMSelector

    root = dub_dir(project)
    meta = _read(root / "meta.json")
    channel = channel or load_channel(meta["channel"])
    segments = load_segments(project, "segments_en.json")
    genders = _read(root / "speakers.json") if (root / "speakers.json").exists() else None
    voice_map = map_voices(segments, channel.voices.get("dub_pool") or [],
                           _read(root / "voice_map.json") if (root / "voice_map.json").exists() else None,
                           genders)
    _write(root / "voice_map.json", voice_map)
    budgets = {s["id"]: char_budget(s["end"] - s["start"], cps_for_voice(channel.voices, voice_map[s["speaker"]]))
               for s in segments}
    styles = styles_from_analysis(segments, analysis) if analysis else {}

    llm = llm or LLMSelector()
    # Small chunks: the worker models reason before answering, and a whole
    # video in one call ran out of tokens and came back empty (2026-11-04).
    by_id: dict[str, str] = {}
    cost, models = 0.0, set()
    for i in range(0, len(segments), TRANSLATE_CHUNK):
        chunk = segments[i:i + TRANSLATE_CHUNK]
        result = llm.execute({"task": "translation_draft_en_fa", "json_schema": TRANSLATE_SCHEMA,
                              "prompt": translation_prompt(chunk, budgets, channel.glossary,
                                                           segments[max(0, i - 2):i]),
                              "max_tokens": 8000, "temperature": 0.4})
        cost += result.cost_usd or 0.0
        if not result.success:
            raise RuntimeError(result.error)
        answer = result.data.get("json") or json.loads(result.data["text"])
        by_id.update({row["id"]: row["fa"].strip() for row in answer.get("lines", [])})
        models.add(result.data.get("model"))
    missing = [s["id"] for s in segments if not by_id.get(s["id"])]
    if missing:
        raise RuntimeError("translation is missing lines: " + ", ".join(missing))

    rows = [{
        "id": s["id"], "start": s["start"], "end": s["end"], "speaker": s["speaker"],
        "voice": voice_map[s["speaker"]], "source_text": s["text"],
        "text": by_id[s["id"]], "draft_text": by_id[s["id"]],
        "budget_letters": budgets[s["id"]], "style": styles.get(s["id"], style_for()),
        # Final Persian from the worker tier: the agent (premium) and the
        # owner review every line before synthesis.
        "review": "draft",
    } for s in segments]
    _write(root / "segments_fa.json", rows)
    meta["cost_usd"]["translation"] = round(cost, 6)
    meta["translation_model"] = ", ".join(sorted(m for m in models if m))
    _write(root / "meta.json", meta)
    return {"lines": len(rows), "model": meta["translation_model"], "cost_usd": round(cost, 6)}


def approve_lines(project: Path, ids: Optional[list[str]] = None, channel=None,
                  editor: str = "owner") -> int:
    """Mark lines approved; lines whose text differs from the draft are kept
    as before/after examples in the channel bible, tagged with who edited."""
    from lib.channel_bible import load_channel, record_edit

    root = dub_dir(project)
    meta = _read(root / "meta.json")
    channel = channel or load_channel(meta["channel"])
    rows = load_segments(project)
    count = 0
    for row in rows:
        if ids and row["id"] not in ids:
            continue
        if row["review"] != "approved" and row["text"] != row.get("draft_text"):
            record_edit(channel, Path(project).name, "dub_line", row["draft_text"], row["text"],
                        note=f"{editor} edit, {row['id']} ({row['source_text'][:60]})")
        row["review"] = "approved"
        count += 1
    _write(root / "segments_fa.json", rows)
    return count


# -- synthesize / record -------------------------------------------------------

def _duration(path: Path) -> float:
    from tools.analysis.audio_probe import probe_duration

    return float(probe_duration(str(path)))


def rewrite_with_worker(llm=None) -> Callable[[str, int, int], str]:
    from tools.text.llm_selector import LLMSelector

    llm = llm or LLMSelector()

    def rewrite(text: str, max_letters: int, attempt: int) -> str:
        # Reasoning models spend tokens before answering; 2k came back empty.
        result = llm.execute({"task": "dub_line_shorten", "temperature": 0.3, "max_tokens": 6000, "prompt": (
            "Shorten this spoken Tehrani Persian dub line so it has at most "
            f"{max_letters} letters (spaces and punctuation not counted). Keep the "
            "meaning, the facts and the tone; drop filler first. Answer with the "
            f"line only.\n\n{text}")})
        if not result.success:
            raise RuntimeError(result.error)
        return result.data["text"].strip().strip("«»\"")
    return rewrite


def synthesize(project: Path, *, tts=None, rewrite=None, channel=None, providers: Optional[list[str]] = None,
               allow_drafts: bool = False, rewrites: bool = True,
               duration: Callable[[Path], float] = _duration) -> dict:
    """Synthesize and fit every approved line. rewrites=False skips the
    worker rewrites (a premium pass after the agent shortened lines itself):
    long lines then borrow the next pause or get flagged."""
    from lib.channel_bible import load_channel
    from tools.audio.tts_selector import TTSSelector

    root = dub_dir(project)
    meta = _read(root / "meta.json")
    channel = channel or load_channel(meta["channel"])
    rows = load_segments(project)
    pending = [r["id"] for r in rows if r["review"] != "approved"]
    if pending and not allow_drafts:
        raise RuntimeError(f"{len(pending)} lines are not approved yet: {', '.join(pending[:8])}")
    narrator = channel.voice_for("narrator")
    tts = tts or TTSSelector()
    if not rewrites:
        rewrite = None
    elif rewrite is None:
        rewrite = rewrite_with_worker()
    clips = root / "clips"
    spent = {"tts": 0.0}

    def synthesize_for(seg: Segment):
        row = next(r for r in rows if r["id"] == seg.id)

        def synth(text: str) -> tuple[str, float]:
            request = {
                "text": text, "language_code": "fa", "voice_id": row["voice"],
                "style": row.get("style") or style_for(), "channel": channel.name,
                "model_id": narrator.get("model_final", "gemini-3.8-flash-tts"),
            }
            # Same line, voice and style as an earlier run: reuse the clip, so
            # editing one line re-synthesizes only that line. Google and AvalAI
            # serve the same Gemini voices, so the provider is not in the key.
            digest = hashlib.sha256(json.dumps(request, sort_keys=True, ensure_ascii=False)
                                    .encode("utf-8")).hexdigest()[:10]
            out = clips / f"{seg.id}_{digest}.wav"
            if out.exists():
                return str(out), float(duration(out))
            result = tts.execute({**request, "output_path": str(out), "allowed_providers":
                                  providers or narrator.get("providers", ["gemini", "avalai"])})
            if not result.success:
                raise RuntimeError(f"{seg.id}: {result.error}")
            spent["tts"] += result.cost_usd or 0.0
            seconds = result.data.get("audio_duration_seconds") or duration(out)
            return str(out), float(seconds)
        return synth

    segments = [to_segment(r) for r in rows]
    try:
        media_end = duration(Path(meta["source"]))
    except Exception:  # without the length the last line simply has no tail room
        media_end = None
    fits = fit_all(segments, synthesize_for, rewrite,
                   lambda s: cps_for_voice(channel.voices, next(r["voice"] for r in rows if r["id"] == s.id)),
                   media_end=media_end)
    _save_fits(project, fits, source="tts")
    meta["cost_usd"]["tts"] = round(spent["tts"], 6)
    _write(root / "meta.json", meta)
    return _fit_summary(fits) | {"cost_usd": round(spent["tts"], 6)}


def _save_fits(project: Path, fits: list[Fit], source: str) -> None:
    _write(dub_dir(project) / "fits.json", {"source": source, "fits": [f.to_dict() for f in fits]})


def load_fits(project: Path) -> list[Fit]:
    data = _read(dub_dir(project) / "fits.json")
    return [Fit(**f) for f in data["fits"]]


def _fit_summary(fits: list[Fit]) -> dict:
    counts: dict[str, int] = {}
    for f in fits:
        counts[f.status] = counts.get(f.status, 0) + 1
    return {"lines": len(fits), "status": counts,
            "review_required": [f.id for f in fits if f.review_required],
            "flagged": [f.id for f in fits if f.status == "flagged"]}


def export_vo(project: Path, run: Callable[[list[str]], Any] = _run) -> list[Path]:
    """Recording script per speaker with an English reference clip per line."""
    root = dub_dir(project)
    rows = load_segments(project)
    vocals = root / "stems" / "vocals.wav"
    written = []
    for speaker in sorted({r["speaker"] for r in rows}):
        folder = root / "vo" / speaker
        (folder / "ref").mkdir(parents=True, exist_ok=True)
        table = ["| line | time | seconds | max letters | Persian | English | reference |",
                 "|---|---|---|---|---|---|---|"]
        for r in (r for r in rows if r["speaker"] == speaker):
            ref = folder / "ref" / f"{r['id']}.wav"
            run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{r['start']:.3f}",
                 "-to", f"{r['end']:.3f}", "-i", str(vocals), "-ac", "1", str(ref)])
            table.append(f"| {r['id']} | {_clock(r['start'])}–{_clock(r['end'])} | "
                         f"{r['end'] - r['start']:.1f} | {r.get('budget_letters', '')} | {r['text']} | "
                         f"{r['source_text']} | ref/{r['id']}.wav |")
        script = folder / "script.md"
        script.write_text(
            f"# Recording script: {speaker}\n\n"
            "Record each line as `<line>.wav` (e.g. `s001.wav`) into a folder named after\n"
            "this speaker. Listen to the reference first and match its energy and length;\n"
            "a take may run at most 8% longer than the slot.\n\n" + "\n".join(table) + "\n",
            encoding="utf-8")
        written.append(script)
    return written


def import_vo(project: Path, takes_dir: Path, duration: Callable[[Path], float] = _duration) -> dict:
    """Fit recorded takes (no rewrites: the actor re-records instead)."""
    rows = load_segments(project)
    missing = []

    def take_for(seg: Segment) -> Path:
        for candidate in (Path(takes_dir) / seg.speaker / f"{seg.id}.wav", Path(takes_dir) / f"{seg.id}.wav"):
            if candidate.exists():
                return candidate
        missing.append(seg.id)
        return Path()

    paths = {r["id"]: take_for(to_segment(r)) for r in rows}
    if missing:
        raise FileNotFoundError("no take for: " + ", ".join(missing))
    fits = fit_all([to_segment(r) for r in rows],
                   lambda seg: (lambda text, p=paths[seg.id]: (str(p), duration(p))),
                   None, lambda seg: DEFAULT_CPS)
    _save_fits(project, fits, source="voice_actor")
    return _fit_summary(fits)


def _clock(seconds: float) -> str:
    return f"{int(seconds // 60):02d}:{seconds % 60:05.2f}"


# -- mix -----------------------------------------------------------------------

def mix(project: Path, *, out: Optional[Path] = None, mixer=None, loudness=None,
        run: Callable[[list[str]], Any] = _run) -> dict:
    """Place every line over the accompaniment at the original voice level,
    mux with the source picture and bring the result to -14 LUFS / -1 dBTP."""
    from tools.audio.audio_mixer import AudioMixer
    from tools.audio.loudness_normalize import LoudnessNormalize

    root = dub_dir(project)
    meta = _read(root / "meta.json")
    mixer = mixer or AudioMixer()
    loudness = loudness or LoudnessNormalize()
    placed_dir = root / "mix" / "placed"
    placed_dir.mkdir(parents=True, exist_ok=True)

    voice_level = loudness.measure(root / "stems" / "vocals.wav", -14.0, -1.0, 11.0)["input_i"]
    tracks = [{"path": str(root / "stems" / "accompaniment.wav"), "role": "music", "volume": 1.0}]
    for fit in load_fits(project):
        src = Path(fit.audio_path)
        clip_level = loudness.measure(src, -14.0, -1.0, 11.0)["input_i"]
        gain = max(-CLIP_GAIN_LIMIT_DB, min(CLIP_GAIN_LIMIT_DB, voice_level - clip_level))
        dst = placed_dir / f"{fit.id}.wav"
        filters = [f"atempo={fit.tempo:.4f}"] if fit.tempo > 1.0001 else []
        filters.append(f"volume={gain:.2f}dB")
        run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(src),
             "-af", ",".join(filters), "-ar", "48000", "-ac", "2", str(dst)])
        tracks.append({"path": str(dst), "role": "speech", "volume": 1.0,
                       "start_seconds": round(fit.start, 3)})

    mixed = root / "mix" / "dub_mix.wav"
    result = mixer.execute({"operation": "mix", "tracks": tracks, "normalize": False,
                            "output_path": str(mixed)})
    if not result.success:
        raise RuntimeError(result.error)

    out = Path(out or Path(project) / "renders" / "dub_fa.mp4")
    out.parent.mkdir(parents=True, exist_ok=True)
    raw = out.with_name(out.stem + "_raw.mp4")
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", meta["source"], "-i", str(mixed),
         "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
         "-shortest", str(raw)])
    final = loudness.execute({"input_path": str(raw), "output_path": str(out),
                              "true_peak": RENDER_TRUE_PEAK})
    if not final.success:
        raise RuntimeError(final.error)
    return {"output": str(out), "tracks": len(tracks), "voice_level_lufs": voice_level}


# -- QA ------------------------------------------------------------------------

def qa(project: Path, *, render: Optional[Path] = None, stt=None, loudness=None,
       check_round_trip: bool = True) -> dict:
    from tools.analysis.avalai_stt import AvalAISTT
    from tools.audio.loudness_normalize import LoudnessNormalize

    root = dub_dir(project)
    meta = _read(root / "meta.json")
    fits = load_fits(project)
    rows = {r["id"]: r for r in load_segments(project)}
    loudness = loudness or LoudnessNormalize()
    report: dict[str, Any] = {"checked": datetime.datetime.now().isoformat(timespec="seconds")}

    report["overlaps"] = overlaps(fits)
    report["flagged"] = [f.id for f in fits if f.status == "flagged"]
    report["unreviewed"] = [i for i, r in rows.items() if r.get("review") != "approved"]

    lows, cost = [], 0.0
    if check_round_trip:
        stt = stt or AvalAISTT()

        def heard_text(audio: Path, saved: Path, source: Path) -> Optional[str]:
            nonlocal cost
            # A transcript newer than the synthesized clip is still valid (the
            # placed copy is rebuilt from it on every mix): an interrupted or
            # repeated QA run does not pay for those lines again.
            if saved.exists() and source.exists() and saved.stat().st_mtime >= source.stat().st_mtime:
                return _read(saved).get("text", "")
            heard = stt.execute({"audio_path": str(audio), "language": "fa", "model": QA_STT_MODEL,
                                 "output_path": str(saved)})
            if not heard.success:
                return None
            cost += heard.cost_usd or 0.0
            return heard.data["text"]

        for fit in fits:
            source = Path(fit.audio_path)
            clip = root / "mix" / "placed" / f"{fit.id}.wav"
            audio = clip if clip.exists() else source
            text = heard_text(audio, root / "qa_stt" / f"{fit.id}.{QA_STT_MODEL}.json", source)
            if text is None:
                lows.append({"id": fit.id, "error": "transcription failed"})
                continue
            score = round_trip(text, fit.text)["best"]
            if score < ROUND_TRIP_FLOOR and audio != source:
                # Short lines vary a lot between transcriptions, and the placed
                # copy is sped up: ask again on the clip as synthesized.
                raw_text = heard_text(source, root / "qa_stt" / f"{fit.id}.{QA_STT_MODEL}.raw.json", source)
                if raw_text is not None and round_trip(raw_text, fit.text)["best"] > score:
                    text, score = raw_text, round_trip(raw_text, fit.text)["best"]
            if score < ROUND_TRIP_FLOOR:
                lows.append({"id": fit.id, "score": score, "heard": text, "text": fit.text})
    report["round_trip_low"] = lows

    render = Path(render or Path(project) / "renders" / "dub_fa.mp4")
    measured = loudness.measure(render, -14.0, -1.0, 11.0) if render.exists() else None
    report["loudness"] = None if measured is None else {
        "integrated_lufs": measured["input_i"], "true_peak_dbtp": measured["input_tp"],
        "pass": abs(measured["input_i"] + 14.0) <= 1.0 and measured["input_tp"] <= -1.0 + 0.1,
    }
    rights = meta.get("rights", "unknown")
    report["rights"] = rights
    report["warnings"] = []
    if rights == "unknown":
        report["warnings"].append(
            "حق استفاده از ویدیوی منبع معلوم نیست (rights: unknown). قبل از انتشار، "
            "اجازه‌ی صاحب اثر رو بگیر یا ویدیوی خودت رو استفاده کن.")
    report["pass"] = (not report["overlaps"] and not report["flagged"] and not report["unreviewed"]
                      and not lows and bool(report["loudness"] and report["loudness"]["pass"]))
    report["cost_usd"] = round(cost, 6)
    _write(root / "qa.json", report)
    return report


def status(project: Path) -> dict:
    root = dub_dir(project)
    have = {name: (root / name).exists() for name in
            ("meta.json", "segments_en.json", "segments_fa.json", "fits.json", "qa.json")}
    info: dict[str, Any] = {"files": have}
    if have["meta.json"]:
        info["meta"] = _read(root / "meta.json")
    if have["segments_fa.json"]:
        rows = load_segments(project)
        info["approved"] = sum(r["review"] == "approved" for r in rows)
        info["lines"] = len(rows)
    return info
