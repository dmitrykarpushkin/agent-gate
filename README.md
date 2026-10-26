# stopline

**English** · [Русский](README.ru.md)

[![CI](https://github.com/dmitrykarpushkin/stopline/actions/workflows/ci.yml/badge.svg)](https://github.com/dmitrykarpushkin/stopline/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

**Git hooks that refuse what a coding agent claims but cannot show, judged by rules the agent cannot edit.**

For people who let Claude Code, Codex or another coding agent commit to their repositories without watching every
step. "Tests pass", "no secrets", "verified" are sentences a model writes. stopline turns them into checks that exit 1.

![Real output of examples/demo.sh: a committed key, a commit under the agent's own identity, and a --no-verify push are all refused](docs/demo.svg)

*Real output of `sh examples/demo.sh`, steps 2-4, drawn by [`scripts/render_demo_svg.py`](scripts/render_demo_svg.py).*

## Why use it

- **The agent cannot move the goalposts.** At push time the rules are read from the commit the push builds on, not
  from the agent's working copy. Widen the allowed emails or set the test command to `true` in the same push, and you
  are still judged by the old rules.
- **Tests run on what is pushed, not on what is lying around.** pre-push checks out the pushed commit in a clean
  temporary worktree and runs your test command there.
- **It checks the process, not only the content.** Besides secrets in every added line of every commit, it refuses
  commits under the agent's own identity, attribution trailers, unsigned commits by people who sign, and change
  records "verified" by their own author.
- **No edits before you say go.** A Claude Code hook keeps the agent read-only on feedback and feature requests until
  you answer with a `kind: go` note, and a turn that changed a page cannot end until the agent has looked at a screenshot (it gives up after three
  tries, so a session without a browser does not loop).
- **Small and readable.** Python standard library, no dependencies, 282 tests. A check that crashes counts as red.

## How it compares

stopline is not a hook manager or a secret scanner. It is the set of checks aimed at the ways coding agents go wrong,
and it runs next to the tools below.

| Tool | Better at | What stopline adds |
|---|---|---|
| [pre-commit](https://github.com/pre-commit/pre-commit), [lefthook](https://github.com/evilmartians/lefthook) | Running any linter in any language, caching, speed, years of team use | Rules taken from the base commit; tests on a clean copy of the pushed commit; agent-specific checks |
| [gitleaks](https://github.com/gitleaks/gitleaks), [TruffleHog](https://github.com/trufflesecurity/trufflehog) | Secrets: far larger rule sets, and TruffleHog verifies keys live | Secrets are 1 of 12 checks; the allowlist is read from the base, so a commit cannot allow its own key |
| [Claude Code permissions and sandbox](https://code.claude.com/docs/en/settings) | A real OS boundary, enforced by the client and by admins | A workflow rule permissions cannot express: no edits before the person's go |
| [dcg](https://github.com/Dicklesworthstone/destructive_command_guard), [cc-safety-net](https://github.com/kenryu42/cc-safety-net) | Blocking `rm -rf`-class shell commands, many agents | Process rules on the repository history instead of single commands |

Need only secret scanning? Use gitleaks or TruffleHog. Need isolation? Use the sandbox. They work alongside stopline.

## Quick start

Needs git and Python 3.11+.

```sh
git clone https://github.com/dmitrykarpushkin/stopline && cd stopline
sh examples/demo.sh                      # the six-step demo in a temporary directory, nothing else is touched
cd /path/to/your/repo && sh /path/to/stopline/hooks/install.sh
```

Then copy [`examples/agent-gate.toml`](examples/agent-gate.toml) to the root of your repo and set your emails and test
command (the config file keeps the project's first name). To add the Claude Code gate, copy the four hook entries from
[`examples/claude-settings.json`](examples/claude-settings.json). Details: [docs/configuration.md](docs/configuration.md).

## How it works

```
agent edits  ->  [gate]        Claude Code hook: read-only until the person's "kind: go"
git commit   ->  [pre-commit]  secrets, forbidden script, identity          -> exit 1: commit refused
             ->  [commit-msg]  banned trailers and words                    -> exit 1: commit refused
git push     ->  [pre-push]    rules from the BASE commit, tests in a clean
                               worktree of the pushed commit, 12 checks     -> exit 1: push refused
GitHub       ->  [CI]          the same tests and checks on the server, for pushes that skipped the hooks
```

The twelve checks: secrets, commit identity, signatures, language, supply chain (unpinned `npx -y` and friends),
retiring pinned model ids, hidden text and prompt injection, telemetry flags, instruction-file sync, change records,
required text, gate wiring. Each one, and the failure it answers, is in [docs/checks.md](docs/checks.md).

**Does it help in practice?** One measurement from the private project this code comes from, so an anecdote with
numbers rather than a benchmark: on a "feedback, do not build yet" task, instruction text alone kept the agent from
editing in 0 of 10 runs (two Claude models); with a hook of the same kind (an earlier, simpler version of the gate),
5 of 5. The evaluation harness is not part of this repository.

## Limitations

- **Client-side hooks can be skipped** (`--no-verify`, another `core.hooksPath`, a clone without the install). The
  push check catches what `--no-verify` let through at commit time, but only a server-side job with branch protection
  cannot be skipped. [`.github/workflows/ci.yml`](.github/workflows/ci.yml) is that job.
- **Pattern matching, not proof.** An unknown, encoded or split credential passes; so does a paraphrased injection.
- **The gate is for Claude Code only**, and its Bash check is a speed bump, not a sandbox. The git hooks work for any
  agent that commits.
- **Shape, not truth.** A signature header is checked for presence, not verified; a named verifier is not proof that
  one ran.
- **The tests come from the pushed tree**, so an agent can weaken a test in the same push. Review test diffs.
- **Not measured:** false-positive rates on real repositories, run time on large histories.

The full list, with the design decisions behind each check: [docs/design.md](docs/design.md).

## Status and provenance

A personal project, used on my own repositories, not by a team. It was extracted on 2026-10-26 from a private
monorepo where it guarded agents working on my projects. There, 168 commits touched the checks, hooks and gate between
2026-10-18 and 2026-10-26; 165 of them were made by agents working under these checks. The private history
mentions other work and internal ids, so it is not published; what changed when is in [CHANGELOG.md](CHANGELOG.md).

Related: [foureyes](https://github.com/dmitrykarpushkin/foureyes) (no agent judges its own work) and
[needsyou](https://github.com/dmitrykarpushkin/needsyou) (one screen for what needs a person).

## Documentation

[Checks and hooks](docs/checks.md) · [Configuration](docs/configuration.md) · [Design and limits](docs/design.md) ·
[Full demo transcript](docs/example-session.md) · [Repository layout](docs/layout.md) · [Rules](rules.toml)

---

Working in this repo with a coding agent? Its rules are in [AGENTS.md](AGENTS.md).

MIT License · [Dmitry Karpushkin](https://github.com/dmitrykarpushkin)
