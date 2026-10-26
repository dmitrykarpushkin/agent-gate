"""The pre-push hook: refuses a push to a protected branch when the repo's tests or the checks are red for the pushed commit.

git calls the hook with the remote name and URL and writes one line per pushed ref on stdin:
`<local ref> <local sha> <remote ref> <remote sha>`. For each ref that goes to a protected branch:
  1. base = the remote sha when this clone has it; otherwise (new branch, empty remote, force push, a remote sha this
     clone never fetched) the parent of the oldest pushed commit that the remote-tracking branch does not have, so the
     whole range is judged and not only the tip;
  2. the configuration is read from the base commit ([push] branches, test_command and every check's table), so the push
     cannot relax the rules it is judged by; a base without agent-gate.toml falls back to the pushed commit's file;
  3. the pushed commit (not the working copy) is checked out in a temporary worktree, test_command runs there, then the
     checks run on base..pushed commit.
Only the tip's tests run: a red commit in the middle of a push with a green tip passes the test step (the checks still
judge every commit of the range).
"""
import os, shlex, subprocess, sys, tempfile
from . import config, run_all

ZERO = "0" * 40
# A hook run from a linked worktree gets GIT_DIR and friends; everything below finds the repository from its directory.
REPO_VARS = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR", "GIT_OBJECT_DIRECTORY",
             "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_NAMESPACE", "GIT_PREFIX")


def git(*args, cwd=None, check=False):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=check)


def is_commit(sha, cwd=None):
    return git("cat-file", "-e", sha + "^{commit}", cwd=cwd).returncode == 0


def push_base(sha, remote, branch, cwd=None):
    """The base for a push whose remote sha is unknown here: the parent of the oldest commit of sha that the remote-tracking
    branch lacks (the remote's main for a new branch; the oldest commit itself when it is a root commit). None when every
    commit is already there."""
    ref = None
    for candidate in (f"refs/remotes/{remote}/{branch}", f"refs/remotes/{remote}/main", f"refs/remotes/origin/{branch}", "refs/remotes/origin/main"):
        if git("rev-parse", "-q", "--verify", candidate, cwd=cwd).returncode == 0:
            ref = candidate
            break
    args = ["rev-list", "--topo-order", sha] + (["--not", ref] if ref else [])
    commits = git(*args, cwd=cwd).stdout.split()
    if not commits:
        return None
    oldest = commits[-1]
    parent = git("rev-parse", "-q", "--verify", oldest + "^", cwd=cwd)
    return parent.stdout.strip() if parent.returncode == 0 else oldest


def rules_for(root, base, sha):
    cfg = config.from_ref(root, base) if is_commit(base, root) else None
    return cfg if cfg is not None else (config.from_ref(root, sha) or {})


def judge(root, remote, line, tmp, out, err):
    """Returns 0 (green or not protected) or 1 (blocked) for one stdin line."""
    parts = line.split()
    if len(parts) != 4:
        return 0
    _local_ref, sha, remote_ref, remote_sha = parts
    if sha == ZERO:
        return 0  # a deletion; nothing to test
    branch = remote_ref[len("refs/heads/"):] if remote_ref.startswith("refs/heads/") else None
    if remote_sha != ZERO and is_commit(remote_sha, root):
        base = remote_sha
    else:
        base = push_base(sha, remote, branch or "main", root) or sha + "~1"
    try:
        cfg = rules_for(root, base, sha)
    except config.ConfigError as e:
        print(f"stopline pre-push: {e}; push blocked", file=err)
        return 1
    branches = config.get(cfg, "push.branches", ["main"])
    if branch not in branches:
        return 0
    wt = os.path.join(tmp, "wt")
    if git("worktree", "add", "--detach", "-q", wt, sha, cwd=root).returncode != 0:
        print(f"stopline pre-push: cannot check out {sha}; push blocked", file=err)
        return 1
    try:
        print(f"stopline pre-push: {sha[:12]} -> {branch}, judged against {base[:12]}", file=out)
        test = config.get(cfg, "push.test_command")
        if test:
            r = subprocess.run(test if isinstance(test, str) else shlex.join(test), shell=True, cwd=wt, capture_output=True, text=True)
            if r.returncode != 0:
                tail = (r.stdout + r.stderr).splitlines()[-40:]
                print("\n".join(tail), file=err)
                print(f"stopline pre-push: tests are red for {sha[:12]}, push blocked", file=err)
                return 1
            print(f"stopline pre-push: tests green ({test})", file=out)
        if run_all.run(base, root=wt, out=out, err=err) != 0:
            print(f"stopline pre-push: checks are red for {sha[:12]}, push blocked", file=err)
            return 1
        return 0
    finally:
        git("worktree", "remove", "--force", wt, cwd=root)


def main(argv, stdin=None, out=None, err=None):
    stdin, out, err = stdin or sys.stdin, out or sys.stdout, err or sys.stderr
    for stream in (out, err):  # git shows both; line buffering keeps their lines in the order they were written
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(line_buffering=True)
    for v in REPO_VARS:
        os.environ.pop(v, None)
    remote = argv[0] if argv else "origin"
    root = run_all.toplevel()
    if git("rev-parse", "--is-shallow-repository", cwd=root).stdout.strip() == "true":
        # a shallow clone lacks the base commits the checks compare against; get the full history first
        print("stopline pre-push: shallow clone, fetching the full history first", file=err)
        if git("fetch", "-q", "--unshallow", remote, cwd=root).returncode != 0:
            print(f"stopline pre-push: cannot unshallow from {remote}, push blocked", file=err)
            return 1
    status = 0
    for line in stdin.read().splitlines():
        with tempfile.TemporaryDirectory() as tmp:
            status |= judge(root, remote, line, tmp, out, err)
    return status
