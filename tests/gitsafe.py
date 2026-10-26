"""Keeps test fixtures away from the repository the tests live in.

A git hook run from a linked worktree (pre-push, pre-commit) exports GIT_DIR, and pre-commit also GIT_INDEX_FILE.
Every git call a test makes inherits them, so `git init`, `git config`, `git commit` and `git push origin` in a
temporary fixture act on the enclosing repository and push to its real origin. That happened once when the test suite
ran inside a pre-push hook: fixture commits landed in the real repository.
Importing this module drops those variables from os.environ, so the test process and everything it starts
find their repository from the working directory again. assert_sandbox() is a second net for fixtures that push.
"""
import os, pathlib, re, subprocess

REPO_VARS = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR", "GIT_OBJECT_DIRECTORY",
             "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_NAMESPACE", "GIT_PREFIX")
HERE = pathlib.Path(__file__).resolve().parent


CONFIG_PREFIXES = ("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_")
CONFIG_VARS = ("GIT_CONFIG_PARAMETERS", "GIT_CONFIG_COUNT")


def scrub(env=os.environ):
    """Drop repository-selecting and injected-config variables (a hook's `git -c` leaves GIT_CONFIG_PARAMETERS)."""
    for v in list(env):
        if v in REPO_VARS or v in CONFIG_VARS or v.startswith(CONFIG_PREFIXES):
            env.pop(v, None)
    return env


scrub()


def _git(cwd, *a):
    r = subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True, env=scrub(dict(os.environ)))
    return r.stdout.strip() if r.returncode == 0 else ""


def _common_dir(cwd):
    d = _git(cwd, "rev-parse", "--path-format=absolute", "--git-common-dir")
    return pathlib.Path(d).resolve() if d else None


def _origin_path(repo, url):
    """The local directory an origin url points at, resolved; None when it is not a local path."""
    if url.startswith("file://"):
        url = url[len("file://"):]
    elif re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://", url) or re.match(r"^[^/]+@[^/]+:", url):
        return None
    p = pathlib.Path(url)
    return (pathlib.Path(repo) / p).resolve() if not p.is_absolute() else p.resolve()


def assert_sandbox(repo):
    """Refuse a fixture repo that is the enclosing repository, or whose origin is remote or is the enclosing repository."""
    mine, outer = _common_dir(repo), _common_dir(HERE)
    if mine is None or (outer is not None and mine == outer):
        raise RuntimeError("test fixture %s resolves to the enclosing repository %s" % (repo, outer))
    url = _git(repo, "config", "--get", "remote.origin.url")
    if not url:
        return
    target = _origin_path(repo, url)
    if target is None:
        raise RuntimeError("test fixture %s has a non-local origin %s" % (repo, url))
    if outer is not None:
        probe = target
        while not probe.exists() and probe != probe.parent:
            probe = probe.parent
        if probe == outer or outer in probe.parents or _common_dir(probe) == outer:
            raise RuntimeError("test fixture %s has origin %s that is the enclosing repository %s" % (repo, url, outer))
