# Design decisions and limits

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
- **Isolated execution.** Hooks run `python3 -I` on the launcher in the stopline clone: the guarded repo is never on
  the module path and `PYTHONPATH` is ignored, so a `json.py` or `subprocess.py` committed to the guarded repo cannot
  shadow the standard library inside the checks (a test commits such files and expects the hooks to keep working).
- **Tests that cannot hurt the host repo.** Running the suite inside a git hook once made fixture commits land in the
  enclosing repository (hooks export `GIT_DIR`). `tests/gitsafe.py` scrubs those variables and refuses a fixture whose
  origin is not a local sandbox, and a test fails when a test file runs git without importing it.

## Limitations (full list)

- **Client-side hooks are skippable.** `git commit --no-verify`, `git push --no-verify`, changing `core.hooksPath`,
  or a clone without the install skips everything. The demo shows the push check catching what `--no-verify` let
  through at commit time, but the only rule a client cannot skip is a server-side one (branch protection with a CI job
  running `stopline run`). `.github/workflows/ci.yml` is that job (tests, `stopline run` on the pushed range and a
  full-tree secret scan, Python 3.11 and 3.13); its result is shown by the CI badge in the README.
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
- **The checks live outside the guarded repo.** A push cannot weaken them, but whoever can write to the stopline
  clone can.
- **Not measured here:** false-positive rates on real repositories, run time on large histories (the suite has speed
  tests for 5 MB blobs and 300 000-character lines only), behaviour with agents other than Claude Code for the gate.
- Personal research project: used on one person's repositories, not by a team.
