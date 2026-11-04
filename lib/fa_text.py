"""Persian text helpers for TTS checks: normalization, numbers as words, CER.

The round-trip check transcribes a voice sample and compares it with the
script. Persian has several spellings of the same thing that a transcriber
mixes freely (Arabic yeh/kaf, ZWNJ or space or nothing in «می‌شه», Persian,
Arabic or ASCII digits, «۱۹۹۵» or «هزار و نهصد و نود و پنج»), so both sides
are normalized first and the score is taken against two references: numbers
as words and numbers as digits.
"""

from __future__ import annotations

import re

ZWNJ = "‌"

_CHAR_MAP = str.maketrans({
    "ي": "ی", "ى": "ی", "ئ": "ی",
    "ك": "ک",
    "ة": "ه", "ۀ": "ه",
    "أ": "ا", "إ": "ا", "ٱ": "ا", "آ": "ا",
    "ؤ": "و",
    **{chr(0x06F0 + i): str(i) for i in range(10)},  # Persian digits
    **{chr(0x0660 + i): str(i) for i in range(10)},  # Arabic-Indic digits
})
_DIACRITICS = re.compile(r"[ً-ٰٟـ]")  # harakat, superscript alef, tatweel
_PUNCT = re.compile(r"[^\w\s]|_", re.UNICODE)
_DIGIT_RUN = re.compile(r"\d+")
# A digit run that may contain thousands separators: 150,000 or ۱۵۰٬۰۰۰.
_GROUPED_NUMBER = re.compile(r"\d{1,3}(?:[,٬]\d{3})+")

_ONES = ["", "یک", "دو", "سه", "چهار", "پنج", "شش", "هفت", "هشت", "نه"]
_TEENS = ["ده", "یازده", "دوازده", "سیزده", "چهارده", "پانزده", "شانزده",
          "هفده", "هجده", "نوزده"]
_TENS = ["", "", "بیست", "سی", "چهل", "پنجاه", "شصت", "هفتاد", "هشتاد", "نود"]
_HUNDREDS = ["", "صد", "دویست", "سیصد", "چهارصد", "پانصد", "ششصد", "هفتصد",
             "هشتصد", "نهصد"]
_SCALES = ["", "هزار", "میلیون", "میلیارد", "تریلیون"]


def to_ascii_digits(text: str) -> str:
    return text.translate({**{0x06F0 + i: str(i) for i in range(10)},
                           **{0x0660 + i: str(i) for i in range(10)}})


def _below_thousand(n: int) -> list[str]:
    parts = []
    if n >= 100:
        parts.append(_HUNDREDS[n // 100])
        n %= 100
    if 10 <= n < 20:
        parts.append(_TEENS[n - 10])
    else:
        if n >= 20:
            parts.append(_TENS[n // 10])
        if n % 10:
            parts.append(_ONES[n % 10])
    return parts


def number_to_words(n: int) -> str:
    """Spell a non-negative integer in Persian: 1995 -> هزار و نهصد و نود و پنج."""
    if n < 0:
        return "منفی " + number_to_words(-n)
    if n == 0:
        return "صفر"
    groups = []
    while n:
        groups.append(n % 1000)
        n //= 1000
    if len(groups) > len(_SCALES):
        raise ValueError("number too large to spell")
    words = []
    for scale in range(len(groups) - 1, -1, -1):
        value = groups[scale]
        if not value:
            continue
        if scale == 1 and value == 1:
            # «هزار», not «یک هزار», as people say it.
            words.append(_SCALES[1])
            continue
        chunk = " و ".join(_below_thousand(value))
        words.append(f"{chunk} {_SCALES[scale]}".strip())
    return " و ".join(words)


def spell_numbers(text: str) -> str:
    """Replace every digit run (any script, with or without separators) by words."""
    text = to_ascii_digits(text)
    text = _GROUPED_NUMBER.sub(lambda m: re.sub(r"[,٬]", "", m.group()), text)
    return _DIGIT_RUN.sub(lambda m: number_to_words(int(m.group())), text)


def normalize(text: str) -> str:
    """Comparable form: one spelling per letter, ASCII digits, no punctuation,
    ZWNJ and spaces collapsed to single spaces."""
    text = _DIACRITICS.sub("", text.translate(_CHAR_MAP))
    text = text.replace(ZWNJ, " ")
    text = _PUNCT.sub(" ", text)
    return " ".join(text.lower().split())


# Transcribers write spoken Tehrani in written form («جوون» → «جوان»). The
# script is spoken on purpose, so these are not pronunciation errors.
SPOKEN_FORMS = {
    "جوون": "جوان",
    "کوچیک": "کوچک",
    "میشه": "می شه",
    "فکرشم": "فکرش هم",
    "خونه": "خانه",
    "اینجوری": "این جوری",
    "همشون": "همه شون",
    "صب": "صبر",
}


def canonical_words(text: str) -> list[str]:
    """Normalized words with spoken/written variants folded together: known
    spoken forms, the ezafe «ی» after «ه» («مغازه‌ی»), and a detached
    possessive «ش» / «اش» («گوشی‌ش», «سرمایه‌اش»)."""
    words: list[str] = []
    for token in normalize(text).split():
        for word in SPOKEN_FORMS.get(token, token).split():
            if word == "ی" and words and words[-1].endswith("ه"):
                continue
            if word in ("ش", "اش") and words:
                words[-1] += "ش"
                continue
            words.append(word)
    return words


def _levenshtein(a: str, b: str) -> int:
    if len(a) < len(b):
        a, b = b, a
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1,
                               previous[j - 1] + (ca != cb)))
        previous = current
    return previous[-1]


def char_similarity(hypothesis: str, reference: str) -> float:
    """1 − character error rate, on canonical words joined without spaces
    (word boundaries in Persian transcripts are too unstable to count)."""
    hyp = "".join(canonical_words(hypothesis))
    ref = "".join(canonical_words(reference))
    if not ref:
        return 1.0 if not hyp else 0.0
    return max(0.0, 1.0 - _levenshtein(hyp, ref) / len(ref))


def round_trip(transcript: str, script_words: str, script_digits: str | None = None) -> dict:
    """Score a transcript against the script with numbers as words and as digits.

    `script_digits` defaults to `script_words`; the transcript is also
    compared after spelling its own digits, so «۱۹۹۵» in the transcript
    matches «هزار و نهصد و نود و پنج» in the script.
    """
    script_digits = script_digits or script_words
    spelled = spell_numbers(transcript)
    scores = {
        "vs_words": round(max(char_similarity(transcript, script_words),
                              char_similarity(spelled, script_words)), 4),
        "vs_digits": round(max(char_similarity(transcript, script_digits),
                               char_similarity(spelled, spell_numbers(script_digits))), 4),
    }
    scores["best"] = max(scores.values())
    return scores


def chars_per_second(text: str, seconds: float) -> float:
    """Spoken characters per second: letters and digits only, the measure the
    dub timing budget uses (max_chars ≈ seconds × cps)."""
    if seconds <= 0:
        return 0.0
    letters = sum(1 for ch in normalize(text) if not ch.isspace())
    return round(letters / seconds, 2)


def word_diff(transcript: str, reference: str) -> list[tuple[str, str]]:
    """Words the transcript got wrong, as (heard, expected) pairs, for lexicon
    suggestions. Uses difflib on canonical words."""
    import difflib

    hyp = canonical_words(spell_numbers(transcript))
    ref = canonical_words(reference)
    pairs = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(a=ref, b=hyp, autojunk=False).get_opcodes():
        heard, expected = hyp[j1:j2], ref[i1:i2]
        # «شرکتیکه» for «شرکتی که» is only a word boundary.
        if tag in ("replace", "delete") and "".join(heard) != "".join(expected):
            pairs.append((" ".join(heard), " ".join(expected)))
    return pairs
