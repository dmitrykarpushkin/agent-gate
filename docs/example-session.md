# Example session

Real output of `sh examples/demo.sh`, regenerated for this page (the temporary directory is shown as `$DEMO`, the
stopline clone as `<stopline>`; commit hashes change on every run). Step 6 feeds the gate the JSON events Claude Code
sends to hooks. It switches `require_citation` off, visibly: in a terminal the prompt comes straight from the person.
Behind an orchestrator that relays messages (where a "go" could be typed by another agent), leave it on, and a go
counts only with a cited message id of the person.

```
== 1. install the hooks and push the rules

$ sh <stopline>/hooks/install.sh
stopline hooks installed for $DEMO/repo (core.hooksPath=<stopline>/hooks)
(exit 0)

$ git add -A && git commit -qm "add rules and tests" && git push -q origin HEAD:main
stopline pre-push: 4cb747fc3583 -> main, judged against 4cb747fc3583
stopline pre-push: tests green (python3 -m unittest discover -s tests)
stopline: 12 checks on 4cb747fc3583..HEAD, rules from agent-gate.toml at 4cb747fc3583
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

== 2. the agent commits a key (a fake AWS key id, built at runtime)

$ git add settings.py && git commit -qm "add settings"
settings.py: possible aws key id
stopline pre-commit: commit blocked
(exit 1)

== 3. the agent commits under its own identity

$ git add hello.py && git -c user.email=coding-agent@example.invalid commit -qm "add hello"
index: author coding-agent@example.invalid is not an allowed identity
index: committer coding-agent@example.invalid is not an allowed identity
stopline pre-commit: commit blocked
(exit 1)

== 4. the agent skips the commit hooks (--no-verify) and pushes: a foreign author and an unsigned commit by the owner

$ git -c user.email=coding-agent@example.invalid commit -q --no-verify -m "add hello" && git -c user.email=owner@example.invalid commit -q --allow-empty --no-verify -m "owner work, unsigned" && git push -q origin HEAD:main
stopline pre-push: 80f106e12844 -> main, judged against 4cb747fc3583
stopline pre-push: tests green (python3 -m unittest discover -s tests)
stopline: 12 checks on 4cb747fc3583..HEAD, rules from agent-gate.toml at 4cb747fc3583
secrets: ok
commits: 2 problem(s)
  - 1ba2b34: author coding-agent@example.invalid is not an allowed identity
  - 1ba2b34: committer coding-agent@example.invalid is not an allowed identity
signatures: 1 problem(s)
  - 80f106e: commit by owner@example.invalid without a signature
language: ok
supply_chain: ok
pinned_models: ok
hidden_text: ok
telemetry_flags: ok
core_sync: ok
changes: ok
required_text: ok
gate_wiring: ok
stopline pre-push: checks are red for 80f106e12844, push blocked
error: failed to push some refs to '$DEMO/remote.git'
(exit 1)

== 5. the same work, committed by the bot and signed by the owner, goes through

$ git add hello.py && git commit -qm "add hello" && git -c user.email=owner@example.invalid -c user.signingkey=owner@example.invalid commit -q -S --allow-empty -m "owner work, signed" && git push -q origin HEAD:main
stopline pre-push: cb216060efaa -> main, judged against 4cb747fc3583
stopline pre-push: tests green (python3 -m unittest discover -s tests)
stopline: 12 checks on 4cb747fc3583..HEAD, rules from agent-gate.toml at 4cb747fc3583
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

$ echo '{"session_id": "s1", "prompt": "kind: feature\nadd a dark mode"}' | stopline gate prompt
{"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": "INTAKE GATE (feedback or feature): no changes to the repo before the person's go. First write their words verbatim and any decisions made by others as proposals, research with sources, 2-3 options, a critic; then ask and stop. Scratch places stay writable: /tmp, .claude/gate. The go is a note with `kind: go`."}}
(exit 0)

$ echo '{"session_id": "s1", "tool_name": "Edit", "tool_input": {"file_path": "src/theme.css"}}' | stopline gate pretool
{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": "Intake gate: this is feedback or a feature request, and the person has not said go. Only read-only commands and writes under /tmp or .claude/gate are allowed. Write the requirements (their words verbatim), the options with sources and the critic's verdict there, ask, and stop. Changes to the repo wait for a note with `kind: go`."}}
(exit 0)

$ echo '{"session_id": "s1", "tool_name": "Bash", "tool_input": {"command": "git status"}}' | stopline gate pretool
(exit 0)

$ echo '{"session_id": "s1", "prompt": "kind: go\noption 2, keep the old palette"}' | stopline gate prompt
{"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": "Go recorded: the intake gate is open for changes."}}
(exit 0)

$ echo '{"session_id": "s1", "tool_name": "Edit", "tool_input": {"file_path": "src/theme.css"}}' | stopline gate pretool
(exit 0)
```
