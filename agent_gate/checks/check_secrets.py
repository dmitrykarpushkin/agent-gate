"""Rule no-secrets-in-repo: added lines must not look like credentials or tunnel URLs, and added files must not be key
files, .env files or blobs over the size limit.

Config [secrets]: allow_file (default .agent-gate/secret-paths-allow.txt, read from the base commit), size_limit_mb
(default 5), skip (exact paths whose lines are not scanned, for example this file when the tool checks itself)."""
import re, subprocess
from .. import common
from ..common import decode_bytes

PATTERNS = {
    "anthropic key": r"sk-ant-[A-Za-z0-9_-]{10,}",
    "github token": r"gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}",
    "openai key": r"\bsk-proj-[A-Za-z0-9_-]{20,}|\bsk-[A-Za-z0-9]{32,}",
    "google api key": r"\bAIza[0-9A-Za-z_-]{35}\b",
    "groq key": r"\bgsk_[A-Za-z0-9]{40,}",
    "huggingface token": r"\bhf_[A-Za-z0-9]{30,}",
    "xai key": r"\bxai-[A-Za-z0-9]{40,}",
    "bearer token": r"(?i)\bbearer\s+(?=[A-Za-z0-9._~+/=-]*\d)[A-Za-z0-9._~+/=-]{24,}",
    "aws key id": r"AKIA[0-9A-Z]{16}",
    "slack token": r"xox[abprs]-[A-Za-z0-9-]{10,}",
    "private key": r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    "telegram bot token": r"\b\d{8,10}:[A-Za-z0-9_-]{35}\b",
    "stripe key": r"\b[sr]k_live_[A-Za-z0-9]{16,}",
    "npm token": r"\bnpm_[A-Za-z0-9]{36}\b",
    "sendgrid key": r"\bSG\.[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,}",
    "jwt": r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}",
    "url with credentials": r"(?<![a-z0-9+.-])[a-z][a-z0-9+.-]{0,31}://[^\s/:@'\"<>${}]{1,128}:[^\s/@'\"<>${}]{3,128}@[A-Za-z0-9.-]+",
    "cloudflare token": r"\b(?:CLOUDFLARE_API_TOKEN|CF_API_TOKEN)\s*[:=]\s*['\"]?[A-Za-z0-9_-]{20,}",
    "api key assignment": r"(?i)\bapi[_-]?key\s*[:=]\s*['\"]?(?!os\.|\$)(?=[A-Za-z0-9_+/=-]*\d)[A-Za-z0-9_+/=-]{20,}",
    "tunnel url": r"(?<![a-z0-9-])[a-z0-9-]{1,63}\.(?:trycloudflare\.com|ngrok-free\.app|ts\.net)\b",
    "password assignment": r"(?i)\b(password|passwd|secret)\s*[:=]\s*['\"]?(?!os\.environ|os\.getenv)[^\s'\"<>$]{6,}",
}
COMPILED = {k: re.compile(v) for k, v in PATTERNS.items()}


def check_lines(pairs, skip=()):
    out = []
    for p, l in pairs:
        if p in skip:
            continue
        for name, rx in COMPILED.items():
            if rx.search(l):
                out.append(f"{p}: possible {name}")
    return out


ALLOW_FILE = ".agent-gate/secret-paths-allow.txt"
SIZE_LIMIT = 5 * 1024 * 1024
KEY_SUFFIXES = (".pem", ".p12", ".pfx", ".key", ".keystore", ".p8", ".kdbx", ".jks", ".ppk", ".gpg")
KEY_NAMES = ("id_rsa", "id_ed25519", "id_ecdsa", "id_dsa")  # anywhere in the name: id_rsa.bak, deploy_id_rsa
EXACT_NAMES = ("credentials", "credentials.json", "secrets.json", "token.json", ".netrc", ".npmrc", ".pgpass", ".git-credentials", ".htpasswd")
ENV_TEMPLATES = (".env.example", ".env.sample", ".env.template")


def sensitive_name(path):
    """True when the file name alone says it holds a credential (keys, certificates, .env and *.env, credentials*.json, service-account*.json)."""
    n = path.rsplit("/", 1)[-1].lower()
    if n == ".env" or (n.startswith(".env.") and n not in ENV_TEMPLATES) or n.endswith(".env"):
        return True
    if n in EXACT_NAMES or n.endswith(KEY_SUFFIXES):
        return True
    if any(k in n for k in KEY_NAMES) and not n.endswith(".pub"):
        return True
    return n.endswith(".json") and n.startswith(("credentials", "service-account", "service_account"))


def settings(cfg):
    """(allow_file, size_limit_bytes, skip) from the [secrets] table."""
    sec = (cfg or {}).get("secrets") or {}
    return (sec.get("allow_file", ALLOW_FILE), int(float(sec.get("size_limit_mb", 5)) * 1024 * 1024), tuple(sec.get("skip", ())))


def parse_allow(text, allow_file=ALLOW_FILE):
    """Return (globs, problems). A line is `glob  # reason`; blank lines and lines starting with # are comments.
    An entry without a reason allows nothing and is reported."""
    globs, problems = [], []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        pat, sep, reason = line.partition(" #")
        if not sep or not reason.strip():
            problems.append(f"{allow_file}: entry {pat.strip()!r} is without a reason (write `glob  # why`), it allows nothing")
            continue
        pat = pat.strip()
        if not pat.strip("*?/"):
            problems.append(f"{allow_file}: entry {pat!r} is only wildcards and would allow everything, it allows nothing")
            continue
        try:
            glob_regex(pat)
        except re.error as e:
            problems.append(f"{allow_file}: entry {pat!r} is not a valid glob ({e}), it allows nothing")
            continue
        globs.append(pat)
    return globs, problems


def glob_regex(glob):
    """Glob to regex for a whole path: * and ? stay inside one path segment, ** (as a whole segment or anywhere) crosses slashes."""
    out, i = [], 0
    while i < len(glob):
        c = glob[i]
        if glob.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
            continue
        if c == "*":
            if glob.startswith("**", i):
                out.append(".*")
                i += 2
                continue
            out.append("[^/]*")
        elif c == "?":
            out.append("[^/]")
        elif c == "[" and "]" in glob[i + 2:]:
            j = glob.index("]", i + 2)
            body = glob[i + 1:j].replace("\\", "\\\\").replace("/", "")
            if body.startswith("!"):
                out.append("[^" + body[1:] + ("/" if body[1:] else "") + "]")  # a negated class must not match a slash either
            else:
                out.append("[" + body + "]")
            i = j
        else:
            out.append(re.escape(c))
        i += 1
    return re.compile("".join(out) + r"\Z", re.S)


def allowed(path, globs):
    for g in globs:
        try:
            if glob_regex(g).match(path):
                return True
        except re.error:
            continue
    return False


def path_problems(items, globs, allow_file=ALLOW_FILE, limit=SIZE_LIMIT):
    """items: (path, size) pairs of files being added. Returns the problems, one per path and reason."""
    out = []
    for path, size in items:
        if allowed(path, globs):
            continue
        if sensitive_name(path):
            out.append(f"{path}: sensitive file name (not in {allow_file})")
        if size > limit:
            out.append(f"{path}: {size} bytes is over the {limit / 1024 / 1024:g} MB limit (not in {allow_file})")
    return list(dict.fromkeys(out))


def blob_sizes(shas, cwd):
    shas = sorted(set(shas))
    if not shas:
        return {}
    res = subprocess.run(["git", "cat-file", "--batch-check=%(objectname) %(objectsize)"], cwd=cwd, input="\n".join(shas) + "\n",
                         capture_output=True, text=True, check=True).stdout
    return {l.split()[0]: int(l.split()[1]) for l in res.splitlines() if len(l.split()) == 2 and l.split()[1].isdigit()}


def allow_at(ref, cwd=None, allow_file=ALLOW_FILE):
    """The allowlist as it is in ref (a commit), or nothing when the file is not there. Read from the base commit, never from the
    commit being judged: a commit cannot allow its own file."""
    r = subprocess.run(["git", "show", f"{ref}:{allow_file}"], cwd=cwd, capture_output=True)
    return parse_allow(r.stdout.decode("utf-8", errors="replace"), allow_file) if r.returncode == 0 else ([], [])


def run_paths(base, allow_ref=None, cfg=None):
    allow_file, limit, _ = settings(cfg)
    globs, problems = allow_at(allow_ref or base, common.ROOT, allow_file)
    rows = list(common.history_added_blobs(base))
    sizes = blob_sizes([b for _, _, b in rows], common.ROOT)
    return problems + path_problems([(p, sizes.get(b, 0)) for _, p, b in rows], globs, allow_file, limit)


def staged_paths(cfg=None):
    """Problems for the files staged in ROOT; the allowlist is the one in HEAD."""
    allow_file, limit, _ = settings(cfg)
    raw = subprocess.run(["git", "diff", "--cached", "-r", "-z", "--raw", "--no-abbrev", "--no-renames", "--diff-filter=AM"], cwd=common.ROOT,
                         capture_output=True, check=True).stdout.decode("utf-8", errors="replace")
    rows = list(common.parse_raw(raw))
    globs, problems = allow_at("HEAD", common.ROOT, allow_file)
    sizes = blob_sizes([b for _, b in rows], common.ROOT)
    return problems + path_problems([(p, sizes.get(b, 0)) for p, b in rows], globs, allow_file, limit)


def run(base, cfg=None):
    """Every line added by any commit in base..HEAD of ROOT (a secret added and removed again is still found) and every file added."""
    _, _, skip = settings(cfg)
    return check_lines(common.history_added_lines(base), skip) + run_paths(base, cfg=cfg)


def run_staged(cfg=None):
    """The same rule on the index of ROOT (the pre-commit hook)."""
    _, _, skip = settings(cfg)
    return check_lines(common.staged_lines(), skip) + staged_paths(cfg)


def tree_lines(root):
    """Yield (path, line) for every line of every tracked text file under root (the whole tree, not a diff)."""
    import pathlib
    root = pathlib.Path(root)
    names = subprocess.run(["git", "ls-files", "-z"], cwd=root, capture_output=True, text=True,
                           check=True).stdout.split("\0")
    for name in filter(None, names):
        try:
            with open(root / name, "rb") as f:
                text = decode_bytes(f.read())
        except OSError:
            continue
        if text is None:  # genuinely binary
            continue
        for line in text.split("\n"):
            yield name, line


def run_tree(root, skip=()):
    """Scan everything tracked in root; finds a secret that is already in the tree."""
    return check_lines(tree_lines(root), skip)


