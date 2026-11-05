"""Still-led videos with images the owner makes by hand.

The owner generates the stills with Nano Banana (Gemini app or AI Studio,
often cheaper or free) and drops them in a folder; everything else is
automatic: the prompt pack to copy from, a check of the images, narration
per scene, and a HyperFrames workspace where every still gets a camera move,
captions and era stamps timed to the voice, rendered and brought to -14 LUFS.

Everything lives under <project>/manual_images/:

    shotlist.json     scenes -> narration, caption, shots (prompt, camera)
    PROMPTS.md        the prompts with the file name to save each image as
    prompts.html      the same with copy buttons and previews (open from disk)
    in/<shot>.png     the owner's images (png, jpg, jpeg or webp)
    audio/            narration per scene (cached by text, voice and style)
    workspace/        the generated HyperFrames composition
    timing.json       where every scene, shot and caption sits

    python scripts/fa_manual_images.py init    --project projects/<id>
    python scripts/fa_manual_images.py prompts --project projects/<id>
    python scripts/fa_manual_images.py check   --project projects/<id>
    python scripts/fa_manual_images.py build   --project projects/<id> --render
"""

from __future__ import annotations

import hashlib
import html
import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from lib.fa_text import chars_per_second, normalize

REPO_ROOT = Path(__file__).resolve().parent.parent
GSAP = REPO_ROOT / ".agents" / "skills" / "music-to-video" / "references" / "motion-primitives" / "assets" / "gsap.min.js"
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp")
CAMERAS = ("push_in", "pull_out", "pan_left", "pan_right", "tilt_up", "tilt_down", "still")
# Varied by default so consecutive stills never move the same way.
CAMERA_CYCLE = ("push_in", "pan_right", "pull_out", "pan_left", "tilt_up", "push_in")
ASPECT = 16 / 9
ASPECT_TOLERANCE = 0.04
MIN_WIDTH = 1280
LEAD_IN = 0.25        # silence before the first line
SCENE_TAIL = 0.35     # breath after each scene's line
MIN_SHOT = 1.2
CAPTION_WORDS = 6
DEFAULT_RULES = [
    "No text, letters, numbers, signs or logos anywhere in the image.",
    "Landscape 16:9.",
    "Keep the main subject in the upper two thirds; the bottom fifth is for captions.",
]


# -- files ---------------------------------------------------------------------

def root(project: Path) -> Path:
    return Path(project) / "manual_images"


def _read(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write(path: Path, data: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


TEMPLATE = {
    "title": "",
    "style": {
        "prompt": "Flat 2D hand-drawn cartoon illustration with bold ink outlines.",
        "references": [],
        "rules": DEFAULT_RULES,
    },
    "voice": {"channel": "fa-main", "providers": ["avalai"]},
    "music": {"path": "", "volume": 0.18},
    "scenes": [{
        "id": "s1",
        "narration": "متن گفتاری این صحنه، عددها با حروف.",
        "caption": "زیرنویس همین صحنه، عددها با رقم.",
        "stamp": "",
        "transition": "cut",
        "shots": [{"id": "s1a", "prompt": "What the image shows, in English.", "camera": "push_in",
                   "focus": [0.5, 0.45]}],
    }],
}


def init(project: Path) -> Path:
    """Write a template shot list (never overwrites)."""
    path = root(project) / "shotlist.json"
    if path.exists():
        raise FileExistsError(f"{path} already exists")
    (root(project) / "in").mkdir(parents=True, exist_ok=True)
    return _write(path, TEMPLATE)


def load_shotlist(project: Path) -> dict:
    data = _read(root(project) / "shotlist.json")
    problems = validate(data)
    if problems:
        raise ValueError("shotlist.json: " + "; ".join(problems))
    return data


def validate(data: dict) -> list[str]:
    problems = []
    scenes = data.get("scenes") or []
    if not scenes:
        problems.append("no scenes")
    seen: set[str] = set()
    cast = (data.get("style") or {}).get("characters") or {}
    for scene in scenes:
        sid = scene.get("id") or "?"
        if not (scene.get("narration") or scene.get("audio")):
            problems.append(f"{sid}: needs narration text or an audio file")
        if not scene.get("shots"):
            problems.append(f"{sid}: no shots")
        for shot in scene.get("shots") or []:
            shid = shot.get("id")
            if not shid or not re.fullmatch(r"[A-Za-z0-9_-]+", shid):
                problems.append(f"{sid}: shot id must be letters, digits, _ or -: {shid!r}")
            elif shid in seen:
                problems.append(f"duplicate shot id {shid}")
            seen.add(shid or "")
            if not shot.get("prompt"):
                problems.append(f"{shid}: no prompt")
            if shot.get("camera", "push_in") not in CAMERAS:
                problems.append(f"{shid}: camera must be one of {', '.join(CAMERAS)}")
            for name in shot.get("characters") or []:
                if name not in cast:
                    problems.append(f"{shid}: character {name!r} is not in style.characters")
            if shot.get("cue") and shot["cue"] not in (scene.get("narration") or ""):
                problems.append(f"{shid}: cue {shot['cue']!r} is not in the scene's narration")
    return problems


def shots(data: dict) -> list[tuple[dict, dict]]:
    return [(scene, shot) for scene in data["scenes"] for shot in scene["shots"]]


# -- prompt pack -----------------------------------------------------------------

def full_prompt(shot: dict, style: dict) -> str:
    rules = style.get("rules") or DEFAULT_RULES
    parts = [shot["prompt"].strip()]
    # Bulk tools (ZAPI FLOW) cannot attach reference images, so a recurring
    # character is kept consistent by repeating the same description.
    cast = style.get("characters") or {}
    looks = [f"{name}: {cast[name].strip()}" for name in shot.get("characters") or [] if name in cast]
    if looks:
        parts.append("Characters: " + " ".join(looks))
    if style.get("prompt"):
        parts.append("Style: " + style["prompt"].strip())
    parts.append(" ".join(rules))
    return "\n\n".join(parts)


def write_prompt_pack(project: Path) -> dict:
    data = load_shotlist(project)
    style = data.get("style") or {}
    out = root(project)
    refs = style.get("references") or []
    md = [f"# پرامپت عکس‌ها: {data.get('title') or Path(project).name}", "",
          "۱. هر پرامپت رو توی Nano Banana (اپ Gemini یا AI Studio) بچسبون.",
          "۲. اگه عکس مرجع سبک داری، همراه پرامپت پیوستش کن تا همه‌ی عکس‌ها یکدست بشن:" if refs else
          "۲. اولین عکسی که پسندیدی رو برای بقیه به‌عنوان مرجع سبک پیوست کن تا یکدست بشن.",
          *[f"   - `{r}`" for r in refs],
          "۳. عکس رو افقی (۱۶:۹) بگیر و با همون اسمی که زیرش نوشته ذخیره کن، توی پوشه‌ی `in/`.",
          "۴. اگه توی عکس نوشته یا حرف دیدی، دوباره بساز؛ متن فارسی رو خود ویدیو اضافه می‌کنه.", ""]
    cards = []
    for scene, shot in shots(data):
        prompt = full_prompt(shot, style)
        saved = find_image(project, shot["id"])
        preview = f"in/{saved.name}" if saved else f"in/{shot['id']}.png"
        md += [f"## {shot['id']}  →  `in/{shot['id']}.png`", "",
               f"صحنه‌ی {scene['id']}: «{scene.get('caption') or scene.get('narration', '')}»", "",
               "```", prompt, "```", ""]
        cards.append(
            f'<section class="card"><header><b>{html.escape(shot["id"])}</b>'
            f'<span>ذخیره با اسم <code>in/{html.escape(shot["id"])}.png</code></span></header>'
            f'<p class="line">{html.escape(scene.get("caption") or scene.get("narration", ""))}</p>'
            f'<div class="row"><pre dir="ltr" id="p-{html.escape(shot["id"])}">{html.escape(prompt)}</pre>'
            f'<img src="{html.escape(preview)}" alt="" onerror="this.classList.add(\'missing\')"></div>'
            f'<button onclick="copy(\'p-{html.escape(shot["id"])}\', this)">کپی پرامپت</button></section>')
    order = [shot["id"] for _, shot in shots(data)]
    lines = [zapi_line(shot, style) for _, shot in shots(data)]
    (out / "zapi_flow.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    _write(out / "zapi_flow_order.json", order)
    md[2:2] = ["**راه سریع (ZAPI FLOW):** همه‌ی پرامپت‌ها یکجا توی `zapi_flow.txt` هستن، هر خط یه عکس به همین ترتیب.",
               "توی Flow حالت تصویر و افقی ۱۶:۹ رو بذار، توی ZAPI FLOW «شماره‌ی ردیف توی اسم فایل» رو روشن کن، "
               "بعد پوشه‌ی دانلود رو با دستور `import` بده؛ عکس‌ها خودشون با اسم درست میان توی `in/`.", ""]
    (out / "PROMPTS.md").write_text("\n".join(md), encoding="utf-8")
    (out / "prompts.html").write_text(PROMPTS_PAGE.format(
        title=html.escape(data.get("title") or Path(project).name),
        count=len(cards),
        refs="".join(f"<li><code dir='ltr'>{html.escape(r)}</code></li>" for r in refs) or "<li>ندارد</li>",
        zapi=html.escape("\n".join(lines)),
        cards="\n".join(cards)), encoding="utf-8")
    (out / "in").mkdir(parents=True, exist_ok=True)
    return {"prompts": len(cards), "markdown": str(out / "PROMPTS.md"), "html": str(out / "prompts.html"),
            "zapi_flow": str(out / "zapi_flow.txt")}


def zapi_line(shot: dict, style: dict) -> str:
    """The full prompt on one line: ZAPI FLOW reads one prompt per line."""
    return " ".join(full_prompt(shot, style).split())


PROMPTS_PAGE = """<!doctype html>
<html lang="fa" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>پرامپت عکس‌ها</title>
<style>
:root {{ color-scheme: light dark; --bg:#f8f6f1; --fg:#1e1b16; --muted:#6c665c; --card:#fff; --line:#e3ddd2; --accent:#1f4fd1; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#15161a; --fg:#ebe8e2; --muted:#a19b90; --card:#1e2026; --line:#30333a; --accent:#8aa8ff; }} }}
body {{ margin:0; padding:24px 16px; background:var(--bg); color:var(--fg); font-family:Vazirmatn,Tahoma,sans-serif; line-height:1.8; }}
main {{ max-width:1100px; margin:auto; }}
h1 {{ font-size:1.4rem; margin:0; }} p, li {{ color:var(--muted); }}
.card {{ background:var(--card); border:1px solid var(--line); border-radius:14px; padding:16px; margin:16px 0; }}
.card header {{ display:flex; gap:12px; align-items:baseline; flex-wrap:wrap; }}
.line {{ margin:4px 0 10px; color:var(--fg); }}
.row {{ display:flex; gap:16px; flex-wrap:wrap; }}
pre {{ flex:1 1 420px; white-space:pre-wrap; margin:0; padding:12px; background:var(--bg); border-radius:10px; font-size:.85rem; text-align:left; }}
img {{ width:260px; aspect-ratio:16/9; object-fit:cover; border-radius:10px; border:1px solid var(--line); }}
img.missing {{ visibility:hidden; }}
button {{ margin-top:10px; font:inherit; padding:6px 16px; border-radius:8px; border:1px solid var(--accent); background:transparent; color:var(--accent); cursor:pointer; }}
code {{ font-size:.9em; }}
</style></head><body><main>
<h1>پرامپت عکس‌ها: {title}</h1>
<p>{count} عکس. هر پرامپت رو کپی کن، توی Nano Banana بساز، با اسمی که بالای هر کارت نوشته توی پوشه‌ی <code>in</code> کنار همین صفحه ذخیره کن. عکسی که ذخیره بشه همین‌جا پیش‌نمایشش دیده می‌شه (صفحه رو تازه کن).</p>
<p>عکس‌های مرجع سبک برای پیوست:</p><ul>{refs}</ul>
<section class="card"><header><b>همه یکجا برای ZAPI FLOW</b>
<span>هر خط یه عکس، به ترتیب کارت‌های پایین. توی Flow حالت تصویر و ۱۶:۹ رو بذار و توی ZAPI FLOW «شماره‌ی ردیف توی اسم فایل» رو روشن کن.</span></header>
<pre dir="ltr" id="zapi-all">{zapi}</pre>
<button onclick="copy('zapi-all', this)">کپی همه‌ی پرامپت‌ها</button></section>
{cards}
</main>
<script>
function copy(id, button) {{
  const text = document.getElementById(id).innerText;
  navigator.clipboard.writeText(text).then(() => {{ button.textContent = "کپی شد ✓"; }},
    () => {{ const r = document.createRange(); r.selectNode(document.getElementById(id));
             const s = getSelection(); s.removeAllRanges(); s.addRange(r); button.textContent = "انتخاب شد؛ Ctrl+C"; }});
}}
</script></body></html>
"""


# -- image check -----------------------------------------------------------------

def find_image(project: Path, shot_id: str) -> Optional[Path]:
    for suffix in IMAGE_SUFFIXES:
        path = root(project) / "in" / f"{shot_id}{suffix}"
        if path.exists():
            return path
    return None


def _serial(stem: str, count: int) -> Optional[int]:
    """The row number ZAPI FLOW puts in a file name, if it looks like one."""
    match = re.search(r"\d+", stem)
    if match and 1 <= int(match.group()) <= count:
        return int(match.group())
    return None


def import_flow(project: Path, folder: Path, *, by: str = "auto", overwrite: bool = False) -> dict:
    """Copy images downloaded by ZAPI FLOW into in/<shot id>.<ext>.

    Rows map to shots through zapi_flow_order.json (the order zapi_flow.txt was
    written in). With "serial", the first number in each file name is the row;
    with "time", files are taken in download order. "auto" uses serials when
    every file has one in range, else download order. Flow can return several
    images per prompt: the first download is used, the rest go to in/alts/.
    """
    if by not in ("auto", "serial", "time"):
        raise ValueError("by must be auto, serial or time")
    out = root(project)
    order_path = out / "zapi_flow_order.json"
    order = _read(order_path) if order_path.exists() else [shot["id"] for _, shot in shots(load_shotlist(project))]
    files = sorted((p for p in Path(folder).iterdir() if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES),
                   key=lambda p: (p.stat().st_mtime, p.name))
    serials = {p: _serial(p.stem, len(order)) for p in files}
    if by == "auto":
        by = "serial" if files and all(serials.values()) else "time"
    if by == "serial":
        missing_serial = [p.name for p in files if not serials[p]]
        if missing_serial:
            raise ValueError("no row number in: " + ", ".join(missing_serial[:5]))
        groups: dict[int, list[Path]] = {}
        for path in files:
            groups.setdefault(serials[path], []).append(path)
    else:
        groups = {row: [path] for row, path in enumerate(files, 1)}

    copied, kept, alternates = [], [], 0
    for row, paths in sorted(groups.items()):
        if row > len(order):
            break
        shot_id = order[row - 1]
        existing = find_image(project, shot_id)
        if existing and not overwrite:
            kept.append(shot_id)
        else:
            if existing:
                existing.unlink()
            target = out / "in" / f"{shot_id}{paths[0].suffix.lower()}"
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(paths[0], target)
            copied.append({"shot": shot_id, "from": paths[0].name})
        for k, alt in enumerate(paths[1:], 1):
            (out / "in" / "alts").mkdir(parents=True, exist_ok=True)
            shutil.copy2(alt, out / "in" / "alts" / f"{shot_id}_alt{k}{alt.suffix.lower()}")
            alternates += 1
    report = {
        "by": by,
        "files": len(files),
        "copied": copied,
        "kept_existing": kept,
        "alternates": alternates,
        "unused_files": [p.name for row, ps in sorted(groups.items()) if row > len(order) for p in ps],
        "still_missing": [sid for sid in order if not find_image(project, sid)],
    }
    _write(out / "flow_import.json", report)
    return report


def check_images(project: Path) -> dict:
    from PIL import Image

    data = load_shotlist(project)
    rows = []
    for _, shot in shots(data):
        path = find_image(project, shot["id"])
        row: dict[str, Any] = {"id": shot["id"], "path": str(path) if path else None, "problems": []}
        if not path:
            row["problems"].append("missing")
        else:
            try:
                with Image.open(path) as img:
                    width, height = img.size
            except Exception as exc:  # a truncated download or a non-image file
                row["problems"].append(f"unreadable: {type(exc).__name__}")
            else:
                row.update(width=width, height=height)
                if abs(width / height - ASPECT) / ASPECT > ASPECT_TOLERANCE:
                    row["problems"].append(f"not 16:9 ({width}x{height}); it will be cropped")
                if width < MIN_WIDTH:
                    row["problems"].append(f"small ({width}px wide); camera moves will look soft")
        rows.append(row)
    missing = [r["id"] for r in rows if "missing" in r["problems"]]
    return {"shots": rows, "missing": missing, "ready": not missing
            and not any(p.startswith("unreadable") for r in rows for p in r["problems"])}


# -- narration -------------------------------------------------------------------

def _duration(path: Path) -> float:
    from tools.analysis.audio_probe import probe_duration

    return float(probe_duration(str(path)))


def narrate(project: Path, tts=None, duration: Callable[[Path], float] = _duration) -> dict:
    """One clip per scene. A scene's own `audio` file wins; otherwise TTS with
    the channel's narrator and lexicon. Clips are keyed by text and voice."""
    from lib.channel_bible import load_channel
    from tools.audio.tts_selector import TTSSelector

    data = load_shotlist(project)
    voice_cfg = data.get("voice") or {}
    narrator: dict = {}
    if voice_cfg.get("channel"):
        narrator = load_channel(voice_cfg["channel"]).voice_for("narrator")
    tts = tts or TTSSelector()
    out_dir = root(project) / "audio"
    clips, cost = {}, 0.0
    for scene in data["scenes"]:
        if scene.get("audio"):
            path = Path(scene["audio"])
            if not path.is_absolute():
                path = Path(project) / path
            if not path.exists():
                raise FileNotFoundError(f"{scene['id']}: audio not found: {path}")
            clips[scene["id"]] = {"path": str(path), "seconds": round(duration(path), 3), "source": "file"}
            continue
        request = {
            "text": scene["narration"], "language_code": "fa",
            "voice_id": voice_cfg.get("voice_id") or narrator.get("voice") or "Kore",
            "style": scene.get("style") or voice_cfg.get("style") or narrator.get("style") or "",
            "model_id": voice_cfg.get("model_id") or narrator.get("model_final", "gemini-3.8-flash-tts"),
        }
        if voice_cfg.get("channel"):
            request["channel"] = voice_cfg["channel"]
        digest = hashlib.sha256(json.dumps(request, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:10]
        path = out_dir / f"{scene['id']}_{digest}.wav"
        if not path.exists():
            result = tts.execute({**request, "output_path": str(path), "allowed_providers":
                                  voice_cfg.get("providers") or narrator.get("providers") or ["gemini", "avalai"]})
            if not result.success:
                raise RuntimeError(f"{scene['id']}: {result.error}")
            cost += result.cost_usd or 0.0
        clips[scene["id"]] = {"path": str(path), "seconds": round(duration(path), 3), "source": "tts"}
    return {"clips": clips, "cost_usd": round(cost, 6)}


# -- timing ----------------------------------------------------------------------

# A caption line should not end on a word that leans on the next one:
# prepositions and particles, or an ezafe («گوشیِ خراب»). «رو/را» lean
# back onto their noun, so they may end a line.
_LEANING = {"با", "به", "از", "در", "که", "و", "تو", "توی", "برای", "تا", "یه", "این", "اون", "یک"}


def _leans_forward(word: str) -> bool:
    return word in _LEANING or word.endswith("ِ")


def caption_chunks(text: str, max_words: int = CAPTION_WORDS) -> list[str]:
    """Split a caption at sentence and clause marks, then by word count."""
    pieces = [p.strip() for p in re.split(r"(?<=[.!؟?…،؛:])\s+", text.strip()) if p.strip()]
    chunks = []
    for piece in pieces:
        words = piece.split()
        while len(words) > max_words:
            # Balanced split: two 5-word lines read better than 6 + 4.
            take = -(-len(words) // -(-len(words) // max_words))
            while take > 2 and _leans_forward(words[take - 1]):
                take -= 1
            chunks.append(" ".join(words[:take]))
            words = words[take:]
        if words:
            chunks.append(" ".join(words))
    return chunks


CUE_LEAD = 0.15  # the picture lands just before the cue word is heard


def _letters(text: str) -> int:
    return len(normalize(text).replace(" ", ""))


def _cue_lengths(scene: dict, start: float, end: float, voice_start: float, seconds: float,
                 weights: list[float]) -> Optional[list[float]]:
    """Shot lengths when shots name the words they start on (`cue`), else None.

    A cue is placed by its share of the scene's letters, like the captions.
    Shots without a cue share the time between their cued neighbours by weight.
    """
    shots_ = scene["shots"]
    if not any(s.get("cue") for s in shots_[1:]):
        return None
    text = scene.get("narration", "")
    total = max(1, _letters(text))
    bounds: list[Optional[float]] = [start] + [None] * (len(shots_) - 1) + [end]
    for i, shot in enumerate(shots_[1:], 1):
        if shot.get("cue"):
            at = text.find(shot["cue"])
            bounds[i] = voice_start + seconds * _letters(text[:at]) / total - CUE_LEAD
    known = [i for i, b in enumerate(bounds) if b is not None]
    for left, right in zip(known, known[1:]):
        share = weights[left:right]
        cursor = bounds[left]
        for i in range(left + 1, right):
            cursor += (bounds[right] - bounds[left]) * share[i - left - 1] / sum(share)
            bounds[i] = cursor
    lengths = [b - a for a, b in zip(bounds, bounds[1:])]
    if any(length <= 0 for length in lengths):
        raise ValueError(f"{scene['id']}: shot cues are out of order")
    return lengths


def plan_timing(data: dict, clips: dict) -> dict:
    """Scene, shot and caption times from the narration lengths."""
    t = LEAD_IN
    scenes, captions, all_shots = [], [], []
    for index, scene in enumerate(data["scenes"]):
        seconds = clips[scene["id"]]["seconds"]
        start = 0.0 if index == 0 else t
        voice_start = t
        end = voice_start + seconds + SCENE_TAIL
        scenes.append({"id": scene["id"], "start": round(start, 3), "end": round(end, 3),
                       "voice_start": round(voice_start, 3), "voice_seconds": seconds,
                       "stamp": scene.get("stamp", ""), "transition": scene.get("transition", "cut")})

        weights = [max(0.1, float(s.get("weight", 1))) for s in scene["shots"]]
        span = end - start
        lengths = _cue_lengths(scene, start, end, voice_start, seconds, weights)
        cued = lengths is not None
        if not cued:
            lengths = [span * w / sum(weights) for w in weights]
        # Very short shots read as flicker; give them a floor and take the time
        # from the longer shots in proportion to what they have above it, so
        # none of them drops under the floor and the scene keeps its length.
        # Cued shots keep their exact cut points.
        if not cued and span >= MIN_SHOT * len(lengths):
            deficit = sum(MIN_SHOT - length for length in lengths if length < MIN_SHOT)
            excess = sum(length - MIN_SHOT for length in lengths if length > MIN_SHOT)
            if deficit and excess:
                lengths = [MIN_SHOT if length <= MIN_SHOT
                           else length - (length - MIN_SHOT) * deficit / excess for length in lengths]
        cursor = start
        for shot, length in zip(scene["shots"], lengths):
            all_shots.append({"id": shot["id"], "scene": scene["id"], "start": round(cursor, 3),
                              "end": round(cursor + length, 3),
                              "camera": shot.get("camera") or CAMERA_CYCLE[len(all_shots) % len(CAMERA_CYCLE)],
                              "focus": shot.get("focus") or [0.5, 0.45]})
            cursor += length

        chunks = caption_chunks(scene.get("caption") or scene.get("narration", "")) if data.get("captions", True) else []
        letters = [max(1, len(normalize(c).replace(" ", ""))) for c in chunks]
        c_start = voice_start
        for chunk, n in zip(chunks, letters):
            c_len = seconds * n / sum(letters)
            captions.append({"scene": scene["id"], "text": chunk, "start": round(c_start, 3),
                             "end": round(c_start + c_len, 3)})
            c_start += c_len
        t = end
    return {"duration": round(t + 0.4, 3), "scenes": scenes, "shots": all_shots, "captions": captions}


# -- workspace -------------------------------------------------------------------

def camera_from_to(camera: str, focus: list[float]) -> tuple[tuple, tuple]:
    """(px, py, scale) at the start and end of a shot."""
    fx, fy = focus
    return {
        "push_in": ((fx, fy, 1.04), (fx, fy, 1.16)),
        "pull_out": ((fx, fy, 1.18), (fx, fy, 1.04)),
        "pan_left": ((min(fx + 0.08, 0.9), fy, 1.15), (max(fx - 0.08, 0.1), fy, 1.15)),
        "pan_right": ((max(fx - 0.08, 0.1), fy, 1.15), (min(fx + 0.08, 0.9), fy, 1.15)),
        "tilt_up": ((fx, min(fy + 0.07, 0.9), 1.14), (fx, max(fy - 0.07, 0.1), 1.14)),
        "tilt_down": ((fx, max(fy - 0.07, 0.1), 1.14), (fx, min(fy + 0.07, 0.9), 1.14)),
        "still": ((fx, fy, 1.03), (fx, fy, 1.05)),
    }[camera]


def build_workspace(project: Path, clips: dict) -> dict:
    from lib.fa_thumbnail import find_fonts

    data = load_shotlist(project)
    timing = plan_timing(data, clips)
    ws = root(project) / "workspace"
    for sub in ("img", "audio", "fonts", "js"):
        (ws / "assets" / sub).mkdir(parents=True, exist_ok=True)
    shutil.copyfile(GSAP, ws / "assets" / "js" / "gsap.min.js")
    # The render browser has no installed fonts: without these files every
    # Persian caption and stamp falls back to some other font.
    fonts = find_fonts()
    missing_fonts = []
    for weight, src in (("ExtraBold", fonts.bold), ("Black", fonts.black)):
        if src and src.name == f"Vazirmatn-{weight}.ttf":
            shutil.copyfile(src, ws / "assets" / "fonts" / src.name)
        else:
            missing_fonts.append(f"Vazirmatn-{weight}.ttf")
    warnings = []
    if missing_fonts:
        warnings.append(f"fonts not found: {', '.join(missing_fonts)} (searched {', '.join(fonts.searched)}); "
                        "Persian text will render in a fallback font. Install Vazirmatn or set SUBTITLE_FONTS_DIR.")

    sections, audio_tags = [], []
    for shot in timing["shots"]:
        img = find_image(project, shot["id"])
        if not img:
            raise FileNotFoundError(f"image missing for {shot['id']}; run check")
        name = f"{shot['id']}{img.suffix.lower()}"
        shutil.copyfile(img, ws / "assets" / "img" / name)
        sections.append(
            f'<section id="shot-{shot["id"]}" class="clip scene" data-start="{shot["start"]}" '
            f'data-duration="{round(shot["end"] - shot["start"], 3)}" data-track-index="0">'
            f'<div id="cam-{shot["id"]}" class="cam"><img src="assets/img/{name}" alt=""></div></section>')
    for i, scene in enumerate(timing["scenes"]):
        src = Path(clips[scene["id"]]["path"])
        name = f"vo_{scene['id']}{src.suffix.lower()}"
        shutil.copyfile(src, ws / "assets" / "audio" / name)
        audio_tags.append(
            f'<audio id="vo-{scene["id"]}" src="assets/audio/{name}" data-start="{scene["voice_start"]}" '
            f'data-duration="{scene["voice_seconds"]}" data-track-index="{10 + i}" data-volume="1"></audio>')
    music = (data.get("music") or {}).get("path")
    music_volume = float((data.get("music") or {}).get("volume", 0.18))
    if music:
        src = Path(music) if Path(music).is_absolute() else Path(project) / music
        if not src.exists():
            src = REPO_ROOT / music
        shutil.copyfile(src, ws / "assets" / "audio" / f"music{src.suffix.lower()}")
        audio_tags.append(
            f'<audio id="bgm" src="assets/audio/music{src.suffix.lower()}" data-start="0" '
            f'data-duration="{timing["duration"]}" data-track-index="9" data-volume="{music_volume}"></audio>')

    stamps = "".join(f'<div id="stamp-{s["id"]}" class="stamp">{html.escape(s["stamp"])}</div>'
                     for s in timing["scenes"] if s["stamp"])
    caps = "".join(f'<div id="cg-{i}" class="cg"><span class="box">{html.escape(c["text"])}</span></div>'
                   for i, c in enumerate(timing["captions"]))
    moves = []
    for s in timing["shots"]:
        start, end = camera_from_to(s["camera"], s["focus"])
        moves.append({"id": s["id"], "start": s["start"], "end": s["end"], "from": start, "to": end})
    page = WORKSPACE_PAGE.format(
        title=html.escape(data.get("title") or Path(project).name),
        duration=timing["duration"], sections="\n      ".join(sections), stamps=stamps, captions=caps,
        audio="\n      ".join(audio_tags),
        timeline=json.dumps({
            "moves": moves,
            "flashes": [s["start"] for s in timing["scenes"][1:] if s["transition"] == "flash"],
            "stamps": [{"id": s["id"], "start": s["voice_start"] + 0.1,
                        "end": min(s["end"], s["voice_start"] + 2.4)} for s in timing["scenes"] if s["stamp"]],
            "captions": [{"start": c["start"], "end": c["end"]} for c in timing["captions"]],
            "duration": timing["duration"], "music": bool(music), "music_volume": music_volume,
        }, ensure_ascii=False))
    (ws / "index.html").write_text(page, encoding="utf-8")
    _write(root(project) / "timing.json", timing)
    return {"workspace": str(ws), "duration": timing["duration"], "shots": len(timing["shots"]),
            "captions": len(timing["captions"]), "warnings": warnings}


WORKSPACE_PAGE = """<!doctype html>
<html lang="fa">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=1920, height=1080" />
    <title>{title}</title>
    <script src="assets/js/gsap.min.js"></script>
    <style>
      @font-face {{ font-family: "Vazirmatn"; src: url("assets/fonts/Vazirmatn-ExtraBold.ttf") format("truetype"); font-weight: 800; font-display: block; }}
      @font-face {{ font-family: "Vazirmatn"; src: url("assets/fonts/Vazirmatn-Black.ttf") format("truetype"); font-weight: 900; font-display: block; }}
      :root {{ --cream: #fff8ec; --cobalt: #1428a0; --pill: rgba(22, 16, 11, 0.76); }}
      body {{ margin: 0; background: #000; }}
      #root {{ position: relative; width: 1920px; height: 1080px; overflow: hidden; }}
      .scene, .cam, .overlay {{ position: absolute; inset: 0; }}
      .scene {{ overflow: hidden; background: #0d0b09; }}
      .cam img {{ display: block; width: 100%; height: 100%; object-fit: cover; }}
      .overlay {{ pointer-events: none; }}
      #fade-in, #fade-out {{ background: #000; }}
      #fade-out, #flash {{ opacity: 0; }}
      #flash {{ background: var(--cream); }}
      .stamp {{ position: absolute; top: 56px; right: 64px; direction: rtl; font-family: "Vazirmatn"; font-weight: 800;
               font-size: 44px; line-height: 1.3; color: var(--cream); background: var(--cobalt); padding: 8px 28px 14px;
               border-radius: 14px; box-shadow: 0 6px 24px rgba(0, 0, 0, 0.35); opacity: 0; }}
      .cg {{ position: absolute; left: 0; right: 0; bottom: 78px; display: flex; justify-content: center; opacity: 0; }}
      .cg .box {{ direction: rtl; max-width: 1600px; text-align: center; font-family: "Vazirmatn"; font-weight: 800;
                 font-size: 62px; line-height: 1.4; color: var(--cream); background: var(--pill); padding: 6px 36px 14px;
                 border-radius: 20px; text-shadow: 0 2px 10px rgba(0, 0, 0, 0.45); }}
    </style>
  </head>
  <body>
    <div id="root" data-composition-id="manual-images" data-width="1920" data-height="1080" data-duration="{duration}">
      {sections}
      <div id="fx" class="clip overlay" data-start="0" data-duration="{duration}" data-track-index="1">
        <div id="flash" class="overlay"></div><div id="fade-in" class="overlay"></div><div id="fade-out" class="overlay"></div>
      </div>
      <div id="stamps" class="clip overlay" data-start="0" data-duration="{duration}" data-track-index="2">{stamps}</div>
      <div id="captions" class="clip overlay" data-start="0" data-duration="{duration}" data-track-index="3">{captions}</div>
      {audio}
    </div>
    <script>
      window.__timelines = window.__timelines || {{}};
      const PLAN = {timeline};
      const W = 1920, H = 1080;
      const tl = gsap.timeline({{ paused: true }});
      // Put image point (px, py) at the frame centre at scale s, clamped so the image covers the frame.
      function frame(px, py, s) {{
        const lim = (s - 1) / 2;
        const clamp = (v) => Math.max(-lim, Math.min(lim, v));
        return {{ scale: s, x: clamp(-s * (px - 0.5)) * W, y: clamp(-s * (py - 0.5)) * H }};
      }}
      tl.fromTo("#fade-in", {{ opacity: 1 }}, {{ opacity: 0, duration: 0.35, ease: "power1.out" }}, 0);
      PLAN.moves.forEach((m) => {{
        const cam = "#cam-" + m.id;
        tl.set(cam, frame(...m.from), m.start);
        tl.to(cam, {{ ...frame(...m.to), duration: m.end - m.start, ease: "sine.inOut" }}, m.start);
      }});
      PLAN.flashes.forEach((t) => {{
        tl.set("#flash", {{ opacity: 0.8 }}, t);
        tl.to("#flash", {{ opacity: 0, duration: 0.3, ease: "power2.out" }}, t);
      }});
      PLAN.stamps.forEach((s) => {{
        const el = "#stamp-" + s.id;
        tl.fromTo(el, {{ opacity: 0, x: 40 }}, {{ opacity: 1, x: 0, duration: 0.3, ease: "power3.out" }}, s.start);
        tl.to(el, {{ opacity: 0, duration: 0.18, ease: "power2.in" }}, s.end - 0.18);
        tl.set(el, {{ opacity: 0 }}, s.end);
      }});
      PLAN.captions.forEach((c, i) => {{
        const el = "#cg-" + i;
        tl.fromTo(el, {{ opacity: 0, y: 18 }}, {{ opacity: 1, y: 0, duration: 0.16, ease: "power2.out" }}, c.start);
        tl.to(el, {{ opacity: 0, duration: 0.12, ease: "power2.in" }}, c.end - 0.12);
        tl.set(el, {{ opacity: 0 }}, c.end);
      }});
      tl.to("#fade-out", {{ opacity: 1, duration: 0.45, ease: "power1.in" }}, PLAN.duration - 0.45);
      if (PLAN.music) {{
        tl.fromTo("#bgm", {{ volume: 0 }}, {{ volume: PLAN.music_volume, duration: 0.5 }}, 0);
        tl.to("#bgm", {{ volume: 0, duration: 0.8, ease: "power1.in" }}, PLAN.duration - 0.8);
      }}
      window.__timelines["manual-images"] = tl;
    </script>
  </body>
</html>
"""


# -- render ----------------------------------------------------------------------

def render(project: Path, out: Optional[Path] = None, compose=None, loudness=None) -> dict:
    from tools.audio.loudness_normalize import LoudnessNormalize
    from tools.video.hyperframes_compose import HyperFramesCompose

    ws = root(project) / "workspace"
    out = Path(out or Path(project) / "renders" / "manual_images.mp4")
    out.parent.mkdir(parents=True, exist_ok=True)
    raw = out.with_name(out.stem + "_raw.mp4")
    compose = compose or HyperFramesCompose()
    result = compose.execute({"operation": "render_existing", "workspace_path": str(ws), "output_path": str(raw)})
    if not result.success:
        raise RuntimeError(result.error)
    loudness = loudness or LoudnessNormalize()
    # -1.5 dBTP: the AAC encode lifts peaks a little (seen on the dub renders).
    final = loudness.execute({"input_path": str(raw), "output_path": str(out), "true_peak": -1.5})
    if not final.success:
        raise RuntimeError(final.error)
    return {"output": str(out)}


def preview(project: Path, upto_seconds: float, *, render_video: bool = False, tts=None,
            duration: Callable[[Path], float] = _duration) -> dict:
    """Build the scenes that start before `upto_seconds` while images are still
    coming in. A missing still borrows the nearest earlier one in the video
    (or the next one, at the very start); the result lists which. Lives in
    <project>/manual_images/preview/ so the real workspace is untouched."""
    data = load_shotlist(project)
    clips = narrate(project, tts=tts, duration=duration)["clips"]
    timing = plan_timing(data, clips)
    keep = {s["id"] for s in timing["scenes"] if s["start"] < upto_seconds}
    scenes = [s for s in data["scenes"] if s["id"] in keep]
    order = [shot["id"] for scene in scenes for shot in scene["shots"]]
    have = {sid: find_image(project, sid) for sid in order}
    if not any(have.values()):
        raise RuntimeError("no images yet for this part of the video")

    sub = root(project) / "preview"
    if sub.exists():
        shutil.rmtree(sub)
    (sub / "manual_images" / "in").mkdir(parents=True)
    _write(sub / "manual_images" / "shotlist.json", {**data, "scenes": scenes})
    shutil.copytree(root(project) / "audio", sub / "manual_images" / "audio")
    borrowed = {}
    for i, sid in enumerate(order):
        src = have[sid]
        if not src:
            earlier = [have[o] for o in order[:i] if have[o]]
            src = earlier[-1] if earlier else next(have[o] for o in order[i + 1:] if have[o])
            borrowed[sid] = src.stem
        shutil.copy2(src, sub / "manual_images" / "in" / f"{sid}{src.suffix.lower()}")

    built = build_workspace(sub, narrate(sub, tts=tts, duration=duration)["clips"])
    out = {"scenes": [s["id"] for s in scenes], "seconds": built.get("duration"),
           "borrowed": borrowed, "warnings": built["warnings"]}
    if render_video:
        target = Path(project) / "renders" / f"preview_{int(upto_seconds)}s.mp4"
        out.update(render(sub, out=target))
    return out


def build(project: Path, *, render_video: bool = False, tts=None) -> dict:
    checked = check_images(project)
    if not checked["ready"]:
        bad = [r["id"] for r in checked["shots"]
               if any(p == "missing" or p.startswith("unreadable") for p in r["problems"])]
        raise RuntimeError("images missing or unreadable: " + ", ".join(bad))
    voice = narrate(project, tts=tts)
    built = build_workspace(project, voice["clips"])
    out = {"narration_cost_usd": voice["cost_usd"], **built,
           "pace": pace_report(load_shotlist(project), voice["clips"]),
           "warnings": [f"{r['id']}: {p}" for r in checked["shots"] for p in r["problems"]] + built["warnings"]}
    if render_video:
        out.update(render(project))
    return out


@dataclass
class Status:
    shots: int
    images: int
    missing: list

    def summary(self) -> str:
        return f"{self.images}/{self.shots} images" + (f"; missing: {', '.join(self.missing)}" if self.missing else "")


def status(project: Path) -> Status:
    data = load_shotlist(project)
    ids = [shot["id"] for _, shot in shots(data)]
    missing = [i for i in ids if not find_image(project, i)]
    return Status(len(ids), len(ids) - len(missing), missing)


def pace_report(data: dict, clips: dict) -> list[dict]:
    """Letters per second per scene, to spot rushed or dragging lines."""
    return [{"id": s["id"], "cps": chars_per_second(s.get("narration", ""), clips[s["id"]]["seconds"])}
            for s in data["scenes"] if s.get("narration")]
