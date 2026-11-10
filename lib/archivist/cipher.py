"""The hourly coded file: a historical cipher that chat races to solve.

Answers come in as ``!کد WORD`` (or ``!code WORD``). The first three correct
agents score 3, 2 and 1 points; the board persists between rounds.
"""

from __future__ import annotations

import json
import string
from dataclasses import dataclass, field
from pathlib import Path

# Each round: plaintext from the channel's sourced scripts, cipher, hint.
ROUNDS = [
    {
        "id": "enigma-caesar3",
        "plain": "ENIGMA",
        "method": "caesar",
        "shift": 3,
        "hint": "رمزِ سزار: هر حرف، سه خونه جلوتر از الفبا نوشته شده.",
        "dossier": "MI6",
        "reveal": "انیگما؛ ماشینی که آلمان پیام‌هاش رو باهاش رمز می‌کرد، و بلچلی پارک شکستش.",
    },
    {
        "id": "lubyanka-atbash",
        "plain": "LUBYANKA",
        "method": "atbash",
        "hint": "رمزِ آتباش: الفبا رو برعکس کن؛ A می‌شه Z.",
        "dossier": "KGB",
        "reveal": "لوبیانکا؛ ساختمونِ مرکزیِ پلیسِ مخفیِ شوروی.",
    },
]

UPPER = string.ascii_uppercase


def encode(round_: dict) -> str:
    if round_["method"] == "caesar":
        k = round_["shift"]
        return "".join(UPPER[(UPPER.index(c) + k) % 26] if c in UPPER else c for c in round_["plain"])
    if round_["method"] == "atbash":
        return "".join(UPPER[25 - UPPER.index(c)] if c in UPPER else c for c in round_["plain"])
    raise ValueError(round_["method"])


def normalize_guess(text: str) -> str:
    return "".join(c for c in text.upper() if c in UPPER)


@dataclass
class CipherGame:
    board: dict = field(default_factory=dict)
    round: dict | None = None
    winners: list = field(default_factory=list)
    guesses: int = 0

    POINTS = (3, 2, 1)

    @classmethod
    def load(cls, path: Path) -> "CipherGame":
        board = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        return cls(board=board)

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(self.board, ensure_ascii=False, indent=1), encoding="utf-8")

    def start(self, round_: dict) -> str:
        self.round, self.winners, self.guesses = round_, [], 0
        return encode(round_)

    def guess(self, user: str, text: str) -> int:
        """Score a guess; returns points won (0 if wrong, late or repeated)."""
        if not self.round:
            return 0
        self.guesses += 1
        if normalize_guess(text) != self.round["plain"] or user in self.winners:
            return 0
        if len(self.winners) >= len(self.POINTS):
            return 0
        points = self.POINTS[len(self.winners)]
        self.winners.append(user)
        self.board[user] = self.board.get(user, 0) + points
        return points

    def top(self, n: int = 5) -> list[tuple[str, int]]:
        return sorted(self.board.items(), key=lambda kv: (-kv[1], kv[0]))[:n]
