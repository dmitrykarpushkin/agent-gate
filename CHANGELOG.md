# Changelog

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Dates before 0.1.0 come from the history of
the private monorepo this code was extracted from; that history is not published.

## [Unreleased]

### Changed
- Renamed the project from agent-gate to **stopline**. The launcher is `bin/stopline` and output lines start with
  `stopline`; `bin/agent-gate`, the `agent_gate` package, the `agent-gate.toml` config file and the
  `.agent-gate/` allowlist keep their names, so existing setups keep working. The gate wiring check accepts either
  name.
- The workflow is now `.github/workflows/ci.yml`, named CI.
- Rewrote the README for people, added a Russian version (`README.ru.md`, exempt from the language check), moved
  reference material to `docs/` and rules for coding agents to `AGENTS.md`.

### Added
- `scripts/render_demo_svg.py` draws `docs/demo.svg` from a real run of `examples/demo.sh`.
- Social preview image `docs/social-preview.png`.

## [0.1.0] - 2026-10-26

First public release: three git hooks, a runner with twelve checks, the Claude Code gate, 282 tests, `examples/demo.sh`
and a GitHub Actions job that repeats the checks on the server.

## Before the public release (private monorepo)

- **2026-10-24** - The commit-msg hook refuses banned words and a forbidden script at commit time instead of only at
  push. pre-push fetches the full history first when the clone is shallow.
- **2026-10-22** - The gate: feedback and feature requests close the repository for edits until the person's go, and a
  page change needs a looked-at screenshot. A check that the gate stays wired into the agent settings.
- **2026-10-21** - Signature check for people who must sign; a check that every instruction file carries the same copy
  of the shared rules.
- **2026-10-19** - pre-commit hook for staged secrets. Checks for unpinned package runners, retiring pinned models,
  hidden text in files agents read, and telemetry settings that export prompts. After test fixtures once landed in the
  host repository, tests run git only through a sandbox guard.
- **2026-10-18** - First checks with tests: secrets, commit identity, language, change records. pre-push hook with an
  installer, written after a red commit reached main.
