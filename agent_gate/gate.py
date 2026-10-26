"""Agent gate: mechanical stops for two failures that instructions alone did not prevent, wired as Claude Code hooks.

  prompt   (UserPromptSubmit) a message with a line `kind: feedback` or `kind: feature` opens the intake gate for this session;
           a message with a line `kind: go` records the human's go (by default it must also cite a human message, see below).
  pretool  (PreToolUse)       while the gate is open and no go is recorded, changes outside the scratch places are denied (Edit,
           Write, a Bash command that writes, git commit or push).
  log      (PostToolUse)      records edits of page files (page_patterns) and Reads of PNG files.
  stop     (Stop)             refuses to end a turn that edited page files without a PNG Read after the last such edit
           (at most `screenshot_cap` blocks per session).

Failure 1: feedback or a feature request went straight into code, before the person had agreed to any option.
Failure 2: a page change was reported as checked after reading the HTML, without looking at a rendered picture.

The gate is inert without the marker (ordinary work is not touched). State lives in .claude/gate/ of the project
(untracked). The go is read from text, so it is only as good as the sender of the note: it stops a model from skipping
the human, it does not stop someone who forges a citation.

Config [gate] in agent-gate.toml of the project: scratch (extra writable places, default ["/tmp"]), page_patterns
(regular expression of page files, default html and css), require_citation (default true), citation_pattern (default:
the <cited id="..." author="user"> tag a relaying orchestrator puts around a quoted human message), screenshot_cap (3).
In a plain terminal session, where the prompt comes straight from the person, set require_citation = false.
"""
import json
import os
import re
import sys

CAP = 3
PAGE = r"\.(html|css)$"
KIND = re.compile(r"(?im)^\s*kind:\s*(feedback|feature|go)\b")
CITED = r'<cited\s+id="([A-Za-z0-9_-]+)"\s+author="user"'
SCRATCH = ("/tmp",)


def root():
    return os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()


def settings():
    """The [gate] table of the project's agent-gate.toml, or {} (missing file, old Python, bad TOML: defaults)."""
    try:
        import tomllib
        with open(os.path.join(root(), "agent-gate.toml"), "rb") as f:
            sec = tomllib.load(f).get("gate") or {}
        return sec if isinstance(sec, dict) else {}
    except (OSError, ImportError, ValueError):
        return {}


def state_dir():
    d = os.path.join(root(), ".claude", "gate")
    os.makedirs(d, exist_ok=True)
    return d


def sid(data):
    return re.sub(r"[^A-Za-z0-9_-]", "", str(data.get("session_id") or "nosession"))


def read(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def write(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f)


def scratch_places():
    return tuple(os.path.normpath(p) for p in settings().get("scratch", SCRATCH))


def prompt(data):
    text = str(data.get("prompt") or "")
    kinds = [k.lower() for k in KIND.findall(text)]
    base = os.path.join(state_dir(), sid(data))
    cfg = settings()
    out = None
    closing = "feedback" in kinds or "feature" in kinds
    if "go" in kinds and not closing:
        ids = re.findall(cfg.get("citation_pattern", CITED), text)
        if ids or not cfg.get("require_citation", True):
            write(base + ".go.json", {"cited_messages": ids})
            out = "Go recorded%s: the intake gate is open for changes." % ((" from the cited message(s) " + ", ".join(ids)) if ids else "")
        else:
            out = "A `kind: go` note without a cited human message is not a go: the gate stays closed."
    elif closing:
        write(base + ".intake.json", {"kind": [k for k in kinds if k != "go"][0]})
        try:
            os.remove(base + ".go.json")
        except OSError:
            pass
        places = ", ".join(scratch_places() + (".claude/gate",))
        out = ("INTAKE GATE (feedback or feature): no changes to the repo before the person's go. First write their words verbatim and any "
               "decisions made by others as proposals, research with sources, 2-3 options, a critic; then ask and stop. Scratch places "
               "stay writable: %s. The go is a note with `kind: go`." % places)
    if out:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": out}}))
    return 0


def gate_closed(data):
    base = os.path.join(state_dir(), sid(data))
    return os.path.exists(base + ".intake.json") and not os.path.exists(base + ".go.json")


def scratch(path, places=None):
    """True when path resolves (relative paths against the project root, '..' collapsed) to a scratch place. The project root itself is never
    scratch, even when it lives under /tmp (sandboxes, temporary worktrees); only its .claude/gate folder is."""
    if not path:
        return False
    places = SCRATCH if places is None else places
    top = os.path.normpath(root())
    full = os.path.normpath(os.path.join(top, os.path.expanduser(path)))
    gate = os.path.join(top, ".claude", "gate")
    if full == gate or full.startswith(gate + "/"):
        return True
    if full == top or full.startswith(top + "/"):
        return False
    return full == "/dev/null" or any(full == p or full.startswith(p + "/") for p in places)


# Bash write detection. The command is split by a small shell tokenizer (quotes removed, operators separated), then
# every simple command is judged against an allowlist. Anything the tokenizer does not model is a write.
READONLY = {"ls", "cat", "head", "tail", "wc", "grep", "rg", "find", "echo", "printf", "pwd", "date", "stat", "file", "jq", "which", "tree",
            "sort", "uniq", "cut", "tr", "diff", "cmp", "test", "[", "true", "false", "sleep", "env", "basename", "dirname", "realpath", "cd",
            "sed", "curl", "git", "gh", "python3", "python", "sha256sum", "md5sum", "nl", "column", "id", "whoami", "ps", "df", "du"}
RUNNERS = ("python3", "python", "node", "bash", "sh")
SAFE_VARS = {"LC_ALL", "LANG", "LC_CTYPE", "LC_COLLATE", "TZ", "NO_COLOR", "TERM", "COLUMNS"}
RO_GIT = {"status", "log", "diff", "show", "ls-files", "rev-parse", "blame", "remote", "describe", "shortlog", "grep", "cat-file", "ls-tree",
          "rev-list", "branch", "tag", "worktree", "reflog", "name-rev", "merge-base", "diff-tree", "check-ignore"}
GIT_REF_WRITES = ("-d", "-D", "-m", "-M", "-c", "-C", "-f", "-u", "--delete", "--move", "--copy", "--force", "--set-upstream-to", "--unset-upstream",
                  "--edit-description")
GIT_GLOBAL_OK = ("-C", "--no-pager", "-P", "--no-optional-locks", "--git-dir", "--work-tree", "--bare", "--literal-pathspecs")
LIST_FLAGS = ("-l", "--list", "--contains", "--no-contains", "--merged", "--no-merged", "--points-at")
GH_READS = ("view", "list", "status", "diff", "checks")
GH_NEVER = ("api", "auth", "alias", "extension", "config", "secret", "variable", "ssh-key", "gpg-key", "codespace", "browse")
SED_FLAGS = ("-n", "--quiet", "--silent", "-E", "-r", "--regexp-extended", "-s", "--separate", "-u", "--unbuffered", "-z", "--null-data")
_ADDR = r"(?:\d+|\$|/(?:[^/\\]|\\.)*/I?)"
_CMD = r"(?:[pdq=]|s/(?:[^/\\]|\\.)*/(?:[^/\\]|\\.)*/[gpiImM0-9]*)"
_ONE = r"\s*(?:%s(?:\s*,\s*%s)?\s*!?)?\s*%s\s*" % (_ADDR, _ADDR, _CMD)
SED_READ = re.compile(r"(?:%s;)*%s;?\s*" % (_ONE, _ONE))
CURL_SHORT_WRITES = set("oOTXdFKcDE")   # output, upload, method, data, form, config, cookie jar, header dump, client cert
CURL_LONG_WRITES = ("--output", "--remote-name", "--upload-file", "--request", "--data", "--form", "--json", "--config", "--cookie-jar",
                    "--dump-header", "--trace", "--stderr", "--libcurl", "--create-dirs", "--etag-save", "--hsts", "--alt-svc", "--url-query",
                    "--ssl-sessions")
FIND_WRITES = ("-delete", "-exec", "-execdir", "-ok", "-okdir", "-fls", "-fprint")
# per command: short-option letters and long-option prefixes that write a file or run a program
SHORT_WRITES = {"sort": set("oT"), "tree": set("oR"), "date": set("s"), "file": set("C"), "rg": set()}
LONG_WRITES = {"sort": ("--output", "--temporary-directory", "--compress-program"), "tree": ("--output",), "date": ("--set",),
               "file": ("--compile",), "rg": ("--pre",)}

OPS = ("&>>", "<<<", "&&", "||", ";;", "|&", ">>", "&>", ">&", "<&", ">|", "<<", "<>", "|", "&", ";", ">", "<", "(", ")", "\n")
SEPARATORS = {"&&", "||", ";;", "|&", "|", ";", "(", ")", "\n"}
REDIRECT_OUT = {">", ">>", "&>", "&>>", ">|", "<>", ">&"}


def shell_tokens(cmd):
    """Split a command line like a POSIX shell does for our purpose: words with quotes and backslashes removed, and
    operators. Returns [(kind, text)] with kind "w" or "op"; raises ValueError on an unterminated quote. A word of digits
    right before a redirection is its file descriptor and is dropped. A comment runs to the end of the line."""
    out, cur, quoted, i, n = [], None, False, 0, len(cmd)

    def flush():
        nonlocal cur, quoted
        if cur is not None:
            out.append(("w", cur))
        cur, quoted = None, False
    while i < n:
        c = cmd[i]
        if c in " \t\r":
            flush()
            i += 1
        elif c == "\\":
            if cmd[i + 1:i + 2] == "\n":
                i += 2
                continue
            cur = (cur or "") + cmd[i + 1:i + 2]
            quoted = True
            i += 2
        elif c == "'":
            j = cmd.find("'", i + 1)
            if j < 0:
                raise ValueError("unterminated quote")
            cur, quoted, i = (cur or "") + cmd[i + 1:j], True, j + 1
        elif c == '"':
            j, buf = i + 1, []
            while j < n and cmd[j] != '"':
                if cmd[j] == "\\" and j + 1 < n and cmd[j + 1] in '"\\$`\n':
                    buf.append(cmd[j + 1])
                    j += 2
                else:
                    buf.append(cmd[j])
                    j += 1
            if j >= n:
                raise ValueError("unterminated quote")
            cur, quoted, i = (cur or "") + "".join(buf), True, j + 1
        elif c == "#" and cur is None:
            while i < n and cmd[i] != "\n":
                i += 1
        else:
            op = next((o for o in OPS if cmd.startswith(o, i)), None)
            if op is None:
                cur = (cur or "") + c
                i += 1
                continue
            if op[0] in "<>" and cur is not None and not quoted and cur.isdigit():
                cur = None
            flush()
            out.append(("op", op))
            i += len(op)
    flush()
    return out


def git_writes(rest):
    """git with an allowlist of global options (no -c, no --config-env, no --exec-path), a read-only subcommand and, for the ref
    commands, listing forms only."""
    i = 0
    while i < len(rest) and rest[i].startswith("-"):
        if rest[i].split("=", 1)[0] not in GIT_GLOBAL_OK:
            return True
        i += 2 if rest[i] in ("-C", "--git-dir", "--work-tree") else 1
    sub = rest[i] if i < len(rest) else ""
    args = rest[i + 1:]
    if sub not in RO_GIT or any(a.startswith(("--output", "--open-files-in-pager", "-O", "--ext-diff")) for a in args):
        return True
    words = [a for a in args if not a.startswith("-")]
    if sub in ("branch", "tag"):
        return any(a in GIT_REF_WRITES for a in args) or (bool(words) and not any(a.split("=", 1)[0] in LIST_FLAGS for a in args))
    if sub == "remote":
        return bool(words) and words[0] not in ("show", "get-url")
    if sub == "worktree":
        return words[:1] != ["list"]
    if sub == "reflog":
        return bool(words) and words[0] != "show"
    return False


def sed_writes(rest):
    """sed only as a printer: known flags, inline scripts made of p, d, q, = and s/// without the e or w flags."""
    scripts, files, j = [], [], 0
    while j < len(rest):
        a = rest[j]
        if a in ("-e", "--expression"):
            scripts.append(rest[j + 1] if j + 1 < len(rest) else "")
            j += 2
            continue
        if a.startswith("--expression="):
            scripts.append(a.split("=", 1)[1])
        elif a.startswith("-") and a != "-":
            if a not in SED_FLAGS and not re.fullmatch(r"-[nErsuz]+", a):
                return True
        else:
            files.append(a)
        j += 1
    if not scripts:
        if not files:
            return True
        scripts.append(files.pop(0))
    return not all(SED_READ.fullmatch(t) for t in scripts)


def curl_writes(rest):
    for a in rest:
        if "%output{" in a or a.startswith("@"):
            return True
        if a.startswith("--"):
            if a.split("=", 1)[0].startswith(CURL_LONG_WRITES):
                return True
        elif a.startswith("-") and CURL_SHORT_WRITES & set(a[1:]):
            return True
    return False


def option_writes(w0, rest):
    """Commands that only write through an option: any short-option cluster holding a listed letter, any listed long option."""
    for a in rest:
        if a.startswith("--"):
            if a.split("=", 1)[0].startswith(LONG_WRITES[w0]):
                return True
        elif a.startswith("-") and SHORT_WRITES[w0] & set(a[1:]):
            return True
    return False


def uniq_writes(rest):
    """uniq IN OUT writes OUT: more than one file operand is a write."""
    files, j = 0, 0
    while j < len(rest):
        if rest[j] in ("-f", "-s", "-w"):
            j += 2
            continue
        if not rest[j].startswith("-") or rest[j] == "-":
            files += 1
        j += 1
    return files > 1


def command_writes(words, is_scratch):
    if not words:
        return False
    while words and re.fullmatch(r"[A-Za-z_]\w*=.*", words[0], re.S):
        if words[0].split("=", 1)[0] not in SAFE_VARS:
            return True   # GIT_PAGER, GIT_EXTERNAL_DIFF, LD_PRELOAD, ... can run a program
        words = words[1:]
    if not words:
        return True   # a bare assignment changes the shell; nothing to read here
    w0, rest = os.path.basename(words[0]), words[1:]
    if is_scratch(words[0]):
        return False   # a script the agent wrote to a scratch place (see Limitations)
    if w0 in RUNNERS:
        return not ((w0.startswith("python") and rest[:2] == ["-m", "unittest"]) or (rest and not rest[0].startswith("-") and is_scratch(rest[0])))
    if w0 not in READONLY:
        return True
    if w0 == "git":
        return git_writes(rest)
    if w0 == "gh":
        if rest[:1] == ["status"] or rest[:2] == ["auth", "status"]:
            return False
        return (len(rest) < 2 or rest[0] in GH_NEVER or rest[1] not in GH_READS or any(a in ("--web", "-w") for a in rest))
    if w0 == "env":
        return bool(rest)   # env with anything runs a command or changes its environment
    if w0 == "sed":
        return sed_writes(rest)
    if w0 == "find":
        return any(a.startswith(FIND_WRITES) for a in rest)
    if w0 == "curl":
        return curl_writes(rest)
    if w0 == "uniq":
        return uniq_writes(rest)
    if w0 in SHORT_WRITES:
        return option_writes(w0, rest)
    return False


def bash_writes(cmd, places=None):
    """True when a Bash command may change something outside the scratch places. An allowlist of read-only commands, so unknown
    commands, and shell syntax the tokenizer does not model, are denied."""
    is_scratch = lambda p: scratch(p, places)  # noqa: E731
    if "$(" in cmd or "`" in cmd or "<(" in cmd or ">(" in cmd:
        return True   # command and process substitution are not parsed
    try:
        toks = shell_tokens(cmd)
    except ValueError:
        return True
    words, i = [], 0
    while i < len(toks):
        kind, t = toks[i]
        if kind == "w":
            words.append(t)
        elif t in SEPARATORS:
            if command_writes(words, is_scratch):
                return True
            words = []
        elif t in ("&", "<<"):
            return True   # background jobs and here-documents are not modelled
        else:   # a redirection: the next word is its target
            target = toks[i + 1][1] if i + 1 < len(toks) and toks[i + 1][0] == "w" else None
            if target is None:
                return True
            if t in REDIRECT_OUT and not (t == ">&" and (target.isdigit() or target == "-")) and not is_scratch(target):
                return True
            i += 1
        i += 1
    return command_writes(words, is_scratch)


def pretool(data):
    if not gate_closed(data):
        return 0
    places = scratch_places()
    name = data.get("tool_name", "")
    inp = data.get("tool_input") if isinstance(data.get("tool_input"), dict) else {}
    bad = False
    if name in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        bad = not scratch(str(inp.get("file_path") or inp.get("notebook_path") or inp.get("path") or ""), places)
    elif name == "Bash":
        bad = bash_writes(str(inp.get("command", "")), places)
    if bad:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason":
            "Intake gate: this is feedback or a feature request, and the person has not said go. Only read-only commands and writes under "
            "%s or .claude/gate are allowed. Write the requirements (their words verbatim), the options with sources and the critic's "
            "verdict there, ask, and stop. Changes to the repo wait for a note with `kind: go`." % ", ".join(places)}}))
    return 0


def log(data):
    name = data.get("tool_name", "")
    inp = data.get("tool_input") if isinstance(data.get("tool_input"), dict) else {}
    path = str(inp.get("file_path", ""))
    page = settings().get("page_patterns", PAGE)
    kind = None
    if name in ("Write", "Edit", "MultiEdit") and re.search(page, path.replace(root() + "/", "")):
        kind = "edit"
    elif name == "Bash":
        cmd = str(inp.get("command", ""))
        targets = [t.strip("'\"") for m in re.finditer(r"(?:sed\s+-i\S*|>>?|tee)\s+([^|;]*)", cmd) for t in m.group(1).split()]
        if any(re.search(page, t) for t in targets):
            kind = "edit"
    elif name == "Read" and path.lower().endswith(".png"):
        kind = "pngread"
    if kind:
        with open(os.path.join(state_dir(), sid(data) + ".events"), "a") as f:
            f.write(kind + "\n")
    return 0


def stop(data):
    base = os.path.join(state_dir(), sid(data))
    try:
        with open(base + ".events") as f:
            events = f.read().split()
    except OSError:
        return 0
    last_edit = max([i for i, e in enumerate(events) if e == "edit"], default=-1)
    last_read = max([i for i, e in enumerate(events) if e == "pngread"], default=-1)
    if last_edit < 0 or last_read > last_edit:
        return 0
    blocks = read(base + ".blocks.json", 0)
    if blocks >= int(settings().get("screenshot_cap", CAP)):
        return 0
    write(base + ".blocks.json", blocks + 1)
    sys.stderr.write("Cannot end the turn: a page change is checked by looking at the picture. Render the page to a PNG (phone width 400 and desktop), "
                     "Read the PNG after your last edit and say what you see. Reading HTML, CSS or text is not a check of the layout.\n")
    return 2


MODES = {"prompt": prompt, "pretool": pretool, "log": log, "stop": stop}


def main(argv):
    """argv: [mode]. Reads the hook event as JSON on stdin. A hook must never break the session: an unknown mode, bad input
    or an internal error lets the call through (exit 0)."""
    try:
        d = json.load(sys.stdin)
    except ValueError:
        d = {}
    if not isinstance(d, dict):
        d = {}
    try:
        return MODES[argv[0]](d) if argv and argv[0] in MODES else 0
    except Exception as e:   # noqa: BLE001
        sys.stderr.write("gate: %s: %s\n" % (type(e).__name__, e))
        return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
