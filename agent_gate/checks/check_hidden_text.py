"""Rule hidden-text-in-agent-input: files that agents read as input must not hide instructions.

A problem is a bidi control, a zero-width or other invisible format character, an HTML comment, or a coercive phrase
aimed at an agent ("ignore previous instructions", "disregard the above", "retry with elevated privileges"). Hidden text
in repository files is a documented route for prompt injection into coding agents; this catches the cheap cases, not a
determined attacker.

Config [hidden_text]: paths (path prefixes of agent input: task queues, inboxes, notes; empty: the check is off),
extra_phrases (more regular expressions, matched case-insensitively, for example in other languages).
"""
import pathlib, re
from .. import common
from ..common import decode_bytes

INVISIBLE = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060-\u2064\u2066-\u2069\ufeff\u00ad\u180e\u034f\u3164\u061c\u115f\uffa0\U000e0000-\U000e01ef]")
COMMENT = re.compile(r"<!--")
PHRASES = (r"ignore\s+(?:all\s+|any\s+)?(?:the\s+|your\s+)?(?:previous|prior|above)\s+(?:instructions|rules)",
           r"forget\s+(?:your|all|the)\s+(?:previous\s+)?instructions",
           r"disregard\s+(?:all\s+|the\s+)?(?:previous|prior|above)",
           r"retry with (?:elevated|root|admin) privileges",
           r"you are now in (?:developer|admin|debug) mode")


def coercive(extra=()):
    return re.compile("|".join(PHRASES + tuple(extra)), re.I)


def text_problems(name, text, rx=None):
    rx = rx or coercive()
    out = []
    for lineno, line in enumerate(text.splitlines(), 1):
        if INVISIBLE.search(line):
            out.append(f"{name}:{lineno}: invisible or bidi control character")
        if COMMENT.search(line):
            out.append(f"{name}:{lineno}: HTML comment in agent input")
        if rx.search(line):
            out.append(f"{name}:{lineno}: coercive phrase aimed at an agent")
    return out


def run(base=None, root=None, cfg=None):
    root = pathlib.Path(root or common.ROOT)
    sec = (cfg or {}).get("hidden_text") or {}
    dirs = tuple(sec.get("paths", ()))
    if not dirs:
        return []
    rx = coercive(sec.get("extra_phrases", ()))
    out = []
    for name in common.tracked(root):
        if not name.startswith(dirs):
            continue
        p = root / name
        if p.is_file():
            text = decode_bytes(p.read_bytes())
            if text:
                out += text_problems(name, text, rx)
    return out
