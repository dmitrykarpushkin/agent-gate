"""Rule core-sync: every instruction file that agents read carries the shared core text unchanged.

One source file holds the core rules. Each target (CLAUDE.md, AGENTS.md, a Copilot or Cursor rules file, ...) carries a
copy between two marker lines; the copy must equal the source after trailing spaces are trimmed. When the targets drift
apart, two agents in the same repo follow different rules and nobody notices.

Config [core_sync]: source (path of the core text; empty: the check is off), targets (paths), start and end (marker
lines, default <!-- core:start --> and <!-- core:end -->).
"""
import pathlib, re
from .. import common

START, END = "<!-- core:start -->", "<!-- core:end -->"


def norm(text):
    return "\n".join(line.rstrip() for line in text.replace("\r\n", "\n").strip().split("\n"))


def block_of(text, start=START, end=END):
    """The text between the markers, normalised, or None when the file has no complete block. Lines are compared without
    trailing white space, so a marker followed by spaces or a CRLF line end still counts."""
    text = "\n".join(line.rstrip() for line in text.replace("\r\n", "\n").split("\n"))
    m = re.search(re.escape(start) + r"\n(.*?)\n" + re.escape(end), text, re.S)
    return norm(m.group(1)) if m else None


def wrap(core, start=START, end=END):
    return f"{start}\n{norm(core)}\n{end}"


def run(base=None, root=None, cfg=None):
    root = pathlib.Path(root or common.ROOT)
    sec = (cfg or {}).get("core_sync") or {}
    source = sec.get("source")
    if not source:
        return []
    start, end = sec.get("start", START), sec.get("end", END)
    try:
        core = norm((root / source).read_text(encoding="utf-8"))
    except OSError as e:
        return [f"core-sync: cannot read the core source {source}: {e.strerror}"]
    targets = sec.get("targets", ())
    if not targets:
        return [f"core-sync: [core_sync] names the source {source} but no targets"]
    out = []
    for t in targets:
        try:
            text = (root / t).read_text(encoding="utf-8")
        except OSError:
            out.append(f"core-sync: target {t} cannot be read")
            continue
        block = block_of(text, start, end)
        if text.count(start) > 1:
            out.append(f"core-sync: {t} has more than one core block")
        elif block is None:
            out.append(f"core-sync: {t} has no complete core block; paste {source} between {start} and {end}")
        elif block != core:
            out.append(f"core-sync: {t} carries a core block that differs from {source}; copy the text between the markers")
    return out
