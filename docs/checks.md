# Checks and hooks

The twelve checks the runner applies, and the hooks that call them. Each rule, the files that enforce it and what it
does not catch are also listed in [`rules.toml`](../rules.toml).

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

## How the pieces fit

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
