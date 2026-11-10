"""Sample stream for the Archivist: voice every line, lay out a timeline,
draw overlays, render 1920x1080 with ffmpeg.

The timeline is what a live run would do with the test chat, played back to
back without the model and TTS latency (``turns.json`` keeps the measured
latencies for the report).
"""

from __future__ import annotations

import json
import math
import os
import subprocess
import time
import wave
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from lib import sfx_synth
from lib.archivist.brain import NOT_IN_ARCHIVE
from lib.archivist.cipher import ROUNDS, CipherGame, encode

FPS = 25
W, H = 1920, 1080
RATE = 48000
VOICE = "Algenib"
VOICE_STYLE = ("You are a kind old archivist, about seventy, reading secret files to a friend "
               "late at night in a quiet archive. Speak Persian slowly and warmly, low and a "
               "little gravelly, with small pauses, never dramatic or loud.")
GREEN = (31, 77, 58)
CREAM = (239, 230, 210)
INK = (38, 32, 26)
GOLD = (214, 170, 72)

FONT_DIR = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "Windows" / "Fonts"
COURIER = Path("C:/Windows/Fonts/courbd.ttf")

# Lines that are not model answers. Host lines carry no facts; the file
# reading is the MI6 script verbatim (already sourced).
INTRO = ("شب بخیر، مأمورها. بایگانی دوباره بازه. بیرون بارون میاد، و من این‌جا بین پرونده‌هام. "
         "سؤالتون رو توی چت بنویسید؛ اگه پرونده‌ش روی این قفسه‌ها باشه، براتون می‌خونمش.")
FILE_INTRO = "خب. وقتشه یه پرونده از قفسه بردارم. پرونده‌ی ام‌آی‌سیکس؛ جنگِ دوم."
FILE_PARAS = ("حالا جنگِ دوم", "بریتانیا یه عمارتِ قدیمی", "ولی بهترین مغزها", "شرط؟", "نتیجه؟ رمزِ انیگما")
FILE_OUTRO = "و حالا که حرفِ رمز شد… یه پرونده‌ی رمزدار هم رسیده."
CIPHER_ANNOUNCE = ("پرونده‌ی رمزدارِ این ساعت. شش حرف. رمزِ سزار: هر حرف، سه خونه جلوتر از الفبا نوشته شده. "
                   "اولین سه مأموری که جواب رو با علامتِ تعجب و کلمه‌ی کد بفرستن، امتیاز می‌گیرن.")
OUTRO = "پرونده‌ی رمزدارِ بعدی، یه ساعتِ دیگه. تا اون موقع، سؤال‌هاتون رو بفرستید. من همین‌جام."
SPOKEN_NAMES = {"Mina_H": "مینا"}

# Points from earlier rounds, so the board is not empty in the sample.
SEED_BOARD = {"nightowl_77": 7, "Sara_K": 5, "Arman.R": 4, "Mina_H": 3, "dr_watson": 2}


# -- voice ---------------------------------------------------------------

def file_text(repo: Path) -> str:
    paras = [p.strip() for p in (repo / "projects/mi6-history-fa/narration.txt")
             .read_text(encoding="utf-8").split("\n\n")]
    picked = [next(p for p in paras if p.startswith(start)) for start in FILE_PARAS]
    return " ".join(picked)


def lines(work: Path, repo: Path) -> list[dict]:
    """Every line the Archivist speaks in the sample, in order."""
    turns = json.loads((work / "turns.json").read_text(encoding="utf-8"))
    out = [{"id": "intro", "text": INTRO}]
    for i, t in enumerate(turns):
        if t["action"] == "answer":
            out.append({"id": f"answer{i + 1}", "text": t["answer"]})
    out.append({"id": "refusal", "text": NOT_IN_ARCHIVE})
    out.append({"id": "file", "text": FILE_INTRO + " " + file_text(repo)})
    out.append({"id": "file_outro", "text": FILE_OUTRO})
    out.append({"id": "cipher", "text": CIPHER_ANNOUNCE})
    winner = next((t for t in turns if t["action"] == "cipher"), None)
    name = SPOKEN_NAMES.get(winner["user"], "مأمور") if winner else "مأمور"
    out.append({"id": "winner", "text": f"{name}! جواب درسته: انیگما. سه امتیاز مالِ تو. "
                                        + ROUNDS[0]["reveal"]})
    out.append({"id": "outro", "text": OUTRO})
    return out


class GoogleRestTTS:
    """Gemini TTS on Google's native ``generateContent`` endpoint.

    Same request body as ``avalai_gemini_tts`` (voice + speechMetadata style).
    ``gemini_tts`` goes through the SDK's ``interactions`` endpoint, which hung
    for minutes from this laptop on 2026-11-10 while plain REST answered in
    seconds; AvalAI's credit was used up the same day.
    """

    URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

    def execute(self, inputs: dict):
        import base64

        import requests

        from tools.audio.avalai_gemini_tts import AvalAIGeminiTTS
        from tools.base_tool import ToolResult

        try:
            request = AvalAIGeminiTTS().build_request(inputs)
            response = requests.post(self.URL.format(model=request["model"]),
                                     headers={"x-goog-api-key": os.environ["GOOGLE_API_KEY"]},
                                     json=request["body"], timeout=180)
            if response.status_code != 200:
                raise ValueError(f"HTTP {response.status_code}: {response.text[:300]}")
            part = next(p["inlineData"] for c in response.json().get("candidates", [])
                        for p in c.get("content", {}).get("parts", []) if p.get("inlineData"))
            data = base64.b64decode(part["data"])
            path = Path(inputs["output_path"])
            if part.get("mimeType", "").startswith("audio/wav"):
                path.write_bytes(data)
            else:  # raw 16-bit PCM, 24 kHz mono
                with wave.open(str(path), "wb") as out:
                    out.setnchannels(1)
                    out.setsampwidth(2)
                    out.setframerate(24000)
                    out.writeframes(data)
            usage = response.json().get("usageMetadata", {})
            return ToolResult(success=True, data={"output": str(path), "usage": usage})
        except Exception as exc:  # noqa: BLE001 - reported per line
            return ToolResult(success=False, error=str(exc))


def voice_all(work: Path, force: bool = False, tts=None) -> dict:
    """One TTS call per line with the same voice and style (as live would)."""
    if tts is None:
        tts = GoogleRestTTS()
    repo = Path(__file__).resolve().parents[2]
    audio = work / "audio"
    audio.mkdir(parents=True, exist_ok=True)
    report = {}
    for line in lines(work, repo):
        path = audio / f"{line['id']}.wav"
        text_file = audio / f"{line['id']}.txt"
        if path.exists() and not force and text_file.exists() \
                and text_file.read_text(encoding="utf-8") == line["text"]:
            report[line["id"]] = {"cached": True}
        else:
            print(f"voicing {line['id']} ({len(line['text'].split())} words)", flush=True)
            t0 = time.time()
            res = None
            for _ in range(5):
                res = tts.execute({"text": line["text"], "voice_id": VOICE, "style": VOICE_STYLE,
                                   "output_path": str(path)})
                if res.success:
                    break
                if "429" in (res.error or ""):  # free-tier requests per minute
                    time.sleep(40)
            if not res.success:
                from tools.provider_routing import short_error

                report[line["id"]] = {"error": short_error(res.error)}
                continue
            text_file.write_text(line["text"], encoding="utf-8")
            report[line["id"]] = {"tts_seconds": round(time.time() - t0, 1),
                                  "usage": (res.data or {}).get("usage", {})}
        samples, rate = read_wav(path)
        report[line["id"]] = {**report.get(line["id"], {}),
                              "seconds": round(len(samples) / rate, 2),
                              "median_pitch_hz": median_pitch(samples, rate),
                              "words": len(line["text"].split())}
    (work / "voice_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return report


def read_wav(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path)) as w:
        rate, n, ch = w.getframerate(), w.getnframes(), w.getnchannels()
        data = np.frombuffer(w.readframes(n), "<i2").astype(np.float32) / 32768
    if ch > 1:
        data = data.reshape(-1, ch).mean(1)
    return data, rate


def median_pitch(x: np.ndarray, rate: int) -> float:
    """Median F0 over voiced 40 ms frames (autocorrelation, 70-300 Hz)."""
    n = int(0.04 * rate)
    lo, hi = int(rate / 300), int(rate / 70)
    f0 = []
    for i in range(0, len(x) - n, n):
        f = x[i:i + n] - x[i:i + n].mean()
        if np.sqrt((f ** 2).mean()) < 0.02:
            continue
        ac = np.correlate(f, f, "full")[n - 1:]
        lag = lo + int(np.argmax(ac[lo:hi]))
        if ac[lag] > 0.45 * ac[0]:
            f0.append(rate / lag)
    return round(float(np.median(f0)), 1) if f0 else 0.0


def resample(x: np.ndarray, rate: int, to: int = RATE) -> np.ndarray:
    if rate == to:
        return x
    t = np.arange(int(len(x) * to / rate)) / to
    return np.interp(t, np.arange(len(x)) / rate, x).astype(np.float32)


def mouth_track(x: np.ndarray, rate: int) -> np.ndarray:
    """Mouth shape per video frame (0 closed, 1 mid, 2 open) from loudness."""
    hop = rate // FPS
    frames = len(x) // hop + 1
    rms = np.array([np.sqrt((x[i * hop:(i + 1) * hop + hop // 2] ** 2).mean() + 1e-9) for i in range(frames)])
    ref = np.percentile(rms, 92) or 1.0
    level = rms / ref
    shape = np.where(level > 0.55, 2, np.where(level > 0.2, 1, 0))
    # No single-frame flickers: a shape holds at least two frames.
    for i in range(1, len(shape) - 1):
        if shape[i] != shape[i - 1] and shape[i] != shape[i + 1]:
            shape[i] = shape[i - 1]
    return shape


# -- text ------------------------------------------------------------------

@lru_cache(None)
def font(size: int, weight: str = "Medium", latin: bool = False) -> ImageFont.FreeTypeFont:
    if latin:
        return ImageFont.truetype(str(COURIER), size)
    return ImageFont.truetype(str(FONT_DIR / f"Vazirmatn-{weight}.ttf"), size)


def shape(text: str) -> str:
    import arabic_reshaper
    from bidi.algorithm import get_display

    return get_display(arabic_reshaper.reshape(text), base_dir="R")


def wrap(text: str, fnt, width: int) -> list[str]:
    words, rows, cur = text.split(), [], ""
    for word in words:
        trial = f"{cur} {word}".strip()
        if fnt.getlength(shape(trial)) <= width or not cur:
            cur = trial
        else:
            rows.append(cur)
            cur = word
    if cur:
        rows.append(cur)
    return rows


def rtl(draw: ImageDraw.ImageDraw, right: int, y: int, text: str, fnt, fill) -> int:
    s = shape(text)
    draw.text((right - fnt.getlength(s), y), s, font=fnt, fill=fill)
    return int(fnt.getlength(s))


# -- overlay pieces (RGBA images) -----------------------------------------

def panel(w: int, h: int, fill, radius: int = 18, border=None) -> Image.Image:
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, w - 1, h - 1), radius, fill=fill, outline=border, width=3 if border else 0)
    return img


def badge() -> Image.Image:
    img = panel(470, 64, (14, 18, 20, 200), 14)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((12, 12, 112, 52), 8, fill=(200, 32, 38, 255))
    d.text((28, 15), "LIVE", font=font(28, latin=True), fill="white")
    rtl(d, 452, 12, "SPOIL · بایگان", font(28, "Bold"), CREAM)
    return img


def chat_message(user: str, text: str, status: str = "", width: int = 540) -> Image.Image:
    body = font(26)
    rows = wrap(text, body, width - 40) if status != "removed" else []
    h = 48 + 38 * max(len(rows), 1) + (34 if status and status != "removed" else 0)
    bg = {"winner": (70, 56, 18, 225), "removed": (30, 30, 30, 170)}.get(status, (14, 20, 22, 205))
    img = panel(width, h, bg, 14, border=GOLD + (255,) if status == "winner" else None)
    d = ImageDraw.Draw(img)
    name_col = {"winner": GOLD, "removed": (130, 130, 130)}.get(status, (140, 205, 170))
    d.text((width - 20 - font(24, latin=True).getlength(user), 10), user, font=font(24, latin=True), fill=name_col)
    if status == "removed":
        rtl(d, width - 20, 46, "پیام حذف شد · فیلترِ بایگان", font(24), (150, 150, 150))
        return img
    for i, row in enumerate(rows):
        rtl(d, width - 20, 44 + 38 * i, row, body, CREAM)
    tag = {"answer": ("بایگان جواب می‌ده", (140, 205, 170)),
           "not_in_archive": ("خارج از بایگانی", (220, 160, 110)),
           "winner": ("جوابِ درست · ۳ امتیاز", GOLD)}.get(status)
    if tag:
        rtl(d, width - 20, 44 + 38 * len(rows), "◂ " + tag[0], font(22), tag[1])
    return img


def question_card(user: str, text: str) -> Image.Image:
    w = 1180
    body = font(34, "Medium")
    rows = wrap(text, body, w - 80)[:3]
    h = 84 + 52 * len(rows)
    img = panel(w, h, CREAM + (245,), 16, border=GREEN + (255,))
    d = ImageDraw.Draw(img)
    d.rectangle((w - 14, 10, w - 6, h - 10), fill=GREEN)
    label = shape("می‌پرسه:")
    lf = font(26, "Bold")
    x = w - 40 - lf.getlength(label)
    d.text((x, 16), label, font=lf, fill=GREEN)
    d.text((x - 12 - font(26, latin=True).getlength(user), 18), user, font=font(26, latin=True), fill=INK)
    for i, row in enumerate(rows):
        rtl(d, w - 40, 64 + 52 * i, row, body, INK)
    return img


def file_card(title_fa: str, typed: str, progress: float) -> Image.Image:
    w, h = 620, 150
    img = panel(w, h, (20, 30, 26, 225), 14, border=GREEN + (255,))
    d = ImageDraw.Draw(img)
    rtl(d, w - 24, 14, title_fa, font(30, "Bold"), CREAM)
    shown = typed[: int(len(typed) * progress)]
    d.text((24, 82), shown, font=font(34, latin=True), fill=(225, 205, 160))
    if progress < 1:
        x = 24 + font(34, latin=True).getlength(shown)
        d.rectangle((x + 2, 84, x + 20, 118), fill=(200, 40, 40))
    return img


def cipher_card(cipher: str, hint: str, typed: float, solved: str | None, remaining: float) -> Image.Image:
    w, h = 760, 300
    img = panel(w, h, (232, 219, 188, 248), 10, border=INK + (255,))
    d = ImageDraw.Draw(img)
    d.text((26, 18), "CODED FILE #07", font=font(30, latin=True), fill=(150, 30, 30))
    rtl(d, w - 26, 16, "پرونده‌ی رمزدار", font(30, "Bold"), INK)
    shown = cipher[: int(round(len(cipher) * typed))]
    big = font(92, latin=True)
    spaced = " ".join(shown)
    d.text(((w - big.getlength(" ".join(cipher))) / 2, 70), spaced, font=big, fill=INK)
    rtl(d, w - 26, 184, hint, font(25), (70, 60, 48))
    rtl(d, w - 26, 228, "جواب در چت:  !کد کلمه", font(25, "Bold"), GREEN)
    bar = int((w - 52) * max(0.0, min(1.0, remaining)))
    d.rectangle((26, h - 22, w - 26, h - 14), fill=(200, 188, 160))
    d.rectangle((26, h - 22, 26 + bar, h - 14), fill=GREEN)
    if solved:
        sf = font(46, latin=True)
        label = f"SOLVED: {solved}"
        sw = int(sf.getlength(label)) + 56
        stamp = Image.new("RGBA", (sw, 104), (0, 0, 0, 0))
        sd = ImageDraw.Draw(stamp)
        sd.rounded_rectangle((4, 4, sw - 4, 100), 12, outline=(190, 30, 30, 235), width=8)
        sd.text((28, 22), label, font=sf, fill=(190, 30, 30, 235))
        stamp = stamp.rotate(-7, expand=True, resample=Image.BICUBIC)
        img.alpha_composite(stamp, ((w - stamp.width) // 2, 52))
    return img


def leaderboard(rows: list[tuple[str, int]], highlight: str | None, pulse: float) -> Image.Image:
    w = 470
    h = 92 + 58 * len(rows)
    img = panel(w, h, GREEN + (232,), 16, border=(20, 50, 38, 255))
    d = ImageDraw.Draw(img)
    rtl(d, w - 24, 16, "جدولِ مأمورها", font(32, "Bold"), CREAM)
    for i, (name, pts) in enumerate(rows):
        y = 78 + 58 * i
        if name == highlight:
            a = int(90 + 120 * pulse)
            d.rounded_rectangle((12, y - 4, w - 12, y + 48), 10, fill=GOLD + (a,))
        d.text((w - 60, y + 2), f"{i + 1}", font=font(32, latin=True), fill=CREAM)
        d.text((w - 110 - font(30, latin=True).getlength(name), y + 4), name, font=font(30, latin=True), fill=CREAM)
        d.text((26, y + 4), f"{pts}", font=font(32, latin=True), fill=INK if name == highlight else GOLD)
    return img


def ticker() -> Image.Image:
    img = panel(1000, 54, (14, 18, 20, 190), 12)
    d = ImageDraw.Draw(img)
    rtl(d, 980, 8, "سؤالت رو درباره‌ی جاسوس‌ها بپرس  ·  هر ساعت یه پرونده‌ی رمزدار  ·  فقط از پرونده‌های منبع‌دار",
        font(24), CREAM)
    return img


def paste(frame: np.ndarray, rgba: Image.Image, x: int, y: int, alpha: float = 1.0) -> None:
    if alpha <= 0:
        return
    arr = np.asarray(rgba)
    h, w = arr.shape[:2]
    x0, y0 = max(x, 0), max(y, 0)
    x1, y1 = min(x + w, frame.shape[1]), min(y + h, frame.shape[0])
    if x1 <= x0 or y1 <= y0:
        return
    sub = arr[y0 - y:y1 - y, x0 - x:x1 - x]
    a = sub[..., 3:4].astype(np.float32) / 255 * alpha
    rgb = sub[..., 2::-1].astype(np.float32)  # RGBA -> BGR
    region = frame[y0:y1, x0:x1].astype(np.float32)
    frame[y0:y1, x0:x1] = (region * (1 - a) + rgb * a).astype(np.uint8)


def ease(x: float) -> float:
    x = max(0.0, min(1.0, x))
    return x * x * (3 - 2 * x)


# -- timeline ----------------------------------------------------------------

def build_timeline(work: Path) -> dict:
    turns = json.loads((work / "turns.json").read_text(encoding="utf-8"))
    audio = work / "audio"

    def clip(name):
        x, rate = read_wav(audio / f"{name}.wav")
        return resample(x, rate), mouth_track(x, rate)

    t = 0.0
    speech, events, chat = [], [], []

    def say(name, start, pose="desk"):
        x, mouth = clip(name)
        speech.append({"id": name, "start": start, "end": start + len(x) / RATE, "pose": pose,
                       "samples": x, "mouth": mouth})
        return start + len(x) / RATE

    events.append({"kind": "sfx", "name": "crackle", "at": 0.0})
    t = 5.0
    t = say("intro", t) + 1.5
    answer_no = 0
    for i, turn in enumerate(turns):
        if turn["action"] == "cipher":
            continue
        chat.append({"at": t, "user": turn["user"], "text": turn["text"], "status": "",
                     "turn": turn, "status_at": t + 1.2})
        events.append({"kind": "sfx", "name": "pop", "at": t})
        if turn["action"] == "answer":
            answer_no += 1
            chat[-1]["status"] = "answer"
            start = t + 1.4
            events.append({"kind": "question", "user": turn["user"], "text": turn["text"], "at": start - 0.4})
            events.append({"kind": "sfx", "name": "swish", "at": start - 0.4})
            end = say(f"answer{i + 1}", start + 0.6)
            events[-2]["end"] = end + 0.6
            t = end + 2.2
        elif turn["action"] == "not_in_archive":
            chat[-1]["status"] = "not_in_archive"
            end = say("refusal", t + 1.6)
            t = end + 1.4
        elif turn["action"] == "drop":
            # Shown as removed from the first frame: abuse never reaches the screen.
            chat[-1]["status"], chat[-1]["status_at"] = "removed", t
            t += 2.6
        else:
            t += 2.0
    # File reading: to the shelf, back with the file, read.
    events.append({"kind": "pose", "at": t, "seq": [("shelf_reach", 0.9, 1.8), ("file", 0.9, None)]})
    events.append({"kind": "sfx", "name": "swish", "at": t + 0.2})
    t += 0.9 + 1.8 + 0.9 + 0.4
    card = {"kind": "file_card", "at": t, "title": "پرونده‌ی ام‌آی‌سیکس · بلچلی پارک",
            "typed": "BLETCHLEY PARK, 1942"}
    events.append(card)
    events.append({"kind": "sfx", "name": "typing", "at": t + 0.3, "duration": 1.6})
    end = say("file", t + 0.3, pose="file")
    card["end"] = end + 0.3
    events.append({"kind": "pose_back", "at": end + 0.5, "dur": 0.9})
    t = end + 1.6
    t = say("file_outro", t) + 0.6
    # Cipher round.
    game = CipherGame(board=dict(SEED_BOARD))
    cipher = game.start(ROUNDS[0])
    events.append({"kind": "sfx", "name": "typing", "at": t + 0.2, "duration": 1.2})
    cipher_start = t
    end = say("cipher", t + 1.2)
    winner_turn = next(tt for tt in turns if tt["action"] == "cipher")
    guess_at = end + 3.0
    before = game.top(5)
    points = game.guess(winner_turn["user"], winner_turn["text"].split(maxsplit=1)[1])
    chat.append({"at": guess_at, "user": winner_turn["user"], "text": winner_turn["text"],
                 "status": "winner" if points else "", "status_at": guess_at + 0.8, "turn": winner_turn})
    events.append({"kind": "sfx", "name": "pop", "at": guess_at})
    events.append({"kind": "sfx", "name": "hit", "at": guess_at + 0.8})
    events.append({"kind": "cipher", "at": cipher_start, "cipher": cipher, "hint": ROUNDS[0]["hint"],
                   "solved_at": guess_at + 0.8, "solution": ROUNDS[0]["plain"], "end": None,
                   "window": (end - cipher_start + 4.0)})
    events.append({"kind": "board", "at": cipher_start + 0.8, "before": before, "after": game.top(5),
                   "update_at": guess_at + 1.2, "highlight": winner_turn["user"] if points else None})
    end = say("winner", guess_at + 1.8)
    t = end + 2.5
    events[-2]["end"] = t
    events[-1]["end"] = t + 1.0
    end = say("outro", t)
    total = end + 4.0
    return {"speech": speech, "events": events, "chat": chat, "total": total,
            "cipher": {"text": cipher, "points": points, "board": game.top(5)}}


def mix_audio(tl: dict, out: Path) -> Path:
    n = int(tl["total"] * RATE) + RATE
    voice = np.zeros(n, np.float32)
    for s in tl["speech"]:
        a = int(s["start"] * RATE)
        voice[a:a + len(s["samples"])] += s["samples"] * 0.9
    rng = np.random.default_rng(3)
    # Rain: brown-ish noise, low-passed, slowly breathing, plus sparse drips.
    noise = rng.standard_normal(n).astype(np.float32)
    rain = sfx_synth._lowpass(noise, 1800) * 0.5 + sfx_synth._lowpass(noise, 300) * 0.8
    rain = rain / (np.abs(rain).max() + 1e-9)
    env = 0.85 + 0.15 * np.sin(np.arange(n) / RATE * 2 * np.pi / 11)
    bed = rain * env * 0.055
    drip = sfx_synth.pop(0.05, seed=9)[: int(0.05 * RATE)] * 0.05
    for at in rng.uniform(0, tl["total"], int(tl["total"] * 0.8)):
        a = int(at * RATE)
        bed[a:a + len(drip)] += drip[: n - a]
    sfx = np.zeros(n, np.float32)
    levels = {"pop": 0.18, "swish": 0.12, "typing": 0.16, "hit": 0.22, "crackle": 0.05}
    for e in tl["events"]:
        if e["kind"] != "sfx":
            continue
        kwargs = {"duration": e["duration"]} if "duration" in e else {}
        if e["name"] == "crackle":
            kwargs = {"duration": tl["total"]}
        x = sfx_synth.SYNTHS[e["name"]](**kwargs).astype(np.float32) * levels[e["name"]]
        a = int(e["at"] * RATE)
        sfx[a:a + len(x)] += x[: n - a]
    # Duck the bed a little under speech.
    speaking = np.convolve((np.abs(voice) > 0.01).astype(np.float32), np.ones(4800) / 4800, "same")
    mix = voice + bed * (1 - 0.35 * np.clip(speaking * 3, 0, 1)) + sfx
    sfx_synth.write_wav(out, mix / max(1.0, np.abs(mix).max() / 0.95), RATE)
    return out


class Overlays:
    def __init__(self, tl: dict):
        self.tl = tl
        self.cache: dict = {}
        self.badge = badge()
        self.ticker = ticker()

    def get(self, key, make):
        if key not in self.cache:
            if len(self.cache) > 400:
                self.cache.clear()
            self.cache[key] = make()
        return self.cache[key]

    def draw(self, frame: np.ndarray, t: float) -> None:
        paste(frame, self.badge, 40, 34)
        paste(frame, self.ticker, (W - 1000) // 2, H - 76, 0.9)
        self.draw_chat(frame, t)
        for e in self.tl["events"]:
            if e["kind"] in ("sfx", "pose", "pose_back") or t < e["at"]:
                continue
            end = e.get("end") or self.tl["total"]
            if t > end + 0.5:
                continue
            a = ease((t - e["at"]) / 0.4) * (1 - ease((t - end) / 0.5))
            if e["kind"] == "question":
                img = self.get(("q", e["user"], e["text"]), lambda: question_card(e["user"], e["text"]))
                slide = int(30 * (1 - ease((t - e["at"]) / 0.4)))
                paste(frame, img, (W - img.width) // 2 + 120, H - 110 - img.height + slide, a)
            elif e["kind"] == "file_card":
                prog = min(1.0, (t - e["at"] - 0.3) / 1.6)
                step = round(max(prog, 0) * 40) / 40
                img = self.get(("f", step), lambda: file_card(e["title"], e["typed"], step))
                paste(frame, img, 40, 120, a)
            elif e["kind"] == "cipher":
                typed = round(min(1.0, max(0.0, (t - e["at"] - 0.2) / 1.2)) * 6) / 6
                solved = e["solution"] if t >= e["solved_at"] else None
                rem = 1.0 if solved else 1 - (t - e["at"]) / e["window"]
                rem = round(rem * 60) / 60
                img = self.get(("c", typed, solved, rem),
                               lambda: cipher_card(e["cipher"], e["hint"], typed, solved, rem))
                paste(frame, img, 640, H - 110 - img.height, a)
            elif e["kind"] == "board":
                updated = t >= e["update_at"]
                rows = e["after"] if updated else e["before"]
                pulse = round(0.5 + 0.5 * math.sin((t - e["update_at"]) * 6), 1) if updated else 0
                hl = e["highlight"] if updated else None
                img = self.get(("b", updated, pulse), lambda: leaderboard(rows, hl, pulse))
                paste(frame, img, W - img.width - 40, 120, a)

    def draw_chat(self, frame: np.ndarray, t: float) -> None:
        shown = [m for m in self.tl["chat"] if m["at"] <= t][-5:]
        if not shown:
            return
        header = self.get("chat_header", lambda: self._header())
        y = 760
        imgs = []
        for m in reversed(shown):
            status = m["status"] if t >= m["status_at"] else ""
            img = self.get(("m", m["user"], m["text"], status),
                           lambda: chat_message(m["user"], m["text"], status))
            imgs.append((m, img))
        for m, img in imgs:
            y -= img.height + 10
            if y < 190:
                break
            a = ease((t - m["at"]) / 0.3)
            paste(frame, img, 40 - int(20 * (1 - a)), y, a)
        paste(frame, header, 40, max(y - 56, 120) if y >= 190 else 120, 0.95)

    @staticmethod
    def _header() -> Image.Image:
        img = panel(540, 46, (14, 18, 20, 190), 12)
        rtl(ImageDraw.Draw(img), 520, 6, "چتِ زنده", font(26, "Bold"), CREAM)
        return img


def pose_at(tl: dict, t: float) -> tuple[str, str | None, float]:
    """(pose, still, mix) for the file pull and the way back."""
    pose, still, mix = "desk", None, 0.0
    for e in tl["events"]:
        if e["kind"] == "pose" and t >= e["at"]:
            (s1, f1, h1), (s2, f2, _) = e["seq"]
            dt = t - e["at"]
            if dt < f1:
                pose, still, mix = "desk", s1, ease(dt / f1)
            elif dt < f1 + h1:
                pose, still, mix = "desk", s1, 1.0
            elif dt < f1 + h1 + f2:
                pose, still, mix = s2, s1, 1 - ease((dt - f1 - h1) / f2)
            else:
                pose, still, mix = s2, None, 0.0
        if e["kind"] == "pose_back" and t >= e["at"]:
            dt = t - e["at"]
            if dt < e["dur"]:
                pose, still, mix = "file", "desk", ease(dt / e["dur"])
            else:
                pose, still, mix = "desk", None, 0.0
    return pose, still, mix


def render_sample(work: Path, seconds: float = 0) -> dict:
    from lib.archivist.rig import Rig, camera

    tl = build_timeline(work)
    total = seconds or tl["total"]
    wav = mix_audio(tl, work / "sample_mix.wav")
    rig = Rig(work / "stills")
    over = Overlays(tl)
    renders = work / "renders"
    renders.mkdir(exist_ok=True)
    out = renders / ("archivist_sample.mp4" if not seconds else f"archivist_first{int(seconds)}s.mp4")
    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}",
           "-r", str(FPS), "-i", "-", "-i", str(wav), "-t", f"{total:.2f}",
           "-af", "loudnorm=I=-14:TP=-1:LRA=11", "-ar", "48000",
           "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    rng = np.random.default_rng(11)
    blinks = np.cumsum(rng.uniform(2.6, 5.5, 200))
    page_turns = np.arange(9.0, total, 17.0)
    for i in range(int(total * FPS)):
        t = i / FPS
        pose, still, mix = pose_at(tl, t)
        mouth, nod, talking = 0, 0.0, False
        for s in tl["speech"]:
            if s["start"] <= t < s["end"]:
                k = int((t - s["start"]) * FPS)
                mouth = int(s["mouth"][min(k, len(s["mouth"]) - 1)])
                nod = 1.6 * math.sin(t * 2.3) if mouth else 0.0
                talking = True
                break
        blink = bool(np.any((t >= blinks) & (t < blinks + 0.14)))
        if not talking and not still and pose == "desk":
            # Idle page turn: a short cross-fade to the page-turn still.
            for p in page_turns:
                if p <= t < p + 1.4:
                    still, mix = "page_turn", math.sin(math.pi * (t - p) / 1.4)
                    blink = False
        img = rig.frame(t, pose=pose, mouth=mouth if pose in rig.poses else 0, blink=blink,
                        still=still, mix=mix, nod=nod)
        zoom = 1.0 + (0.05 if talking and not still else 0.0)
        cur = getattr(render_sample, "_zoom", 1.0)
        cur += (zoom - cur) * 0.02
        render_sample._zoom = cur
        frame = camera(img, cur, 0.5, 0.42)
        over.draw(frame, t)
        if t > total - 1.5:
            frame = (frame * max(0.0, (total - t) / 1.5)).astype(np.uint8)
        if t < 1.0:
            frame = (frame * t).astype(np.uint8)
        proc.stdin.write(frame.tobytes())
    proc.stdin.close()
    proc.wait()
    sheet = contact_sheet(out, renders / out.name.replace(".mp4", "_sheet.jpg"))
    return {"video": str(out), "sheet": str(sheet), "seconds": round(total, 1),
            "speech": [{k: s[k] for k in ("id", "start", "end")} for s in tl["speech"]],
            "cipher": tl["cipher"]}


def contact_sheet(video: Path, out: Path, cols: int = 4, rows: int = 4) -> Path:
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
                                "csv=p=0", str(video)], capture_output=True, text=True).stdout.strip())
    n = cols * rows
    fps = n / dur
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(video), "-vf",
                    f"fps={fps:.5f},scale=480:-1,tile={cols}x{rows}", "-frames:v", "1", str(out)], check=True)
    return out
