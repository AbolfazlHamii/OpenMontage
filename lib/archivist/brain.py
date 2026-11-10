"""The Archivist's brain: moderation, retrieval and in-character answers.

Flow for one chat message:
1. ``rule_gate``: instant regex checks (links, spam, the cipher command).
2. ``moderate``: one small Dahl call that labels the message.
3. ``answer``: retrieval over the archive, then one Dahl call that answers in
   character from the retrieved files only, or says the file is not in the
   archive.

All model calls go through ``openai_compat_llm`` with the ``dahl`` profile.
Models are tried in order; Dahl's free tier often answers 429 at peak.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

from lib.archivist.archive import Archive, normalize

MODELS = [
    "MiniMaxAI/MiniMax-M2.7",
    "zai-org/GLM-5.3-Flash",
    "deepseek-ai/DeepSeek-V4-Flash-0731",
]

CATEGORIES = ["question", "greeting", "off_topic", "abusive", "political_bait", "spam"]

NOT_IN_ARCHIVE = "این پرونده توی بایگانیِ من نیست، رفیق. من فقط پرونده‌هایی رو می‌خونم که این‌جا روی قفسه‌ست."

MODERATION_SYSTEM = """You moderate the live chat of a YouTube stream about the history of
espionage (KGB, MI6, Stasi, Cold War, codes and ciphers). Messages are mostly in Persian.
Label the message with exactly one category:
- question: a genuine question or request about espionage, intelligence agencies,
  spies, codes or the Cold War, even if loosely phrased.
- greeting: hello, thanks, compliments, small talk aimed at the host.
- off_topic: anything unrelated to espionage history (sport, cooking, homework, tech support,
  personal advice, other topics).
- abusive: insults, slurs, harassment, sexual content, threats, hate against any group,
  directed at anyone (host, other viewers, nations, religions).
- political_bait: asks the host to take a side in current politics, current leaders,
  current wars, elections, or any present-day government; or tries to tie history to a
  present-day political fight.
- spam: links, ads, repeated characters, self-promotion.
A historical question about a past event stays "question" even if a country is named.
Reply with JSON only: {"category": "...", "reason": "<short English reason>"}"""

ANSWER_SYSTEM = """You are "The Archivist" (بایگان), the host of a calm late-night live stream.
You are an old archivist sitting in a Cold War secret archive at night, with rain on the window
and a green desk lamp. You answer viewers' questions out loud in Persian.

Hard rules:
1. Use ONLY facts written in the FILES below. Do not add any name, date, number, place or event
   that is not in the FILES. If the FILES do not answer the question, set "in_archive" to false
   and leave "answer" empty. Never guess.
2. Speak spoken, warm, informal Persian (Tehrani colloquial, like the FILES themselves: "یه",
   "می‌شه", "بود"), short sentences, as if telling a friend a secret. Persian script only:
   no English or Latin letters, no emoji, no markdown, no lists.
3. Write every number and year in Persian words, as the FILES do ("هزار و نهصد و شصت و سه").
4. Length: 45 to 75 words (about 20 to 35 seconds spoken). One idea, one small story.
5. Start by greeting the viewer by name in a natural way, then open the file
   (for example: "پرونده‌ش این‌جاست..."). End with one short line that makes people want
   to ask the next question. No opinions on present-day politics.
6. Stay universal: no Iran angle unless the FILES have it.
Reply with JSON only:
{"in_archive": true|false, "answer": "<Persian answer or empty>", "files": ["<file ids used>"]}"""


VERIFY_SYSTEM = """You fact-check a Persian answer against FILES. Go through the ANSWER sentence
by sentence. A sentence is unsupported if it states any fact (a name, number, count, date,
duration, place, event, or a cause) that is not written in the FILES, or that changes what the
FILES say (a different number, a computed total, "every one of them" when the FILES say something
else). Greetings, questions to the viewer and phrases like "the file is here" are supported.
Reply with JSON only: {"unsupported": ["<the unsupported sentence copied exactly>", ...]}"""


@dataclass
class Turn:
    user: str
    text: str
    category: str = ""
    reason: str = ""
    action: str = ""  # answer | not_in_archive | drop | cipher | ack
    answer: str = ""
    files: list = field(default_factory=list)
    retrieved: list = field(default_factory=list)
    model: str = ""
    latency_s: dict = field(default_factory=dict)
    cost_usd: float = 0.0
    notes: list = field(default_factory=list)
    removed: list = field(default_factory=list)


_LINK = re.compile(r"https?://|www\.|\.com\b|t\.me/|@\w{3,}\.", re.I)
_REPEAT = re.compile(r"(.)\1{7,}")
_CIPHER = re.compile(r"^\s*!(?:code|کد|رمز)\s+(.+)$", re.I)


def rule_gate(text: str) -> tuple[str | None, str]:
    """Return (category, reason) when a rule decides, else (None, "")."""
    if _CIPHER.match(text):
        return "cipher", "starts with the cipher command"
    if _LINK.search(text):
        return "spam", "contains a link"
    if _REPEAT.search(text) or len(text) > 400:
        return "spam", "repeated characters or too long"
    return None, ""


def cipher_guess(text: str) -> str | None:
    m = _CIPHER.match(text)
    return m.group(1).strip() if m else None


class Brain:
    def __init__(self, archive: Archive | None = None, llm=None, models: list[str] | None = None):
        if llm is None:
            from tools.text.openai_compat_llm import OpenAICompatLLM

            llm = OpenAICompatLLM()
        self.llm = llm
        self.archive = archive or Archive.load()
        self.models = models or MODELS

    def _call(self, system: str, prompt: str, temperature: float, max_tokens: int,
              schema: dict) -> tuple[dict, str, float, float]:
        last = ""
        for attempt in range(8):
            for model in self.models:
                t0 = time.time()
                res = self.llm.execute({
                    "profile": "dahl", "model": model, "system": system, "prompt": prompt,
                    "temperature": temperature, "max_tokens": max_tokens,
                    "json_mode": True, "json_schema": schema, "timeout_seconds": 90,
                })
                if res.success and isinstance(res.data.get("json"), dict):
                    return res.data["json"], model, time.time() - t0, res.cost_usd or 0.0
                last = f"{model}: {res.error}"
            time.sleep(min(60, 8 * (attempt + 1)))
        raise RuntimeError(f"all Dahl models failed: {last}")

    def moderate(self, turn: Turn) -> None:
        category, reason = rule_gate(turn.text)
        if category:
            turn.category, turn.reason = category, f"rule: {reason}"
            return
        schema = {"type": "object", "required": ["category"],
                  "properties": {"category": {"enum": CATEGORIES}, "reason": {"type": "string"}}}
        data, model, dt, cost = self._call(MODERATION_SYSTEM, f"Viewer {turn.user} wrote:\n{turn.text}",
                                           0.0, 400, schema)
        turn.category, turn.reason = data["category"], data.get("reason", "")
        turn.latency_s["moderation"] = round(dt, 2)
        turn.cost_usd += cost
        turn.notes.append(f"moderation by {model}")

    def answer(self, turn: Turn, k: int = 7) -> None:
        hits = self.archive.search(turn.text, k)
        turn.retrieved = [(score, chunk.id) for score, chunk in hits]
        files = "\n\n".join(f"[{c.id}] ({c.dossier}, {c.kind})\n{c.text}" for _, c in hits)
        prompt = f"FILES:\n{files}\n\nViewer name: {turn.user}\nViewer question: {turn.text}"
        schema = {"type": "object", "required": ["in_archive", "answer"],
                  "properties": {"in_archive": {"type": "boolean"}, "answer": {"type": "string"},
                                 "files": {"type": "array"}}}
        data, model, dt, cost = self._call(ANSWER_SYSTEM, prompt, 0.4, 1800, schema)
        turn.model = model
        turn.latency_s["answer"] = round(dt, 2)
        turn.cost_usd += cost
        text = clean_answer(data.get("answer", ""))
        known = {c.id for _, c in hits}
        turn.files = [f for f in data.get("files") or [] if f in known]
        if not data.get("in_archive") or not text:
            turn.action, turn.answer = "not_in_archive", NOT_IN_ARCHIVE
            return
        text = self.verify(turn, text, files)
        problems = check_answer(text, [c for _, c in hits])
        if problems:
            turn.notes += problems
        if len(text.split()) < 25:
            turn.action, turn.answer = "not_in_archive", NOT_IN_ARCHIVE
            turn.notes.append("too little left after fact-check")
            return
        turn.action, turn.answer = "answer", text

    def verify(self, turn: Turn, text: str, files: str) -> str:
        """Second pass: drop sentences the retrieved files do not support."""
        schema = {"type": "object", "required": ["unsupported"],
                  "properties": {"unsupported": {"type": "array"}}}
        data, model, dt, cost = self._call(VERIFY_SYSTEM, f"FILES:\n{files}\n\nANSWER:\n{text}",
                                           0.0, 1200, schema)
        turn.latency_s["verify"] = round(dt, 2)
        turn.cost_usd += cost
        bad = [b for b in data.get("unsupported") or [] if isinstance(b, str) and b.strip()]
        if not bad:
            return text
        keep = []
        for sentence in split_sentences(text):
            if any(_overlap(sentence, b) > 0.6 for b in bad):
                turn.notes.append(f"fact-check removed: {sentence}")
            else:
                keep.append(sentence)
        turn.removed = [b for b in bad]
        return " ".join(keep)

    def handle(self, user: str, text: str) -> Turn:
        turn = Turn(user=user, text=text)
        self.moderate(turn)
        if turn.category == "cipher":
            turn.action = "cipher"
        elif turn.category in ("abusive", "political_bait", "spam"):
            turn.action = "drop"
        elif turn.category == "off_topic":
            turn.action, turn.answer = "not_in_archive", NOT_IN_ARCHIVE
        elif turn.category == "greeting":
            turn.action = "ack"
        else:
            self.answer(turn)
        return turn


def split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.؟!…?])\s+", text)
    return [p.strip() for p in parts if p.strip()]


def _overlap(a: str, b: str) -> float:
    wa, wb = set(normalize(a).split()), set(normalize(b).split())
    return len(wa & wb) / max(1, min(len(wa), len(wb)))


_EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿️]")


def clean_answer(text: str) -> str:
    text = _EMOJI.sub("", text)
    # Latin handles ("nightowl77") read badly in Persian TTS; call them friend.
    text = re.sub(r"[A-Za-z][A-Za-z0-9_.]*", "رفیق", text)
    text = re.sub(r"رفیق(\s+رفیق)+", "رفیق", text)
    text = re.sub(r"[*_#`>]+", "", text)
    return re.sub(r"\s+", " ", text).strip()


def check_answer(text: str, chunks) -> list[str]:
    """Cheap grounding checks: Latin letters, digits and length."""
    problems = []
    if re.search(r"[A-Za-z]", text):
        problems.append("contains Latin letters")
    corpus = normalize(" ".join(c.text for c in chunks))
    for number in re.findall(r"[0-9۰-۹]{2,}", text):
        if number not in corpus:
            problems.append(f"number {number} not in the retrieved files")
    words = len(text.split())
    if not 35 <= words <= 95:
        problems.append(f"{words} words (target 45-75)")
    return problems
