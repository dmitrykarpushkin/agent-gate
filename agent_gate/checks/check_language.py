"""Rule one-language-repo: added lines, file names and commit messages must not contain a forbidden script.

Config [language]: forbid (a script name from SCRIPTS, or a list of ["0x400", "0x52f"] ranges; without it the check is
off), exempt_paths (a path equal to an entry, or under an entry that ends with "/"), old_lines_only (files whose lines
that already exist at the base commit stay allowed, so an old file can be cleaned up over time).
"""
import re, subprocess
from .. import common

SCRIPTS = {
    # Cyrillic with Supplement, Extended-C, Extended-A, Extended-B
    "cyrillic": ((0x400, 0x52F), (0x1C80, 0x1C8F), (0x2DE0, 0x2DFF), (0xA640, 0xA69F)),
    "greek": ((0x370, 0x3FF), (0x1F00, 0x1FFF)),
    "cjk": ((0x3040, 0x30FF), (0x3400, 0x4DBF), (0x4E00, 0x9FFF), (0xAC00, 0xD7AF)),
}


def ranges_regex(ranges):
    return re.compile("[" + "".join(re.escape(chr(a)) + "-" + re.escape(chr(b)) for a, b in ranges) + "]")


CYRILLIC = ranges_regex(SCRIPTS["cyrillic"])


class Policy:
    """The [language] table, resolved."""

    def __init__(self, cfg):
        sec = (cfg or {}).get("language") or {}
        forbid = sec.get("forbid")
        if not forbid:
            self.name, self.rx = None, None
        elif isinstance(forbid, str):
            if forbid not in SCRIPTS:
                raise ValueError(f"[language] forbid: unknown script {forbid!r}, use one of {sorted(SCRIPTS)} or a list of ranges")
            self.name, self.rx = forbid, ranges_regex(SCRIPTS[forbid])
        else:
            self.name = "forbidden script"
            self.rx = ranges_regex([(int(str(a), 0), int(str(b), 0)) for a, b in forbid])
        self.exempt = tuple(sec.get("exempt_paths", ()))
        self.old_only = tuple(sec.get("old_lines_only", ()))

    @property
    def on(self):
        return self.rx is not None

    def label(self):
        return self.name.capitalize() if self.name in SCRIPTS else self.name

    def found(self, text):
        return bool(self.rx and self.rx.search(text))

    def legacy(self, path):
        return any(path == e or (e.endswith("/") and path.startswith(e)) for e in self.exempt)


def old_lines(policy, base):
    res = {}
    for p in policy.old_only:
        try:
            res[p] = set(common.git("show", f"{base}:{p}").splitlines())
        except subprocess.CalledProcessError:
            res[p] = set()
    return res


def check_paths(policy, paths):
    """A file name outside the exempt paths must not contain the script, whatever the file holds."""
    return [f"{p}: {policy.label()} in file name" for p in dict.fromkeys(paths) if p and not policy.legacy(p) and policy.found(p)]


def check_lines(policy, pairs, old=None):
    if not policy.on:
        return []
    old = old or {}
    pairs = list(pairs)
    out = check_paths(policy, (p for p, _ in pairs))
    return out + [f"{p}: {policy.label()} in added line: {l[:60]}" for p, l in pairs
                  if p and not policy.legacy(p) and policy.found(l) and not (p in policy.old_only and l in old.get(p, set()))]


def run(base, cfg=None):
    policy = Policy(cfg)
    if not policy.on:
        return []
    found = check_paths(policy, common.added_paths(base)) + check_lines(policy, common.added_lines(base), old_lines(policy, base))
    return list(dict.fromkeys(found))  # a path with added lines is found twice


def staged_paths():
    """Names of files added, modified or renamed in the index of ROOT."""
    out = subprocess.run(["git", "-c", "core.quotepath=false", "diff", "--cached", "--name-only", "--diff-filter=AMR", "-z"],
                         cwd=common.ROOT, capture_output=True, check=True).stdout.decode("utf-8", errors="replace")
    return [n for n in out.split("\0") if n]


def staged_binary():
    """Names of staged files git treats as binary (numstat prints - - for them); their bytes are not text to check."""
    out = subprocess.run(["git", "-c", "core.quotepath=false", "diff", "--cached", "--numstat", "--no-renames", "-z"],
                         cwd=common.ROOT, capture_output=True, check=True).stdout.decode("utf-8", errors="replace")
    return {r.split("\t", 2)[2] for r in out.split("\0") if r.startswith("-\t-\t")}


def run_staged(cfg=None):
    """Same rule on the index; the old lines of old_lines_only files are read from HEAD. Binary files are skipped."""
    policy = Policy(cfg)
    if not policy.on:
        return []
    binary = staged_binary()
    pairs = [(p, l) for p, l in common.staged_lines() if p not in binary]
    return list(dict.fromkeys(check_paths(policy, staged_paths()) + check_lines(policy, pairs, old_lines(policy, "HEAD"))))
