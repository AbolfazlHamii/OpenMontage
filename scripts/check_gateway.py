#!/usr/bin/env python3
"""Check what an OpenAI-compatible gateway (AvalAI, GapGPT, ...) can do for
OpenMontage before a production depends on it.

Standard library only. Reads OPENAI_BASE_URL / OPENAI_API_KEY from the
environment or from OpenMontage's .env, then:

  1. lists the gateway's models and picks out speech, transcription, image
     and chat models;
  2. synthesizes a Persian test sentence with each speech model (/audio/speech);
  3. transcribes each result back (/audio/transcriptions, language=fa) and
     scores how close it is to the original text, a rough pronunciation check;
  4. optionally (--image, costs credit) generates one image (/images/generations).

Usage:
  python scripts/check_gateway.py
  python scripts/check_gateway.py --base-url https://api.gapgpt.app/v1 --image
  python scripts/check_gateway.py --tts-models gpt-4o-mini-tts tts-1 --voices alloy nova

Outputs go to gateway_check/ (audio, image, report.json).
"""

from __future__ import annotations

import argparse
import base64
import difflib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

SAMPLE_FA = (
    "اپل توی سال هزار و نهصد و هفتاد و شش، توی یه گاراژ کوچیک شروع شد؛ "
    "استیو جابز و استیو وازنیاک فقط هزار و سیصد دلار پول داشتن."
)
# Transcribers usually write numbers as digits; score against both forms.
SAMPLE_FA_DIGITS = (
    "اپل توی سال ۱۹۷۶، توی یه گاراژ کوچیک شروع شد؛ "
    "استیو جابز و استیو وازنیاک فقط ۱۳۰۰ دلار پول داشتن."
)
TTS_HINTS = ("tts", "speech", "eleven", "voice")
STT_HINTS = ("whisper", "transcribe", "stt")
IMAGE_HINTS = ("image", "dall-e", "imagen", "flux", "banana", "seedream", "recraft")
CHAT_HINTS = ("claude", "gemini", "gpt-4", "gpt-5", "qwen", "deepseek", "llama")


# ---------------------------------------------------------------- helpers ---

def load_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        values[key.strip()] = val.strip().strip('"').strip("'")
    return values


class Gateway:
    def __init__(self, base_url: str, api_key: str, timeout: float = 120):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def _request(self, method: str, path: str, body: bytes | None = None,
                 content_type: str | None = None) -> tuple[int, bytes, dict]:
        req = urllib.request.Request(self.base_url + path, data=body, method=method)
        req.add_header("Authorization", f"Bearer {self.api_key}")
        req.add_header("User-Agent", "openmontage-gateway-check/1.0")
        if content_type:
            req.add_header("Content-Type", content_type)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return resp.status, resp.read(), dict(resp.headers)
        except urllib.error.HTTPError as err:
            return err.code, err.read(), dict(err.headers or {})
        except (urllib.error.URLError, TimeoutError, OSError) as err:
            reason = getattr(err, "reason", err)
            return 0, json.dumps({"error": {"message": str(reason)}}).encode(), {}

    def get_json(self, path: str):
        status, raw, _ = self._request("GET", path)
        return status, _decode(raw)

    def post_json(self, path: str, payload: dict):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        return self._request("POST", path, data, "application/json")

    def post_multipart(self, path: str, fields: dict[str, str], file_field: str,
                       file_path: Path):
        boundary = uuid.uuid4().hex
        parts: list[bytes] = []
        for name, value in fields.items():
            parts.append(
                f"--{boundary}\r\nContent-Disposition: form-data; "
                f'name="{name}"\r\n\r\n{value}\r\n'.encode("utf-8")
            )
        parts.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{file_field}\"; "
            f'filename="{file_path.name}"\r\nContent-Type: application/octet-stream\r\n\r\n'
            .encode("utf-8")
        )
        parts.append(file_path.read_bytes())
        parts.append(f"\r\n--{boundary}--\r\n".encode("utf-8"))
        return self._request("POST", path, b"".join(parts),
                             f"multipart/form-data; boundary={boundary}")


def _decode(raw: bytes):
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return raw[:300].decode("utf-8", "replace")


def error_text(status: int, raw: bytes | dict | str) -> str:
    body = raw if isinstance(raw, (dict, str)) else _decode(raw)
    if isinstance(body, dict):
        err = body.get("error", body)
        if isinstance(err, dict):
            body = err.get("message") or err.get("code") or json.dumps(err, ensure_ascii=False)
        else:
            body = str(err)
    hint = {
        0: "could not reach the gateway: check the URL, DNS, VPN/proxy settings",
        401: "key rejected (wrong key, or key belongs to a different gateway)",
        402: "out of credit",
        403: "key lacks access to this model/endpoint",
        404: "endpoint or model not offered by this gateway",
        429: "rate limited or out of credit",
    }.get(status, "")
    label = "network error" if status == 0 else f"HTTP {status}"
    return f"{label}: {str(body)[:200]}" + (f"  [{hint}]" if hint else "")


def normalize_fa(text: str) -> str:
    table = str.maketrans({"ي": "ی", "ى": "ی", "ك": "ک", "‌": " ", "ـ": ""})
    text = text.translate(table)
    text = text.translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789"))
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def audio_duration(path: Path) -> float | None:
    if not shutil.which("ffprobe"):
        return None
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(path)],
            capture_output=True, text=True, timeout=30,
        )
        return round(float(out.stdout.strip()), 2)
    except (ValueError, subprocess.SubprocessError):
        return None


def pick(models: list[str], hints: tuple[str, ...]) -> list[str]:
    return [m for m in models if any(h in m.lower() for h in hints)]


# ------------------------------------------------------------------ steps ---

def step_models(gw: Gateway, report: dict) -> list[str]:
    print("\n[1] Models")
    status, body = gw.get_json("/models")
    if status != 200 or not isinstance(body, dict):
        msg = error_text(status, body)
        print("   ✗", msg)
        report["models"] = {"ok": False, "status": status, "error": msg}
        return []
    ids = sorted({str(m.get("id")) for m in body.get("data", []) if isinstance(m, dict)})
    groups = {
        "speech": pick(ids, TTS_HINTS),
        "transcription": pick(ids, STT_HINTS),
        "image": pick(ids, IMAGE_HINTS),
        "chat_examples": [
            m for m in pick(ids, CHAT_HINTS)
            if m not in pick(ids, TTS_HINTS + STT_HINTS + IMAGE_HINTS)
        ][:25],
    }
    report["models"] = {"ok": True, "count": len(ids), **groups}
    print(f"   ✓ {len(ids)} models")
    for name, items in groups.items():
        print(f"   {name:14}: {', '.join(items[:15]) or '—'}"
              + (" …" if len(items) > 15 else ""))
    return ids


def step_tts(gw: Gateway, models: list[str], voices: list[str], out_dir: Path,
             report: dict) -> list[Path]:
    print("\n[2] Persian speech (/audio/speech)")
    made: list[Path] = []
    report["tts"] = []
    for model in models:
        for voice in voices:
            payload = {"model": model, "voice": voice, "input": SAMPLE_FA,
                       "response_format": "mp3"}
            if model.startswith("gpt-4o-mini-tts"):
                payload["instructions"] = (
                    "Speak natural, conversational Iranian Persian with a Tehrani "
                    "accent, like an energetic YouTube storyteller."
                )
            t0 = time.time()
            status, raw, headers = gw.post_json("/audio/speech", payload)
            took = round(time.time() - t0, 1)
            ctype = headers.get("Content-Type", headers.get("content-type", ""))
            entry = {"model": model, "voice": voice, "seconds": took}
            if status == 200 and raw and "json" not in ctype:
                path = out_dir / f"tts_{model}_{voice}.mp3".replace("/", "_")
                path.write_bytes(raw)
                entry.update(ok=True, file=str(path), bytes=len(raw),
                             duration=audio_duration(path))
                made.append(path)
                print(f"   ✓ {model} / {voice}: {len(raw)//1024} KB"
                      f", {entry['duration'] or '?'} s audio, {took} s → {path.name}")
            else:
                msg = error_text(status, raw)
                entry.update(ok=False, error=msg)
                print(f"   ✗ {model} / {voice}: {msg}")
            report["tts"].append(entry)
    return made


def step_roundtrip(gw: Gateway, stt_model: str, files: list[Path], report: dict):
    print(f"\n[3] Round trip: transcribe the speech back with {stt_model}")
    report["roundtrip"] = []
    references = [normalize_fa(SAMPLE_FA), normalize_fa(SAMPLE_FA_DIGITS)]
    for path in files:
        status, raw, _ = gw.post_multipart(
            "/audio/transcriptions",
            {"model": stt_model, "language": "fa", "response_format": "json"},
            "file", path,
        )
        body = _decode(raw)
        if status == 200 and isinstance(body, dict) and "text" in body:
            heard = body["text"]
            score = max(
                difflib.SequenceMatcher(None, ref, normalize_fa(heard)).ratio()
                for ref in references
            )
            verdict = "good" if score >= 0.85 else "check by ear" if score >= 0.65 else "poor"
            report["roundtrip"].append({"file": path.name, "ok": True,
                                        "similarity": round(score, 3),
                                        "verdict": verdict, "heard": heard})
            print(f"   {path.name}: {score:.0%} match ({verdict})")
            print(f"      heard: {heard}")
        else:
            msg = error_text(status, body)
            report["roundtrip"].append({"file": path.name, "ok": False, "error": msg})
            print(f"   ✗ {path.name}: {msg}")
            if status in (400, 404):
                break  # transcription not offered; no point repeating


def step_image(gw: Gateway, model: str, out_dir: Path, report: dict):
    print(f"\n[4] Image (/images/generations, {model})")
    payload = {
        "model": model,
        "prompt": ("Flat 2D cartoon illustration, two young engineers building "
                   "the first personal computer in a cluttered 1970s garage, "
                   "warm colors, clean outlines, no text"),
        "size": "1024x1024",
        "n": 1,
    }
    t0 = time.time()
    status, raw, _ = gw.post_json("/images/generations", payload)
    took = round(time.time() - t0, 1)
    body = _decode(raw)
    if status == 200 and isinstance(body, dict) and body.get("data"):
        item = body["data"][0]
        path = out_dir / f"image_{model}.png".replace("/", "_")
        if item.get("b64_json"):
            path.write_bytes(base64.b64decode(item["b64_json"]))
            print(f"   ✓ saved {path.name} ({took} s)")
            report["image"] = {"ok": True, "model": model, "file": str(path), "seconds": took}
        elif item.get("url"):
            print(f"   ✓ URL returned ({took} s): {item['url']}")
            report["image"] = {"ok": True, "model": model, "url": item["url"], "seconds": took}
        else:
            report["image"] = {"ok": False, "model": model, "error": "empty data item"}
            print("   ✗ response had no b64_json or url")
    else:
        msg = error_text(status, body)
        report["image"] = {"ok": False, "model": model, "error": msg}
        print("   ✗", msg)


# ------------------------------------------------------------------- main ---

def main() -> int:
    repo = Path(__file__).resolve().parent.parent
    env = {**load_dotenv(repo / ".env"), **os.environ}

    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--base-url", default=env.get("OPENAI_BASE_URL") or "")
    ap.add_argument("--api-key", default=env.get("OPENAI_API_KEY") or "")
    ap.add_argument("--tts-models", nargs="*", default=None,
                    help="speech models to try (default: what the gateway lists, "
                         "else gpt-4o-mini-tts and tts-1)")
    ap.add_argument("--voices", nargs="*", default=["alloy", "nova"])
    ap.add_argument("--stt-model", default=None,
                    help="transcription model for the round trip (default: auto)")
    ap.add_argument("--image", action="store_true", help="also test image generation (costs credit)")
    ap.add_argument("--image-model", default="gpt-image-2")
    ap.add_argument("--out", default="gateway_check")
    args = ap.parse_args()

    if not args.base_url or not args.api_key:
        print("Set OPENAI_BASE_URL and OPENAI_API_KEY (in .env or the environment),\n"
              "or pass --base-url and --api-key.")
        return 2

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    gw = Gateway(args.base_url, args.api_key)
    report: dict = {"base_url": gw.base_url, "sample_text": SAMPLE_FA}
    print(f"Gateway: {gw.base_url}")

    listed = step_models(gw, report)
    if report["models"].get("status") in (0, 401):
        what = "the connection" if report["models"]["status"] == 0 else "the API key"
        print(f"\nStopping: fix {what} first (every other call would fail the same way).")
        return 1
    speech_listed = [m for m in pick(listed, TTS_HINTS) if "realtime" not in m]
    tts_models = args.tts_models or speech_listed[:4] or ["gpt-4o-mini-tts", "tts-1"]
    files = step_tts(gw, tts_models, args.voices, out_dir, report)

    stt = args.stt_model
    if not stt:
        candidates = pick(listed, STT_HINTS)
        preferred = [m for m in ("gpt-4o-transcribe", "gpt-4o-mini-transcribe", "whisper-1")
                     if m in candidates]
        stt = (preferred or candidates or ["whisper-1"])[0]
    if files:
        step_roundtrip(gw, stt, files, report)

    if args.image:
        step_image(gw, args.image_model, out_dir, report)

    (out_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nReport: {out_dir / 'report.json'}")
    print("Listen to the mp3 files yourself; the round-trip score catches "
          "mispronunciation, not a robotic tone.")
    tts_ok = any(e.get("ok") for e in report.get("tts", []))
    return 0 if tts_ok else 1


if __name__ == "__main__":
    sys.exit(main())
