"""Command line of stopline. Run it through the launcher, which puts this package on the path in isolated mode:

  python3 -I path/to/stopline/bin/stopline run [BASE]       every enabled check on BASE..HEAD (default HEAD~1)
  python3 -I path/to/stopline/bin/stopline staged           the pre-commit checks on the index
  python3 -I path/to/stopline/bin/stopline msg FILE         the commit-msg checks on a message file
  python3 -I path/to/stopline/bin/stopline tree [PATH]      secret scan of every tracked file (not a diff)
  python3 -I path/to/stopline/bin/stopline pre-push REMOTE  the pre-push hook (reads git's ref lines on stdin)
  python3 -I path/to/stopline/bin/stopline gate MODE        the Claude Code agent gate (prompt, pretool, log, stop)

With the stopline clone on PYTHONPATH, `python3 -m agent_gate ...` is the same. All commands work on the git work tree of the
current directory.
"""
import re, subprocess, sys
from . import common, config, gate, prepush, run_all
from .checks import check_commits, check_language, check_secrets

USAGE = __doc__


def head_config(root):
    """Rules for commit-time hooks: the committed file in HEAD (a commit cannot relax its own rules), else the work tree."""
    return config.load(root, "HEAD")[0]


def ident_email(var):
    """The email of `git var GIT_AUTHOR_IDENT` or GIT_COMMITTER_IDENT for the commit about to be made."""
    r = subprocess.run(["git", "var", var], cwd=common.ROOT, capture_output=True, text=True)
    m = re.search(r"<([^>]*)>", r.stdout)
    return m.group(1) if m else ""


def staged():
    common.set_root(run_all.toplevel())
    cfg = head_config(common.ROOT)
    names = config.enabled(cfg)
    found = []
    if "secrets" in names:
        found += check_secrets.run_staged(cfg)
    if "language" in names:
        found += check_language.run_staged(cfg)
    if "commits" in names:
        found += check_commits.Rules(cfg).identity_problems("index", ident_email("GIT_AUTHOR_IDENT"), ident_email("GIT_COMMITTER_IDENT"))
    for p in found:
        print(p)
    if found:
        print("stopline pre-commit: commit blocked")
    return 1 if found else 0


def message_text(path):
    lines = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            if line.startswith("# " + "-" * 24 + " >8 "):  # commit -v: the diff below the scissors line is not the message
                break
            if not line.startswith("#"):
                lines.append(line)
    return "".join(lines)


def msg(path):
    common.set_root(run_all.toplevel())
    cfg = head_config(common.ROOT)
    if "commits" not in config.enabled(cfg):
        return 0
    found = [p.split(": ", 1)[1] for p in check_commits.Rules(cfg).message_problems("message", message_text(path))]
    for p in found:
        print("stopline commit-msg: " + p, file=sys.stderr)
    return 1 if found else 0


def tree(path=None):
    root = common.set_root(run_all.toplevel(path or "."))
    skip = check_secrets.settings(config.from_tree(root))[2]
    found = check_secrets.run_tree(root, skip)
    print("\n".join(found) or "no secrets found in the tree")
    return 1 if found else 0


def main(argv):
    cmd, rest = (argv[0], argv[1:]) if argv else ("", [])
    try:
        if cmd == "run" and len(rest) <= 1:
            return run_all.run(rest[0] if rest else None)
        if cmd == "staged" and not rest:
            return staged()
        if cmd == "msg" and len(rest) == 1:
            return msg(rest[0])
        if cmd == "tree" and len(rest) <= 1:
            return tree(rest[0] if rest else None)
        if cmd == "pre-push":
            return prepush.main(rest)
        if cmd == "gate":
            return gate.main(rest)
    except config.ConfigError as e:
        print(f"stopline: {e}", file=sys.stderr)
        return 1
    print(USAGE, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
