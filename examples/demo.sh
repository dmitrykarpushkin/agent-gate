#!/bin/sh
# A reproducible demo: a scratch repository guarded by agent-gate, and an "agent" that tries to commit a key, commit under
# a foreign identity, push unsigned work, and edit before the person said go. Usage: sh examples/demo.sh
# Everything happens in a temporary directory (shown as $DEMO); the agent-gate clone is shown as <agent-gate>.
# Needs git and Python 3.11+; gpg is used for the last step (a throwaway key in the temporary directory) when present.
set -u
# the demo ignores your own git settings (signing programs, hooks paths) so it behaves the same everywhere
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1
AG=$(cd "$(dirname "$0")/.." && pwd -P)
DEMO=$(mktemp -d)
trap 'rm -rf "$DEMO"' EXIT
OWNER=owner@example.invalid
BOT=repo-bot@example.invalid

# run CMD...: print the command, run it in the demo repo, print its output and exit status
run() {
    printf '\n$ %s\n' "$*" | sed -e "s#$DEMO#\$DEMO#g" -e "s#$AG#<agent-gate>#g"
    out=$(cd "$DEMO/repo" && sh -c "$*" 2>&1)
    rc=$?
    [ -n "$out" ] && printf '%s\n' "$out" | sed -e "s#$DEMO#\$DEMO#g" -e "s#$AG#<agent-gate>#g"
    echo "(exit $rc)"
}

git init -q --bare -b main "$DEMO/remote.git"
git init -q -b main "$DEMO/repo"
cd "$DEMO/repo" || exit 1
git config user.name "Repo Bot"
git config user.email "$BOT"
git config commit.gpgsign false
git remote add origin "$DEMO/remote.git"
mkdir tests
cat > tests/test_ok.py <<'EOF'
import unittest
class T(unittest.TestCase):
    def test_ok(self):
        self.assertTrue(True)
EOF
cat > agent-gate.toml <<EOF
[push]
branches = ["main"]
test_command = "python3 -m unittest discover -s tests"

[commits]
allowed_emails = ["$OWNER", "$BOT"]
banned_trailers = ["co-authored-by"]

[signatures]
signed_emails = ["$OWNER"]
EOF

echo "== 1. install the hooks and push the rules"
run sh "$AG/hooks/install.sh"
run 'git add -A && git commit -qm "add rules and tests" && git push -q origin HEAD:main'

echo
echo "== 2. the agent commits a key (a fake AWS key id, built at runtime)"
KEY=$(python3 -c 'print("AKIA" + "Z" * 16)')
printf 'AWS_KEY_ID = "%s"\n' "$KEY" > settings.py
run 'git add settings.py && git commit -qm "add settings"'
rm -f settings.py
git reset -q

echo
echo "== 3. the agent commits under its own identity"
echo "print('hello')" > hello.py
run 'git add hello.py && git -c user.email=coding-agent@example.invalid commit -qm "add hello"'

echo
echo "== 4. the agent skips the commit hooks (--no-verify) and pushes: a foreign author and an unsigned commit by the owner"
run 'git -c user.email=coding-agent@example.invalid commit -q --no-verify -m "add hello" && git -c user.email='"$OWNER"' commit -q --allow-empty --no-verify -m "owner work, unsigned" && git push -q origin HEAD:main'

echo
echo "== 5. the same work, committed by the bot and signed by the owner, goes through"
git reset -q --hard origin/main
if command -v gpg >/dev/null 2>&1; then
    export GNUPGHOME="$DEMO/gnupg"
    mkdir -m 700 "$GNUPGHOME"
    gpg --batch --quiet --passphrase '' --quick-gen-key "Owner <$OWNER>" ed25519 sign never 2>/dev/null
    echo "print('hello')" > hello.py
    run 'git add hello.py && git commit -qm "add hello" && git -c user.email='"$OWNER"' -c user.signingkey='"$OWNER"' commit -q -S --allow-empty -m "owner work, signed" && git push -q origin HEAD:main'
    run 'git verify-commit HEAD 2>&1 | grep -o "Good signature from .*"'
else
    echo "(gpg not installed: step skipped)"
fi

echo
echo "== 6. the gate (Claude Code hooks): a feature request closes the repo for edits until the person says go"
gate() {
    printf "\n\$ echo '%s' | agent-gate gate %s\n" "$2" "$1"
    (cd "$DEMO/repo" && printf '%s' "$2" | CLAUDE_PROJECT_DIR="$DEMO/repo" python3 -I "$AG/bin/agent-gate" gate "$1")
    echo "(exit $?)"
}
echo "# Here the person types into the terminal, so the prompt is their own words. Behind an orchestrator that relays"
echo "# messages, keep require_citation = true: then a go counts only with a cited message id of the person."
run "printf '[gate]\\nrequire_citation = false\\n' >> agent-gate.toml && tail -2 agent-gate.toml"
gate prompt '{"session_id": "s1", "prompt": "kind: feature\nadd a dark mode"}'
gate pretool '{"session_id": "s1", "tool_name": "Edit", "tool_input": {"file_path": "src/theme.css"}}'
gate pretool '{"session_id": "s1", "tool_name": "Bash", "tool_input": {"command": "git status"}}'
gate prompt '{"session_id": "s1", "prompt": "kind: go\noption 2, keep the old palette"}'
gate pretool '{"session_id": "s1", "tool_name": "Edit", "tool_input": {"file_path": "src/theme.css"}}'
