# Rules for an AI agent working in this repository

Humans: start with [README.md](README.md). This file is for coding agents (Claude Code, Codex and others).

## What this repository is

stopline: git hooks (pre-commit, commit-msg, pre-push), a runner with twelve checks and a Claude Code hook ("the
gate"). Python 3.11+ standard library only. The package is `agent_gate/` (the project's first name, kept so imports and
configs do not break); the launcher is `bin/stopline`, and `bin/agent-gate` is the same launcher under the old name.

## Before you change anything

- Install the hooks on this clone: `sh hooks/install.sh`. The repo guards itself with its own `agent-gate.toml`.
- Read [docs/checks.md](docs/checks.md) and [docs/design.md](docs/design.md); each rule and its limits are in
  `rules.toml`.

## Rules

1. **No dependencies.** Standard library only. Hooks run `python3 -I`; do not rely on `PYTHONPATH` or the current
   directory being importable.
2. **Fail closed.** A check that crashes, a config that does not parse, or an unknown push base must make the result
   red, never green. Do not add a `try/except: pass` around a check.
3. **Every check is `run(...) -> list[str]`**, empty list means green. A new check needs: a module in
   `agent_gate/checks/`, tests in `tests/`, an entry in `rules.toml` (with its `limits`), and a line in
   `docs/checks.md`.
4. **Tests must not touch the host repo.** Any test that runs git imports `tests/gitsafe.py`; a test enforces this.
5. **English only** in code, comments, commit messages and file names. The one exception is `README.ru.md`, the
   Russian translation of the README (exempt in `agent-gate.toml`). Keep it in step with `README.md`.
6. **Keep `## Limitations` in README.md.** The `required_text` check refuses a push that drops it. When behaviour
   changes, update the limits in README.md, README.ru.md and `docs/design.md` together.
7. **Do not loosen `agent-gate.toml` to make a push green.** Rules are read from the base commit, so it does not work
   anyway; fix the cause.
8. **Claim only what the code does.** The gate is implemented and tested for Claude Code hook events only. The secrets
   check is pattern matching, not verification.

## Checks to run before you say "done"

```sh
python3 -m unittest discover -s tests          # all tests, about a minute
sh examples/demo.sh                            # the six-step demo, steps 2-4 must end in (exit 1)
python3 -I bin/stopline run origin/main        # the repo's own checks on your range
```

If the output of the demo changed, regenerate the picture: `python3 scripts/render_demo_svg.py` (writes
`docs/demo.svg`), and `docs/example-session.md` if the change is visible there.
