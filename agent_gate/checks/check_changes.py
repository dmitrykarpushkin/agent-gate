"""Rules independent-verifier, explicit-yes, evidence-for-done: validate change records.

A change lives in <dir>/<NNNN-name>/ with proposal.md, tasks.md and verification.md (finished ones may move to
<dir>/archive/). verification.md starts with a front matter block of `key: value` lines between `---` markers:
  status: draft | proposed | verified | applied
  kind: feature | fix | cleanup | service | money | message | production | deletion | force_push
  author: <agent or person id>
  verifier: <different id>        required from status verified; compared with author after strip and casefold;
                    a placeholder (pending, none, tbd, todo, n/a, na, null, unknown) or a value with no letter or digit is a problem
  evidence: <link, hash or command output reference>   required from status verified. It must carry some detail: two or
                    more words, or one token that looks like a commit hash (7 to 40 hex characters), a URL or a path
                    (contains "/" and at least 6 characters, so "n/a" fails). "ok", "done", "yes", "-" are problems.
                    The machine does not check that the hash or path exists.
  before / after: required for kind fix from status verified
  approved_by_user: <message id> "<quoted excerpt>"   required from status applied when the kind needs a yes (needs_yes)
                    or cost_usd is above spend_limit_usd. Exact format: an id matching approval_id, a space, then an
                    excerpt of the person's message in straight double quotes with at least 3 words. Any other text is a
                    problem at every status where the field is present. Only the shape is checked, not that the message
                    exists or says yes.
  approval_scope: shared   optional; allows the same message id to approve changes of different kinds. Without it,
                    one message id used in two records of different kinds that both need a yes is a problem.
  cost_usd: <number>   must be a finite number >= 0
  risk: low | medium | high, revert: <how to undo>   from change number risk_from and status verified
  test_author: <agent id>   from change number task_tests_from and status verified: the agent that wrote the tests;
                    must be a real id and differ from author (the one implementing)
A change with status applied must have no open `- [ ]` task in its tasks.md.
tasks.md, from change number task_tests_from: every checkbox line must name its tests with `tests: <what>`
(`tests: none, <reason>` is allowed for a task with no code).

Config [changes]: dir (default "changes"; the check is off when the folder does not exist), needs_yes (kinds),
spend_limit_usd (default 10), approval_id (regular expression, default below), task_tests_from and risk_from
(change numbers from which those rules apply, default 0: a team that adopts a rule later keeps its old records valid).
"""
import math
import pathlib
import re
from .. import common

STATUSES = ["draft", "proposed", "verified", "applied"]
KINDS = {"feature", "fix", "cleanup", "service", "money", "message", "production", "deletion", "force_push"}
NEEDS_YES = {"service", "money", "message", "production", "deletion", "force_push"}
SPEND_LIMIT_USD = 10
APPROVAL_ID = r"[A-Za-z0-9][A-Za-z0-9_.:/#-]{5,}"
APPROVAL_MIN_WORDS = 3
HASH_RE = re.compile(r"^[0-9a-fA-F]{7,40}$")
PLACEHOLDERS = {"pending", "none", "tbd", "todo", "n/a", "na", "null", "unknown"}
FILES = ("proposal.md", "tasks.md", "verification.md")


class Policy:
    """The [changes] table, resolved."""

    def __init__(self, cfg=None):
        sec = (cfg or {}).get("changes") or {}
        self.dir = sec.get("dir", "changes")
        self.needs_yes = set(sec.get("needs_yes", NEEDS_YES))
        self.spend_limit = float(sec.get("spend_limit_usd", SPEND_LIMIT_USD))
        self.approval = re.compile(r'^(' + sec.get("approval_id", APPROVAL_ID) + r') "([^"]*)"$')
        self.task_tests_from = int(sec.get("task_tests_from", 0))
        self.risk_from = int(sec.get("risk_from", 0))


DEFAULT = Policy()
RISKS = {"low", "medium", "high"}
TASK_RE = re.compile(r"^\s*[-*]\s+\[[ xX]\]\s+(.*)$")
TESTS_RE = re.compile(r"\btests:\s*(\S.*)", re.IGNORECASE)


def change_number(name):
    m = re.match(r"(\d+)-", name)
    return int(m.group(1)) if m else None


def applies(name, start):
    """A rule that starts at change number `start` applies to this record (start 0: to every record, numbered or not)."""
    num = change_number(name)
    return start <= 0 or (num is not None and num >= start)


def check_task_tests(name, text):
    """Every checkbox task of a new change names its tests (`tests: ...`); returns one problem per bare task."""
    out = []
    for line in (text or "").splitlines():
        m = TASK_RE.match(line)
        if m and not TESTS_RE.search(m.group(1)):
            out.append(f"{name}: task without tests: {m.group(1).strip()[:60]!r} (add `tests: <name or none, reason>`)")
    return out


def check_risk(name, meta):
    """From status verified (of change risk_from on): risk is low, medium or high and revert says how to undo the change."""
    out = []
    if (meta.get("risk") or "").strip().lower() not in RISKS:
        out.append(f"{name}: verified needs risk: low, medium or high (got {meta.get('risk')!r})")
    rv = meta.get("revert")
    if not rv or is_placeholder(rv):
        out.append(f"{name}: verified needs revert: how to undo the change")
    return out


def check_test_author(name, meta):
    """From status verified the agent that wrote the tests is named and differs from the author."""
    ta = meta.get("test_author")
    if not ta:
        return [f"{name}: verified without test_author"]
    if is_placeholder(ta):
        return [f"{name}: test_author {ta!r} is a placeholder, name the agent that wrote the tests"]
    if ta.strip().casefold() == (meta.get("author") or "").strip().casefold():
        return [f"{name}: test_author equals author"]
    return []


class Front(dict):
    """Front matter values; `duplicates` lists keys that appeared more than once (the last value wins)."""
    duplicates = ()


def parse_front(text):
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    meta = Front()
    meta.duplicates = []
    for l in lines[1:]:
        if l.strip() == "---":
            return meta
        if ":" in l:
            k, v = l.split(":", 1)
            k = k.strip()
            if k in meta and k not in meta.duplicates:
                meta.duplicates.append(k)
            meta[k] = v.strip()
    return None


def duplicate_problems(name, meta):
    """One problem per front matter key that appears twice, so a later line cannot silently hide an earlier one."""
    return [f"{name}: duplicate key {k!r} in front matter" for k in getattr(meta, "duplicates", ())]


def evidence_has_detail(value):
    """True when the evidence is more than one bare word: two or more words, or one hash, URL or path."""
    words = (value or "").split()
    if len(words) >= 2:
        return True
    return len(words) == 1 and bool(HASH_RE.match(words[0]) or ("/" in words[0] and len(words[0]) >= 6))


def is_placeholder(value):
    """True for a stand-in value: a known placeholder word, or text with no letter or digit (such as "-")."""
    v = (value or "").strip().casefold()
    return v in PLACEHOLDERS or not any(c.isalnum() for c in v)


def parse_cost(value):
    """Return the cost as a float, or None when it is not a finite number >= 0."""
    try:
        cost = float(value)
    except (TypeError, ValueError):
        return None
    return cost if math.isfinite(cost) and cost >= 0 else None


def parse_approval(value, policy=DEFAULT):
    """Return the message id of a well formed approved_by_user value, or None."""
    m = policy.approval.match((value or "").strip())
    if not m or len(m.group(2).split()) < APPROVAL_MIN_WORDS:
        return None
    return m.group(1)


def needs_yes(meta, policy=DEFAULT):
    """True when the record is of a kind or costs enough to need a person's yes."""
    if meta.get("kind") in policy.needs_yes:
        return True
    cost = parse_cost(meta["cost_usd"]) if "cost_usd" in meta else None
    return cost is not None and cost > policy.spend_limit


def check_reuse(records, policy=DEFAULT):
    """records: list of (name, meta). Report one message id approving different kinds that need a yes."""
    by_id = {}
    for name, meta in records:
        if not meta or meta.get("approval_scope", "").strip() == "shared":
            continue
        mid = parse_approval(meta.get("approved_by_user"), policy)
        if mid and needs_yes(meta, policy):
            by_id.setdefault(mid, []).append((name, meta.get("kind")))
    out = []
    for mid, items in sorted(by_id.items()):
        if len({k for _, k in items}) > 1:
            names = ", ".join(f"{n} ({k})" for n, k in items)
            out.append(f"approval {mid} is reused for different kinds: {names}; "
                       "use a separate approval or approval_scope: shared")
    return out


def check_numbers(names):
    """Report change folders (live and archive together) that share one leading number."""
    by_num = {}
    for n in names:
        m = re.match(r"(\d+)-", n)
        if m:
            by_num.setdefault(int(m.group(1)), []).append(n)
    return [f"change number {num:04d} is used by {len(items)} records: {', '.join(sorted(items))}; take the next free number after a pull"
            for num, items in sorted(by_num.items()) if len(items) > 1]


def check_record(name, meta, policy=DEFAULT):
    out = []
    if meta is None:
        return [f"{name}: verification.md has no front matter"]
    out += duplicate_problems(name, meta)
    status, kind = meta.get("status"), meta.get("kind")
    if status not in STATUSES:
        out.append(f"{name}: bad status {status!r}")
        return out
    if kind not in KINDS:
        out.append(f"{name}: bad kind {kind!r}")
    if not meta.get("author"):
        out.append(f"{name}: missing author")
    rank = STATUSES.index(status)
    if rank >= STATUSES.index("verified"):
        if not meta.get("verifier"):
            out.append(f"{name}: verified without verifier")
        elif is_placeholder(meta["verifier"]):
            out.append(f"{name}: verifier {meta['verifier']!r} is a placeholder, name the agent that verified")
        elif meta["verifier"].strip().casefold() == (meta.get("author") or "").strip().casefold():
            out.append(f"{name}: verifier equals author")
        if not meta.get("evidence"):
            out.append(f"{name}: verified without evidence")
        elif not evidence_has_detail(meta["evidence"]):
            out.append(f"{name}: evidence {meta['evidence']!r} has no detail (give a hash, path, URL or a sentence)")
        if kind == "fix" and not (meta.get("before") and meta.get("after")):
            out.append(f"{name}: fix needs before and after")
        if applies(name, policy.task_tests_from):
            out += check_test_author(name, meta)
        if applies(name, policy.risk_from):
            out += check_risk(name, meta)
    present = "approved_by_user" in meta
    approved = parse_approval(meta.get("approved_by_user"), policy) is not None
    if present and not approved:
        out.append(f"{name}: approved_by_user {meta.get('approved_by_user')!r} is not in the format "
                   "<message id> \"<excerpt of 3+ words>\"")
    if status == "applied" and kind in policy.needs_yes and not approved and not present:
        out.append(f"{name}: kind {kind} applied without approved_by_user")
    applied = status == "applied"
    if "cost_usd" in meta:
        cost = parse_cost(meta["cost_usd"])
        if cost is None:
            out.append(f"{name}: cost_usd {meta['cost_usd']!r} is not a number")
        elif cost > policy.spend_limit and applied and not approved:
            out.append(f"{name}: cost_usd {cost:g} above {policy.spend_limit:g} applied without approved_by_user")
    return out


UNCHECKED_RE = re.compile(r"^\s*[-*] \[ \]", re.M)


def check_applied_tasks(name, meta, tasks_text):
    """A change set to applied must have no open task (`- [ ]`) in tasks.md: applied means done, not merged."""
    if meta and meta.get("status") == "applied":
        n = len(UNCHECKED_RE.findall(tasks_text or ""))
        if n:
            return [f"{name}: status applied but tasks.md has {n} open task(s); finish them or use verified"]
    return []


def run(base=None, root=None, cfg=None):
    root = pathlib.Path(root or common.ROOT)
    policy = Policy(cfg)
    top = root / policy.dir
    if not top.is_dir():
        return []
    out = []
    dirs = sorted(top.glob("*/")) + sorted((top / "archive").glob("*/"))
    records = []
    for d in dirs:
        if not d.is_dir() or d.name == "archive":
            continue
        for f in FILES:
            if not (d / f).exists():
                out.append(f"{d.name}: missing {f}")
        if applies(d.name, policy.task_tests_from) and (d / "tasks.md").exists():
            out += check_task_tests(d.name, (d / "tasks.md").read_text(encoding="utf-8"))
        v = d / "verification.md"
        if v.exists():
            meta = parse_front(v.read_text(encoding="utf-8"))
            records.append((d.name, meta))
            out += check_record(d.name, meta, policy)
            if (d / "tasks.md").exists():
                out += check_applied_tasks(d.name, meta, (d / "tasks.md").read_text(encoding="utf-8"))
    return out + check_reuse(records, policy) + check_numbers([n for n, _ in records])
