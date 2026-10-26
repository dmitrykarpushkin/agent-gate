"""Rule pinned-model-lifecycle: a pinned claude-* model id must not be deprecated and near retirement.

A lifecycle file lists model families (id prefix) with a status and, for a deprecated one, the retirement date. Any
tracked file that pins an id starting with a listed prefix whose status is deprecated or retired and whose retirement is
at most window_days away (or past) is a problem. Offline on purpose: the list is refreshed by hand from the deprecations
page named in the file, so a stale or incomplete list is the remaining risk: only the families listed are judged, and an
entry without a retirement date is never flagged.

Config [pinned_models]: lifecycle_file (a path in the repo; default the file shipped with agent-gate), window_days
(default 60), skip (path prefixes not scanned, such as test fixtures).
"""
import datetime, json, pathlib, re
from .. import common
from ..common import decode_bytes

WINDOW_DAYS = 60
BUNDLED = pathlib.Path(__file__).resolve().parent.parent / "model_lifecycle.json"
ID = re.compile(r"claude-(?:[a-z]+-[0-9]|[0-9]-)[0-9a-z.\-]*", re.I)  # claude-<family>-<n>... and the older claude-<n>-...
TEXT = (".py", ".sh", ".yaml", ".yml", ".json", ".service", ".timer", ".md", ".toml", ".env", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".conf", ".cfg", ".txt", ".ini")


def is_text_name(name):
    base = name.rsplit("/", 1)[-1]
    return name.endswith(TEXT) or "." not in base  # scripts without an extension count


def load_lifecycle(path):
    return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))["models"]


def problems_in(name, text, models, today, window=WINDOW_DAYS):
    out = []
    for lineno, line in enumerate(text.splitlines(), 1):
        for mid in ID.findall(line):
            for prefix, info in models.items():
                if not mid.lower().startswith(prefix) or info.get("status") not in ("deprecated", "retired") or not info.get("retires"):
                    continue
                days = (datetime.date.fromisoformat(info["retires"]) - today).days
                if days <= window:
                    out.append(f"{name}:{lineno}: pins {mid}, {info['status']}, retires {info['retires']} ({days} days)")
    return out


def run(base=None, root=None, cfg=None, today=None):
    root = pathlib.Path(root or common.ROOT)
    sec = (cfg or {}).get("pinned_models") or {}
    today = today or datetime.date.today()
    life = sec.get("lifecycle_file")
    models = load_lifecycle(root / life if life else BUNDLED)
    skip = tuple(sec.get("skip", ())) + ((life,) if life else ())
    window = int(sec.get("window_days", WINDOW_DAYS))
    out = []
    for name in common.tracked(root):
        if (skip and name.startswith(skip)) or not is_text_name(name):
            continue
        p = root / name
        if not p.is_file():
            continue
        text = decode_bytes(p.read_bytes())
        if text:
            out += problems_in(name, text, models, today, window)
    return out
