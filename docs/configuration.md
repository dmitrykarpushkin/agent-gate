# Configuration

One file, `agent-gate.toml`, at the root of the guarded repo (full example: `examples/agent-gate.toml`). A table
that is absent switches its check off, except `secrets`, `supply_chain`, `pinned_models` and `telemetry_flags`,
which run with built-in defaults. `[checks] enabled` picks the checks; `[push]` names the protected branches and the
test command.

**Rules come from the base commit.** At push time the file is read from the commit the push builds on, not from the
pushed commit. An agent that is told "the push is red" and edits `agent-gate.toml` to widen the allowed emails, skip a
path or replace the test command with `true` is still judged by the old rules; the change takes effect for the next
push. The secrets allowlist (`.agent-gate/secret-paths-allow.txt`, one `glob  # reason` per line, a reason is
required) works the same way: a commit cannot allow its own key file. Commit-time hooks read the file from HEAD
(the work-tree file until a commit has one).

The file keeps the project's first name, `agent-gate.toml`, and the secrets allowlist stays at
`.agent-gate/secret-paths-allow.txt`, so repositories set up before the rename keep working.

## Wiring the gate into Claude Code

The gate runs as four Claude Code hooks (UserPromptSubmit, PreToolUse, PostToolUse, Stop). Put the entries from
[`examples/claude-settings.json`](../examples/claude-settings.json) into `.claude/settings.json` of the guarded repo
and replace `/path/to/stopline` with the path of your clone. Add a `[gate_wiring]` table to `agent-gate.toml` and the
push check fails when someone removes one of the four entries.

## Server-side job

[`.github/workflows/ci.yml`](../.github/workflows/ci.yml) runs the tests, `stopline run` on the pushed range and a
full-tree secret scan on every push and pull request (Python 3.11 and 3.13). Pair it with a branch protection rule that
requires the job before merging into main: that is the only part a client cannot skip.
