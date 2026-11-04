"""Fit dubbed lines into the source timing.

Persian runs longer than English, so a translated line often comes back
longer than the slot it replaces. The loop, per segment:

1. Budget the text before synthesis: max_chars = slot seconds x voice cps.
2. Synthesize and measure.
3. Up to 1.08x the slot: speed it up with atempo (inaudible at that rate).
4. Longer: ask for a shorter rewrite, at most twice.
5. Still long: borrow the silence before the next segment.
6. Otherwise flag the line for the owner; it is placed at 1.08x and the
   overlap is reported.

synthesize(text) -> (audio_path, seconds) and rewrite(text, max_chars,
attempt) -> shorter text are passed in, so the loop is the same for TTS
lines, for recorded voice-actor takes (no rewrite) and in tests.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Callable, Optional

from lib.fa_text import chars_per_second, normalize

MAX_STRETCH = 1.08
MAX_REWRITES = 2
OVERLAP_TOLERANCE = 0.200  # seconds a line may run into the next one


@dataclass
class Segment:
    id: str
    start: float
    end: float
    text: str
    speaker: str = "speaker_1"
    source_text: str = ""
    style: str = ""

    @property
    def slot(self) -> float:
        return max(0.0, self.end - self.start)


@dataclass
class Fit:
    id: str
    speaker: str
    text: str
    audio_path: str
    raw_seconds: float
    tempo: float
    start: float
    end: float
    status: str  # ok | stretched | rewritten | used_gap | flagged
    rewrites: int = 0
    texts_tried: list[str] = field(default_factory=list)
    overlap_seconds: float = 0.0
    review_required: bool = False

    @property
    def placed_seconds(self) -> float:
        return self.raw_seconds / self.tempo

    def to_dict(self) -> dict:
        return asdict(self)


def spoken_chars(text: str) -> int:
    return sum(1 for ch in normalize(text) if not ch.isspace())


def char_budget(seconds: float, cps: float) -> int:
    return max(1, math.floor(seconds * cps))


def tempo_for(raw: float, room: float) -> float:
    """atempo factor to fit `raw` seconds into `room`; 1.0 when it already fits."""
    if room <= 0:
        return MAX_STRETCH
    return round(max(1.0, raw / room), 4)


def fit_segment(
    segment: Segment,
    synthesize: Callable[[str], tuple[str, float]],
    rewrite: Optional[Callable[[str, int, int], str]],
    cps: float,
    next_start: Optional[float] = None,
    max_rewrites: int = MAX_REWRITES,
) -> Fit:
    slot = segment.slot
    budget = char_budget(slot, cps)
    text = segment.text
    tried = [text]
    rewrites = 0

    # Rewrite before paying for audio when the text is clearly too long.
    while rewrite and rewrites < max_rewrites and spoken_chars(text) > budget * MAX_STRETCH:
        rewrites += 1
        text = rewrite(text, budget, rewrites)
        tried.append(text)

    while True:
        path, raw = synthesize(text)
        if raw <= slot * MAX_STRETCH:
            tempo = tempo_for(raw, slot)
            status = "rewritten" if rewrites else ("stretched" if tempo > 1.0 else "ok")
            return _fit(segment, text, path, raw, tempo, status, rewrites, tried)
        if not rewrite or rewrites >= max_rewrites:
            break
        rewrites += 1
        # Aim at what this voice actually managed, not the nominal cps.
        measured_cps = chars_per_second(text, raw) or cps
        text = rewrite(text, char_budget(slot, measured_cps), rewrites)
        tried.append(text)

    gap = max(0.0, (next_start - segment.end)) if next_start is not None else 0.0
    room = slot + gap
    if gap and raw <= room * MAX_STRETCH:
        return _fit(segment, text, path, raw, tempo_for(raw, room), "used_gap", rewrites, tried)

    fit = _fit(segment, text, path, raw, MAX_STRETCH, "flagged", rewrites, tried)
    fit.overlap_seconds = round(fit.end - (next_start if next_start is not None else segment.end), 3)
    return fit


def _fit(segment, text, path, raw, tempo, status, rewrites, tried) -> Fit:
    placed = raw / tempo
    return Fit(
        id=segment.id,
        speaker=segment.speaker,
        text=text,
        audio_path=path,
        raw_seconds=round(raw, 3),
        tempo=tempo,
        start=segment.start,
        end=round(segment.start + placed, 3),
        status=status,
        rewrites=rewrites,
        texts_tried=tried,
        # A rewritten line is final Persian from a cheaper model: the agent
        # (premium tier) reviews it before the mix.
        review_required=rewrites > 0,
    )


def fit_all(segments: list[Segment], synthesize_for: Callable[[Segment], Callable[[str], tuple[str, float]]],
            rewrite: Optional[Callable[[str, int, int], str]], cps_for: Callable[[Segment], float]) -> list[Fit]:
    ordered = sorted(segments, key=lambda s: s.start)
    fits = []
    for i, seg in enumerate(ordered):
        next_start = ordered[i + 1].start if i + 1 < len(ordered) else None
        fits.append(fit_segment(seg, synthesize_for(seg), rewrite, cps_for(seg), next_start))
    return fits


def overlaps(fits: list[Fit], tolerance: float = OVERLAP_TOLERANCE) -> list[dict]:
    """Lines that run more than `tolerance` into the next line."""
    ordered = sorted(fits, key=lambda f: f.start)
    found = []
    for current, following in zip(ordered, ordered[1:]):
        over = current.end - following.start
        if over > tolerance:
            found.append({"id": current.id, "next": following.id, "overlap_seconds": round(over, 3)})
    return found
