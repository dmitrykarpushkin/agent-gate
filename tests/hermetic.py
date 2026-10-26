"""Imported first by every test file.

1. Puts the repository root on sys.path, so `import agent_gate` works from any working directory.
2. Imports gitsafe, which drops GIT_DIR and the other variables a git hook exports (fixtures must never act on the
   enclosing repository).
3. Makes fixture repos independent of the account's own git settings: a global commit.gpgsign=true with an external
   signer would make every fixture commit slow or fail. The variables below beat the config files and are inherited by
   every subprocess, including the hooks the tests run.
"""
import os, pathlib, sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
HERE = pathlib.Path(__file__).resolve().parent
for p in (str(ROOT), str(HERE)):
    if p not in sys.path:
        sys.path.insert(0, p)

import gitsafe  # noqa: E402,F401

# 4. An identity exported by the caller (GIT_AUTHOR_EMAIL and friends) would beat the identities fixtures set with
#    `git config`; drop it. Fixture calls that need one pass it through git_env().
for _var in ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_AUTHOR_DATE", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL", "GIT_COMMITTER_DATE"):
    os.environ.pop(_var, None)

LAUNCHER = ROOT / "bin" / "agent-gate"
# RFC 2606 reserved domain: these addresses can never belong to anyone
OWNER = "owner@example.invalid"
BOT = "bot@example.invalid"
STRANGER = "stranger@example.invalid"

_SETTINGS = (("commit.gpgsign", "false"), ("tag.gpgsign", "false"))


def apply():
    n = int(os.environ.get("GIT_CONFIG_COUNT") or 0)
    for key, value in _SETTINGS:
        os.environ["GIT_CONFIG_KEY_%d" % n] = key
        os.environ["GIT_CONFIG_VALUE_%d" % n] = value
        n += 1
    os.environ["GIT_CONFIG_COUNT"] = str(n)


if not os.environ.get("AGENT_GATE_TESTS_HERMETIC"):
    os.environ["AGENT_GATE_TESTS_HERMETIC"] = "1"
    apply()


def git_env(email=OWNER, name="n"):
    """Environment for a fixture git call: no global or system config, a fixed identity."""
    return {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,
            "GIT_AUTHOR_NAME": name, "GIT_AUTHOR_EMAIL": email, "GIT_COMMITTER_NAME": name, "GIT_COMMITTER_EMAIL": email}
