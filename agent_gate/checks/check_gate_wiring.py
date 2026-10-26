"""Rule gate-wired: the agent gate stays wired in the Claude Code settings of the repo.

The settings file must run the gate for UserPromptSubmit (prompt), PreToolUse (pretool), PostToolUse (log) and Stop
(stop). A removed hook is the silent way the gate stops holding, so this fails the push. Whether a given agent session
loads the repo settings is not checked here.

Config [gate_wiring]: settings (default .claude/settings.json), command_contains (a fragment every gate command holds,
default "stopline" or the old name "agent-gate"). Without a [gate_wiring] table the check is off.
"""
import json, pathlib
from .. import common
from .. import gate

WIRING = {"UserPromptSubmit": "prompt", "PreToolUse": "pretool", "PostToolUse": "log", "Stop": "stop"}


def run(base=None, root=None, cfg=None):
    sec = (cfg or {}).get("gate_wiring")
    if sec is None:
        return []
    root = pathlib.Path(root or common.ROOT)
    settings = sec.get("settings", ".claude/settings.json")
    markers = [sec["command_contains"]] if "command_contains" in sec else ["stopline", "agent-gate"]
    marker = " or ".join(repr(m) for m in markers)
    try:
        hooks = json.loads((root / settings).read_text(encoding="utf-8")).get("hooks") or {}
    except (OSError, ValueError) as e:
        return [f"{settings} unreadable: {e}"]
    out = []
    for event, mode in WIRING.items():
        cmds = [h.get("command", "") for g in hooks.get(event) or [] for h in g.get("hooks") or []]
        if not any(any(m in c for m in markers) and c.rstrip().endswith(" gate " + mode) for c in cmds):
            out.append(f"{settings}: event {event} does not run the gate in mode {mode} (a command with {marker} ending in 'gate {mode}')")
        if mode not in gate.MODES:
            out.append(f"the gate has no mode {mode}")
    return out
