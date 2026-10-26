#!/bin/sh
# Run inside the repository to guard:   sh /path/to/agent-gate/hooks/install.sh
# Points git at this hooks directory (core.hooksPath, an absolute path), so an update of the agent-gate clone reaches
# every guarded repo without a second install. Needs Python 3.11+ (tomllib).
here=$(cd "$(dirname "$0")" && pwd -P) || exit 1
root=$(git rev-parse --show-toplevel) || exit 1
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' || { echo "agent-gate needs Python 3.11 or newer" >&2; exit 1; }
for h in pre-commit commit-msg pre-push; do chmod +x "$here/$h"; done
chmod +x "$here/../bin/agent-gate"
git -C "$root" config core.hooksPath "$here" || exit 1
echo "agent-gate hooks installed for $root (core.hooksPath=$here)"
[ -f "$root/agent-gate.toml" ] || echo "no agent-gate.toml in $root yet: built-in defaults apply (see examples/agent-gate.toml)"
