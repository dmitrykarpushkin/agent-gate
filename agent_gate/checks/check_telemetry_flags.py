"""Rule telemetry-content-off: Claude Code telemetry must not export prompts, tool content or raw API bodies.

OTEL_LOG_USER_PROMPTS, OTEL_LOG_TOOL_CONTENT and OTEL_LOG_RAW_API_BODIES (and the other flags in FLAGS) each lift the
default redaction of Claude Code's OpenTelemetry export, so prompts, file contents and any secret in them would leave
the machine. A tracked settings file, unit, script or env file that sets one of them to anything but 0/false/empty is a
problem. Docs (.md) are not scanned. A commented-out line is still reported (fails safe).

Config [telemetry_flags]: skip (path prefixes not scanned, such as test fixtures).
"""
import pathlib, re
from .. import common
from ..common import decode_bytes

FLAGS = ("OTEL_LOG_USER_PROMPTS", "OTEL_LOG_TOOL_CONTENT", "OTEL_LOG_RAW_API_BODIES", "OTEL_LOG_TOOL_DETAILS",
         "OTEL_LOG_ASSISTANT_RESPONSES")
NAME = r"(?<![A-Za-z0-9_])(" + "|".join(FLAGS) + r")"
SET = re.compile(NAME + r"[\"']?\]?\s*[:=,]\s*[\"']?\s*([^\s\"',;})]*)")
PAIR = re.compile(NAME + r"[\"']?\s*\n\s*(?:-\s*)?value\s*:\s*[\"']?([^\s\"',;}]*)")
OFF = {"", "0", "false", "no", "off"}
TEXT = (".json", ".yaml", ".yml", ".service", ".timer", ".sh", ".env", ".toml", ".py", ".conf", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".plist")


def text_problems(name, text):
    out = []
    for m in PAIR.finditer(text):
        if m.group(2).lower() not in OFF:
            out.append(f"{name}:{text[:m.start()].count(chr(10)) + 1}: {m.group(1)} is switched on")
    for lineno, line in enumerate(text.splitlines(), 1):
        for m in SET.finditer(line):
            if m.group(2).lower() not in OFF:
                out.append(f"{name}:{lineno}: {m.group(1)} is switched on")
    return out


def run(base=None, root=None, cfg=None):
    root = pathlib.Path(root or common.ROOT)
    skip = tuple(((cfg or {}).get("telemetry_flags") or {}).get("skip", ()))
    out = []
    for name in common.tracked(root):
        base_name = name.rsplit("/", 1)[-1]
        if (skip and name.startswith(skip)) or not (name.endswith(TEXT) or "." not in base_name or base_name.startswith(".env")):
            continue
        p = root / name
        if p.is_file():
            text = decode_bytes(p.read_bytes())
            if text:
                out += text_problems(name, text)
    return out
