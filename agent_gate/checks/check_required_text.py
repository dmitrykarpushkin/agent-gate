"""Rule required-text: documents that agents and reviewers depend on keep their load-bearing parts.

An edit that "tidies" a review guide or a process spec can silently drop the one section a reviewer agent is told to
follow. This check only looks for presence: each listed file exists and contains each listed phrase verbatim. Whether
the text is followed is not checked here.

Config [required_text]: a table of path = ["phrase", ...]. Empty: the check is off.
"""
import pathlib
from .. import common


def missing(name, text, parts):
    if text is None:
        return [f"{name} is missing"]
    return [f"{name} lacks {p!r}" for p in parts if p not in text]


def run(base=None, root=None, cfg=None):
    root = pathlib.Path(root or common.ROOT)
    out = []
    for name, parts in ((cfg or {}).get("required_text") or {}).items():
        p = root / name
        out += missing(name, p.read_text(encoding="utf-8") if p.is_file() else None, parts)
    return out
