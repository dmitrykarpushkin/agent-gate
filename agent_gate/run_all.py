"""Run every enabled check on base..HEAD of a repository. Exit status 1 on any problem, also when a check crashes."""
import subprocess, sys
from . import common, config
from .checks import ALL


def usable_base(base, root):
    """True when base is a real commit and not the all-zero placeholder."""
    return set(base) != {"0"} and subprocess.run(["git", "rev-parse", "--verify", "-q", base + "^{commit}"],
                                                 cwd=root, capture_output=True).returncode == 0


def run_checks(checks, base, cfg=None):
    """checks: (name, module) pairs. A check that raises is reported as a problem and the rest still run. Returns (bad, lines)."""
    bad, lines = False, []
    for name, mod in checks:
        try:
            problems = mod.run(base, cfg=cfg)
        except Exception as e:  # noqa: BLE001
            problems = [f"check crashed: {type(e).__name__}: {e}"]
        lines.append(f"{name}: {'ok' if not problems else str(len(problems)) + ' problem(s)'}")
        lines.extend(f"  - {p}" for p in problems)
        bad |= bool(problems)
    return bad, lines


def toplevel(path="."):
    r = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=path, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit("agent-gate: not inside a git work tree")
    return r.stdout.strip()


def run(base=None, root=None, out=None, err=None):
    """Judge base..HEAD of root (default: the work tree of the current directory). Returns the exit status."""
    out, err = out or sys.stdout, err or sys.stderr
    root = common.set_root(root or toplevel())
    base = base or "HEAD~1"
    if not usable_base(base, root):
        print(f"agent-gate: base {base!r} is not usable, falling back to HEAD~1", file=err)
        base = "HEAD~1"
        if not usable_base(base, root):
            print("agent-gate: HEAD has no parent; pass a base commit", file=err)
            return 1
    try:
        cfg, source = config.load(root, base)
        names = config.enabled(cfg)
    except config.ConfigError as e:
        print(f"agent-gate: {e}", file=out)
        return 1
    print(f"agent-gate: {len(names)} checks on {base[:12]}..HEAD, rules from {source}", file=out)
    bad, lines = run_checks([(n, ALL[n]) for n in names], base, cfg)
    print("\n".join(lines), file=out)
    return 1 if bad else 0
