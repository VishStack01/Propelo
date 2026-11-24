"""Clichés and filler in cover notes, screening answers and outreach.

    propelo writing-check note.txt [--banned "leverage,synergy"]

A recruiter reads hundreds of notes that open with "I am writing to express my
interest" and close with "I believe I would be a great fit". This check flags
those lines, plus words that make a note sound machine-written, so the draft
gets rewritten around one specific proof point instead. It warns; it never
rewrites anything itself.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

# 142 phrases that make writing sound machine-made or empty, each with why and what to do instead. Some have a safe
# plain replacement ("spearheaded" -> "led", "utilised" -> "used") or are a word that can simply go ("robust",
# "successfully"); clean() applies those to AI drafts. The dashboard runs the same rules (scripts/sync_slop_rules.py).
RULES = json.loads((Path(__file__).parent / "data" / "slop_rules.json").read_text(encoding="utf-8"))["rules"]
_FLAGS = re.IGNORECASE | re.MULTILINE


def _find_rx(r: dict) -> re.Pattern:
    return re.compile(r["pattern"] if "pattern" in r else r"\b" + re.escape(r["delete"]) + r"\b", _FLAGS)


for _r in RULES:
    _r["_find"] = _find_rx(_r)
    if "delete" in _r:
        # The word, with an "a"/"an" before it and the first letter of the next word, so both can be put right.
        _r["_del"] = re.compile(r"(?:\b(an?)\s+)?\b" + re.escape(_r["delete"]) + r"\s+([A-Za-z])(?=([A-Za-z]*))", _FLAGS)

# Kept for callers that list the phrases: (pattern, why, instead).
PHRASES = [(r["_find"].pattern, r["why"], r["instead"]) for r in RULES]

_CONSONANT_SOUND = re.compile(r"^(uni|use|usa|usu|uti|ure|uro|one|once|eu|ewe)", re.I)
_SILENT_H = re.compile(r"^(hour|honest|honou?r|heir)", re.I)
_VOWEL_LETTER_NAME = set("AEFHILMNORSX")


def article(word: str) -> str:
    """'a' or 'an' for the word that follows, by sound: an API, a GPU, an hour, a user."""
    if len(word) > 1 and word.isupper():
        return "an" if word[0] in _VOWEL_LETTER_NAME else "a"
    if _SILENT_H.match(word):
        return "an"
    if word[:1].lower() in "aeiou" and not _CONSONANT_SOUND.match(word):
        return "an"
    return "a"


def clean(text: str) -> tuple[str, list[dict]]:
    """Apply the safe fixes to a draft. Returns (new text, [{"from", "to"}]). Never adds a fact; only swaps a word for
    a plainer one or drops an empty one."""
    fixed: list[dict] = []
    text = text or ""
    for r in RULES:
        if "fix" in r:
            def swap(m: re.Match, r=r) -> str:
                out, was = r["fix"], m.group(0)
                if was.lstrip()[:1].isupper() and out[:1].isalpha():
                    out = out[:1].upper() + out[1:]
                fixed.append({"from": was.strip(), "to": out.strip()})
                return out
            text = r["_find"].sub(swap, text)
        elif "delete" in r:
            def drop(m: re.Match, r=r) -> str:
                art, first, rest = m.group(1), m.group(2), m.group(3)
                fixed.append({"from": r["delete"], "to": ""})
                if art:
                    a = article(first + rest)
                    return (a[:1].upper() + a[1:] if art[:1].isupper() else a) + " " + first
                return first.upper() if m.group(0)[:1].isupper() else first
            text = r["_del"].sub(drop, text)
    text = re.sub(r",\s*,", ",", text)
    text = re.sub(r"^, *", "", text, flags=re.MULTILINE)
    return text, fixed


@dataclass
class Finding:
    phrase: str
    why: str
    instead: str
    line: int

    def to_dict(self) -> dict:
        return asdict(self)


def check(text: str, banned: list[str] | None = None) -> list[Finding]:
    out: list[Finding] = []
    lines = (text or "").splitlines() or [""]
    rules = [(r["_find"], r["why"], r["instead"]) for r in RULES if r.get("pattern") != r"\s*—\s*"]
    rules += [(re.compile(rf"\b{re.escape(w)}\w*\b", re.I), "on your banned-words list", "use your own word") for w in (banned or []) if w.strip()]
    for n, line in enumerate(lines, 1):
        spans: list[tuple[int, int]] = []
        for rx, why, instead in rules:
            for m in rx.finditer(line):
                if any(a <= m.start() and m.end() <= b for a, b in spans):
                    continue  # already flagged as part of a longer phrase
                spans.append(m.span())
                out.append(Finding(m.group(0), why, instead, n))
    if text.count("!") > 1:
        out.append(Finding("!", f"{text.count('!')} exclamation marks", "keep at most one", 0))
    if text.count("—") > 2:
        out.append(Finding("—", f"{text.count('—')} long dashes", "use commas or full stops", 0))
    words = re.findall(r"[A-Za-z']+", text)
    if words and sum(1 for w in words if w.lower() in ("i", "i'm", "i've", "my", "me")) / len(words) > 0.09:
        out.append(Finding("I / my", "the note is mostly about you", "talk about their problem first", 0))
    return out


def specific(text: str) -> bool:
    """Does the note carry at least one concrete proof point (a number or a named thing you built)?"""
    return bool(re.search(r"\d", text or "")) or bool(re.search(r"\b(built|shipped|launched|designed|automated|cut|grew|reduced)\b", text or "", re.I))
