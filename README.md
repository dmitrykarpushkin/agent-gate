# agent-gate

Mechanical, tested guardrails for git repositories where LLM coding agents commit.
**The agent says it is done; the hook decides.**

agent-gate is a set of git hooks (pre-commit, commit-msg, pre-push), a runner with twelve checks, and a Claude Code
hook ("the gate") that stops an agent from editing the repository before a person has said go. Python 3.11+ standard
library only, no dependencies.

## Why it exists

A coding agent's report is not evidence. "Tests pass", "no secrets", "verified" are sentences the model produces, and
an instruction in CLAUDE.md or AGENTS.md is advice the model may or may not follow on a given run. What holds every
time is a check the agent cannot talk its way past: a hook that exits 1.

In the personal research project this code comes from (orchestrating Claude and Codex agents on one person's repos),
the rules started as text in instruction files. Each check here is one of those rules turned into code; several
were written right after the text version had been broken (they are named in the tables below). One measurement from
that project, for the gate: on a "feedback, do not build yet" task, the instruction text alone kept the agent from
editing the source in 0 of 10 runs (two Claude models, with and without the core rules in the prompt, session memory
off); with a PreToolUse hook of the same kind wired in (an earlier, simpler version of `gate.py`), 5 of 5. The sample
is small and the evaluation harness is not part of this repository, so treat it as an anecdote with numbers, not a
benchmark.

## What it checks

| Check | Refuses | Failure it answers |
|---|---|---|
| `secrets` | Credential shapes (provider API keys, tokens, private keys, URLs with passwords, tunnel hosts, password assignments) in **every line added by any commit** of the push, key/.env file names, blobs over 5 MB | A token pasted into a note "for a minute": deleted in the next commit, still in history. Also read: UTF-16 files, files git treats as binary, merge resolutions |
| `commits` | Authors and committers outside an allow list; banned trailers and words in messages and names, after Unicode normalisation | Commits landed under a tool's own identity from clones where setup was skipped; attribution trailers added automatically |
| `signatures` | Commits by listed people without a signature header | Work pushed through an API or a fresh clone, unsigned, under a person's name |
| `language` | Text in a forbidden script in added lines, file names, commit messages | Agents answering in the operator's language inside the code and history of an English-only repo |
| `supply_chain` | `npx -y`, `uvx`, `bunx`, `pipx run` without an exact version (also in MCP server configs), `npm install` without `--ignore-scripts`, `package.json` without a lockfile | Package compromises that ship through install scripts and floating versions, pulled in by an agent's "just run it" |
| `pinned_models` | A pinned model id that is deprecated and retires within 60 days | Unattended jobs that break on the day a pinned model is retired |
| `hidden_text` | Zero-width and bidi characters, HTML comments, "ignore previous instructions" phrases in files agents read as input | Prompt injection hidden in task files and notes that agents ingest |
| `telemetry_flags` | Settings that switch on export of prompts, tool content or raw API bodies (`OTEL_LOG_*`) | Secrets that an agent saw leaving the machine through a telemetry backend |
| `core_sync` | An instruction file (CLAUDE.md, AGENTS.md, ...) whose copy of the shared core rules differs from the source | Two agents in one repo following two different versions of the rules |
| `changes` | Change records that are "verified" by their own author, with evidence "ok", or applied without a cited yes for irreversible kinds | Agents grading their own work; one approval reused for a different action |
| `required_text` | A listed document that lost a listed phrase | A "tidy-up" edit that silently drops the section a reviewer agent is told to follow |
| `gate_wiring` | Claude Code settings that no longer run the gate in all four hook events | The silent way a guard stops holding: someone removes the hook |

And the hooks around them:

| Hook | Does |
|---|---|
| `pre-commit` | `secrets` and `language` on the index, plus the identity of the commit about to be made |
| `commit-msg` | Banned trailers and words, forbidden script, in the message |
| `pre-push` | For a push to a protected branch: checks out the **pushed commit** (not the working copy) in a temporary worktree, runs the repo's test command there, then every enabled check on base..pushed. Born from a red commit that reached main because `git push` ran after a failed test in the same command chain |
| gate (Claude Code) | Feedback and feature requests become requirements and options first: edits are denied until a `kind: go` note. A page change cannot end the turn until a rendered PNG was read; the Stop hook gives up after 3 blocks in a session (`screenshot_cap`), so a session without a browser cannot loop forever |

## How it fits together

```
 agent (Claude Code, Codex, ...)                         person
   |  Edit / Write / Bash                                  |  "kind: go"
   v                                                       v
 [gate] PreToolUse: deny while intake is open  <---- UserPromptSubmit
   |
   v  git commit
 [pre-commit] secrets, language, identity  ---- exit 1: commit refused
 [commit-msg] banned trailers and words    ---- exit 1: commit refused
   |
   v  git push origin main
 [pre-push]  base = what the remote already has
             rules = agent-gate.toml AS COMMITTED IN THE BASE
             worktree of the pushed sha -> test_command -> 12 checks on base..sha
                                         ---- exit 1: push refused
```

Every check is a module with `run(...) -> list[str]`; an empty list is green. The runner (`agent_gate/run_all.py`)
reports a crashing check as a problem instead of skipping it.

## Quickstart

```sh
git clone <this repo> agent-gate
cd agent-gate && python3 -m unittest discover -s tests     # the tests of agent-gate itself

cd /path/to/your/repo
sh /path/to/agent-gate/hooks/install.sh                    # sets core.hooksPath to agent-gate/hooks
cp /path/to/agent-gate/examples/agent-gate.toml .          # edit emails, test command, paths; delete unused tables
python3 -I /path/to/agent-gate/bin/agent-gate run origin/main   # every check on origin/main..HEAD, by hand
python3 -I /path/to/agent-gate/bin/agent-gate tree              # secret scan of every tracked file
```

The gate is wired in `.claude/settings.json` of the guarded repo; `examples/claude-settings.json` has the four
hook entries. `sh examples/demo.sh` runs the session below in a temporary directory.

## Example session

Real output of `sh examples/demo.sh` (temporary directory shown as `$DEMO`, the agent-gate clone as `<agent-gate>`;
the green check list of step 1 is the same as in step 5 and cut here). Step 6 feeds the gate the JSON events Claude
Code sends to hooks. It switches `require_citation` off, visibly: in a terminal the prompt comes straight from the
person. Behind an orchestrator that relays messages (where a "go" could be typed by another agent), leave it on, and
a go counts only with a cited message id of the person:

```
== 1. install the hooks and push the rules

$ sh <agent-gate>/hooks/install.sh
agent-gate hooks installed for $DEMO/repo (core.hooksPath=<agent-gate>/hooks)
(exit 0)

$ git add -A && git commit -qm "add rules and tests" && git push -q origin HEAD:main
agent-gate pre-push: 39f82b945fbb -> main, judged against 39f82b945fbb
agent-gate pre-push: tests green (python3 -m unittest discover -s tests)
agent-gate: 12 checks on 39f82b945fbb..HEAD, rules from agent-gate.toml at 39f82b945fbb
secrets: ok
... (11 more lines: every check ok)
(exit 0)

== 2. the agent commits a key (a fake AWS key id, built at runtime)

$ git add settings.py && git commit -qm "add settings"
settings.py: possible aws key id
agent-gate pre-commit: commit blocked
(exit 1)

== 3. the agent commits under its own identity

$ git add hello.py && git -c user.email=coding-agent@example.invalid commit -qm "add hello"
index: author coding-agent@example.invalid is not an allowed identity
index: committer coding-agent@example.invalid is not an allowed identity
agent-gate pre-commit: commit blocked
(exit 1)

== 4. the agent skips the commit hooks (--no-verify) and pushes: a foreign author and an unsigned commit by the owner

$ git -c user.email=coding-agent@example.invalid commit -q --no-verify -m "add hello" && git -c user.email=owner@example.invalid commit -q --allow-empty --no-verify -m "owner work, unsigned" && git push -q origin HEAD:main
agent-gate pre-push: f5061ef129f0 -> main, judged against 39f82b945fbb
agent-gate pre-push: tests green (python3 -m unittest discover -s tests)
agent-gate: 12 checks on 39f82b945fbb..HEAD, rules from agent-gate.toml at 39f82b945fbb
secrets: ok
commits: 2 problem(s)
  - f749c57: author coding-agent@example.invalid is not an allowed identity
  - f749c57: committer coding-agent@example.invalid is not an allowed identity
signatures: 1 problem(s)
  - f5061ef: commit by owner@example.invalid without a signature
language: ok
supply_chain: ok
pinned_models: ok
hidden_text: ok
telemetry_flags: ok
core_sync: ok
changes: ok
required_text: ok
gate_wiring: ok
agent-gate pre-push: checks are red for f5061ef129f0, push blocked
error: failed to push some refs to '$DEMO/remote.git'
(exit 1)

== 5. the same work, committed by the bot and signed by the owner, goes through

$ git add hello.py && git commit -qm "add hello" && git -c user.email=owner@example.invalid -c user.signingkey=owner@example.invalid commit -q -S --allow-empty -m "owner work, signed" && git push -q origin HEAD:main
agent-gate pre-push: 6d35efe8a5ce -> main, judged against 39f82b945fbb
agent-gate pre-push: tests green (python3 -m unittest discover -s tests)
agent-gate: 12 checks on 39f82b945fbb..HEAD, rules from agent-gate.toml at 39f82b945fbb
secrets: ok
commits: ok
signatures: ok
language: ok
supply_chain: ok
pinned_models: ok
hidden_text: ok
telemetry_flags: ok
core_sync: ok
changes: ok
required_text: ok
gate_wiring: ok
(exit 0)

$ git verify-commit HEAD 2>&1 | grep -o "Good signature from .*"
Good signature from "Owner <owner@example.invalid>" [ultimate]
(exit 0)

== 6. the gate (Claude Code hooks): a feature request closes the repo for edits until the person says go
# Here the person types into the terminal, so the prompt is their own words. Behind an orchestrator that relays
# messages, keep require_citation = true: then a go counts only with a cited message id of the person.

$ printf '[gate]\nrequire_citation = false\n' >> agent-gate.toml && tail -2 agent-gate.toml
[gate]
require_citation = false
(exit 0)

$ echo '{"session_id": "s1", "prompt": "kind: feature\nadd a dark mode"}' | agent-gate gate prompt
{"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": "INTAKE GATE (feedback or feature): no changes to the repo before the person's go. First write their words verbatim and any decisions made by others as proposals, research with sources, 2-3 options, a critic; then ask and stop. Scratch places stay writable: /tmp, .claude/gate. The go is a note with `kind: go`."}}
(exit 0)

$ echo '{"session_id": "s1", "tool_name": "Edit", "tool_input": {"file_path": "src/theme.css"}}' | agent-gate gate pretool
{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": "Intake gate: this is feedback or a feature request, and the person has not said go. Only read-only commands and writes under /tmp or .claude/gate are allowed. Write the requirements (their words verbatim), the options with sources and the critic's verdict there, ask, and stop. Changes to the repo wait for a note with `kind: go`."}}
(exit 0)

$ echo '{"session_id": "s1", "tool_name": "Bash", "tool_input": {"command": "git status"}}' | agent-gate gate pretool
(exit 0)

$ echo '{"session_id": "s1", "prompt": "kind: go\noption 2, keep the old palette"}' | agent-gate gate prompt
{"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": "Go recorded: the intake gate is open for changes."}}
(exit 0)

$ echo '{"session_id": "s1", "tool_name": "Edit", "tool_input": {"file_path": "src/theme.css"}}' | agent-gate gate pretool
(exit 0)
```

## Configuration

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

## Design decisions

- **Mechanical over advisory.** Every rule here is something a script can decide with exit 0 or 1. Rules that need
  judgment stay in the instruction files; where only the shape can be checked (a cited approval, a named verifier),
  `rules.toml` says so in its `limits` field.
- **Judge history, not the net diff.** A secret added in one commit and removed in the next passes a diff of
  base..HEAD; the secrets check reads every commit of the range and what merge commits add against all parents.
- **Judge the pushed commit, not the working copy.** pre-push tests a clean worktree of the sha being pushed.
- **Fail closed.** A check that crashes is a problem; a config that does not parse is red; a missing launcher makes
  the hook fail; a push base that is unknown (new branch, force push) widens the range instead of shrinking it.
- **Evasion-aware matching.** Messages are NFKC-normalised with format characters, combining marks, small-capital
  look-alikes and dash variants removed before banned words are matched; diffs are split on newline only, so a carriage
  return or U+2028 cannot hide the rest of a line; the git log is read NUL-separated.
- **Isolated execution.** Hooks run `python3 -I` on the launcher in the agent-gate clone: the guarded repo is never on
  the module path and `PYTHONPATH` is ignored, so a `json.py` or `subprocess.py` committed to the guarded repo cannot
  shadow the standard library inside the checks (a test commits such files and expects the hooks to keep working).
- **Tests that cannot hurt the host repo.** Running the suite inside a git hook once made fixture commits land in the
  enclosing repository (hooks export `GIT_DIR`). `tests/gitsafe.py` scrubs those variables and refuses a fixture whose
  origin is not a local sandbox, and a test fails when a test file runs git without importing it.

## Limitations

- **Client-side hooks are skippable.** `git commit --no-verify`, `git push --no-verify`, changing `core.hooksPath`,
  or a clone without the install skips everything. The demo shows the push check catching what `--no-verify` let
  through at commit time, but the only rule a client cannot skip is a server-side one (branch protection with a CI job
  running `agent-gate run`). `.github/workflows/agent-gate.yml` is that job (tests, `agent-gate run` on the pushed range and a
  full-tree secret scan, Python 3.11 and 3.13); it has not been run yet, because this copy of the repository has no remote.
- **Pattern matching, not proof.** The secrets check knows a list of shapes; an unknown format, an encoded or split
  credential passes. The hidden-text check catches cheap injections, not a paraphrase.
- **The gate's Bash check is a speed bump, not a sandbox.** It tokenizes the command like a shell (quotes removed,
  operators split), denies what it does not model (substitutions, `&`, here-documents, any assignment but a few
  locale variables, `env CMD`, unknown commands) and allows a short list of read-only commands with their writing
  options closed. It still cannot see: a script written to a scratch place and then run (allowed on purpose, and it
  can do anything); side effects of the repository's own config or attributes (`core.fsmonitor`, textconv and diff
  drivers already set in `.git/config` or `.gitattributes` run on `git status`/`git diff`); variables exported earlier
  in the same shell session; `python3 -m unittest` running tests that write; an allowed tool option it does not know
  about. It over-blocks too (a quoted `|` in a pattern is fine, but `uniq a /tmp/out` is denied).
- **Shape, not truth.** `signatures` checks that a signature header exists, not that it verifies. `changes` checks
  that a verifier is named and differs from the author, not that a second agent really ran anything. The gate reads
  the go from text; a forged citation passes.
- **The root commit is its own base.** A first push of a brand-new history judges the tree of the root commit (the
  tree checks) but not its added lines (the history checks), because nothing came before it.
- **The tests come from the pushed tree.** The rules are read from the base commit, but the test command runs the
  tests in the pushed commit, so an agent can delete or neuter a test in the same push. Review test diffs, or keep
  the important tests outside the guarded repo.
- **Only the tip is tested.** pre-push runs the test command on the pushed commit only; a red commit in the middle of
  a push with a green tip passes the test step (the checks still read every commit). A test pins this behaviour.
- **The checks live outside the guarded repo.** A push cannot weaken them, but whoever can write to the agent-gate
  clone can.
- **Not measured here:** false-positive rates on real repositories, run time on large histories (the suite has speed
  tests for 5 MB blobs and 300 000-character lines only), behaviour with agents other than Claude Code for the gate.
- Personal research project: used on one person's repositories, not by a team.

## Part of a set

- [agent-lab](https://github.com/dmitrykarpushkin/agent-lab): the working spec and the role chains that ideas and
  tasks go through before they reach these gates.
- [agent-console](https://github.com/dmitrykarpushkin/agent-console): the panel where a person sees decisions,
  results and breakages.

## Repository layout

```
agent_gate/            the package: run_all.py, prepush.py, gate.py, config.py, common.py, __main__.py
agent_gate/checks/     one module per check
bin/agent-gate         launcher (python3 -I bin/agent-gate <run|staged|msg|tree|pre-push|gate> ...)
hooks/                 pre-commit, commit-msg, pre-push, install.sh
examples/              agent-gate.toml, claude-settings.json, demo.sh
.github/workflows/     agent-gate.yml: the server-side job (not run yet)
rules.toml             each rule, the files that enforce it, and what it does not catch
tests/                 282 unit and end-to-end tests (python3 -m unittest discover -s tests)
agent-gate.toml        the rules agent-gate applies to its own repository
```

## License

MIT, see `LICENSE`.
