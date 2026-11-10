"""The Archivist's archive: the channel's sourced scripts, split into files.

Retrieval is character 3-gram TF-IDF. Dahl has no embeddings endpoint and the
archive is small (three scripts and their source tables, a few hundred
chunks), so a lexical index is fast, free and good enough for names, places
and years.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# (dossier, narration, sources). Only scripts that went through sourcing.
DOSSIERS = [
    ("KGB", "projects/kgb-history-fa/artifacts/narration.txt",
     "projects/kgb-history-fa/artifacts/sources.md"),
    ("MI6", "projects/mi6-history-fa/narration.txt",
     "projects/mi6-history-fa/artifacts/sources.md"),
    ("STASI", "projects/stasi-history-fa/artifacts/narration.txt",
     "projects/stasi-history-fa/artifacts/sources.md"),
]

# Spellings viewers type for the same thing, folded onto the scripts' spelling.
ALIASES = {
    r"\bkgb\b|کاگ\s*ب|کا\.گ\.ب\.?|کی\s*جی\s*بی|کاگب": "کا گ ب",
    r"\bmi\s*-?\s*6\b|ام\s*آی\s*(?:۶|6|سیکس)|ام‌آی‌۶": "ام‌آی‌سیکس",
    r"\bstasi\b|استازی|اشتاسی": "اشتازی",
    r"\bcheka\b": "چکا",
    r"\bphilby\b": "فیلبی",
    r"\bgordievsky\b|گوردیفسکی|گوردیوسکی": "گوردیفسکی",
}

_DIACRITICS = re.compile("[ً-ٰٟ]")


def normalize(text: str) -> str:
    text = text.replace("ي", "ی").replace("ك", "ک").replace("ۀ", "ه")
    text = _DIACRITICS.sub("", text)
    text = text.replace("‌", " ").lower()
    for pattern, canon in ALIASES.items():
        text = re.sub(pattern, canon.replace("‌", " "), text, flags=re.I)
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


STOPWORDS = set("""
و یه یک از به با در توی تو که این اون آن را رو هم برای تا ولی اما یا چی چه چرا چطور چطوری کی
کجا کدوم آیا بود بودن شد شده می هست است نه ما من تو شما اونا ها های رفیق سلام بایگان جان
آخرش واقعا واقعی قضیه ماجرای ماجرا سوال سؤال کرد کردن داره دارن چیه کنه کنی بگو لطفا
""".split())


def _words(text: str) -> list[str]:
    return [w for w in normalize(text).split() if w not in STOPWORDS and len(w) > 1]


def _grams(text: str, n: int = 3) -> Counter:
    grams: Counter = Counter()
    for word in _words(text):
        padded = f" {word} "
        if len(padded) <= n:
            grams[padded] += 1
            continue
        for i in range(len(padded) - n + 1):
            grams[padded[i:i + n]] += 1
    return grams


@dataclass
class Chunk:
    id: str
    dossier: str
    kind: str  # "script" or "source"
    text: str
    vector: dict = field(default_factory=dict, repr=False)


def _script_chunks(dossier: str, path: Path, window: int = 3) -> list[Chunk]:
    paras = [p.strip() for p in path.read_text(encoding="utf-8").split("\n\n") if p.strip()]
    chunks = []
    for i in range(0, len(paras), 2):
        text = "\n".join(paras[i:i + window])
        chunks.append(Chunk(f"{dossier}-s{i // 2 + 1:02d}", dossier, "script", text))
    return chunks


def _source_chunks(dossier: str, path: Path) -> list[Chunk]:
    chunks = []
    for line in path.read_text(encoding="utf-8").splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 3 or set(cells[0]) <= set("-: ") or cells[0].lower() in ("scenes", "scene"):
            continue
        claim = cells[1]
        links = re.findall(r"\[([^\]]+)\]\((https?://[^)]+)\)", cells[2])
        text = claim + " — " + "; ".join(f"{name} <{url}>" for name, url in links)
        chunks.append(Chunk(f"{dossier}-src{len(chunks) + 1:02d}", dossier, "source", text))
    return chunks


class Archive:
    def __init__(self, chunks: list[Chunk]):
        self.chunks = chunks
        df: Counter = Counter()
        grams = [_grams(c.text) for c in chunks]
        for g in grams:
            df.update(g.keys())
        n = len(chunks)
        self.idf = {g: math.log((n + 1) / (d + 0.5)) for g, d in df.items()}
        for chunk, g in zip(chunks, grams):
            chunk.vector = self._weigh(g)

    @classmethod
    def load(cls, repo: Path = REPO) -> "Archive":
        chunks: list[Chunk] = []
        for dossier, narration, sources in DOSSIERS:
            if (repo / narration).exists():
                chunks += _script_chunks(dossier, repo / narration)
            if (repo / sources).exists():
                chunks += _source_chunks(dossier, repo / sources)
        return cls(chunks)

    def _weigh(self, grams: Counter) -> dict:
        vec = {g: (1 + math.log(c)) * self.idf.get(g, 0.0) for g, c in grams.items()}
        norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
        return {g: v / norm for g, v in vec.items()}

    def search(self, query: str, k: int = 8) -> list[tuple[float, Chunk]]:
        """Top chunks by 3-gram cosine, plus a bonus for each rare query word
        (names, places) found whole in the chunk."""
        q = self._weigh(_grams(query))
        rare = [w for w in set(_words(query)) if len(w) > 2]
        scored = []
        for chunk in self.chunks:
            score = sum(w * chunk.vector.get(g, 0.0) for g, w in q.items())
            body = " " + normalize(chunk.text) + " "
            score += 0.08 * sum(1 for w in rare if f" {w}" in body)
            scored.append((round(score, 4), chunk))
        scored.sort(key=lambda s: -s[0])
        top = scored[:k]
        # A story often continues in the next chunk ("...his name? Kim Philby."
        # then the escape), so the best script hits bring their successor.
        have = {c.id for _, c in top}
        for score, chunk in [s for s in top if s[1].kind == "script"][:3]:
            dossier, n = chunk.id.rsplit("-s", 1)
            follow = self.get(f"{dossier}-s{int(n) + 1:02d}")
            if follow and follow.id not in have:
                top.append((round(score * 0.9, 4), follow))
                have.add(follow.id)
        return top

    def get(self, chunk_id: str) -> Chunk | None:
        return next((c for c in self.chunks if c.id == chunk_id), None)
