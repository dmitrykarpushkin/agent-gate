"""Rule supply-chain-pins: no floating package launches and no package.json without a lockfile.

Reported: `npx -y` / `npm exec -y` / `bunx` / `pnpm dlx` and `uvx` / `pipx run` with no exact pin (`==<digit>` or `@x.y.z`) on the command,
also in an MCP config in JSON, TOML or YAML (`command` naming the launcher; a JSON server object is read whole, so the key order does not matter, TOML and YAML are read per server block),
a bare `npx tool` (reported unless a tracked lockfile sits in the script's folder, above it or below it, or the same file runs `npm ci`/`npm install` first, or the line says `supply-chain: allow`),
an `npm ci` / `npm install` without `--ignore-scripts` (reported unless the line says `supply-chain: allow` or the file is listed in
install_scripts_ok), in any tracked script, unit or config (not in .md prose); and a tracked package.json that has dependencies
but no lockfile next to it. Package compromises keep arriving through install scripts and floating version ranges; exact pins
and lockfiles are the cheap defence. Not checked: version ranges inside lockfiles.

Config [supply_chain]: skip (path prefixes not scanned, such as test fixtures), install_scripts_ok (a table of
file = "reason" whose npm install may run install scripts, for example a build that needs a native binary).
"""
import json, pathlib, re
from .. import common
from ..common import decode_bytes

TEXT = (".py", ".sh", ".yaml", ".yml", ".json", ".service", ".timer", ".md", ".toml", ".js", ".jsx", ".ts", ".mjs")
LAUNCH = re.compile(r"\b(?:npx(?:\s+-\S+)*?\s+(?:-y|--yes)|npm\s+exec(?:\s+-\S+)*?\s+(?:-y|--yes)|bunx|pnpm\s+dlx|uvx|pipx\s+run)\b([^;&|\n#]*)")
PIN = re.compile(r"==\d|@\d+\.\d+\.\d+")
CMD = re.compile(r"""command["']?\s*[:=]\s*["']?(?:\S*/)?(?:npx|bunx|uvx|pipx)["']?\b""")
BARE_NPX = re.compile(r"(?:^|[\s;&|(])npx\b(?:\s+-\S+)*\s+(\S+)")
INSTALL = re.compile(r"\bnpm\s+(?:ci|install|i)\b([^;&|\n#]*)")
ALLOW = "supply-chain: allow"
SCRIPT_EXT = (".sh", ".service", ".timer")  # only real scripts: install and bare-npx rules would hit prose in json/yaml data
MCP_LAUNCHERS = ("npx", "bunx", "uvx", "pipx")
LOCKS = ("package-lock.json", "npm-shrinkwrap.json", "yarn.lock", "pnpm-lock.yaml", "bun.lock", "bun.lockb")


def is_text_name(name):
    base = name.rsplit("/", 1)[-1]
    return name.endswith(TEXT) or "." not in base


def json_servers(node):
    """Yield every dict that has a `command` naming a package launcher, in any key order."""
    if isinstance(node, dict):
        cmd = node.get("command")
        if isinstance(cmd, str) and cmd.rsplit("/", 1)[-1] in MCP_LAUNCHERS:
            yield node
        for v in node.values():
            yield from json_servers(v)
    elif isinstance(node, list):
        for v in node:
            yield from json_servers(v)


def mcp_problems(name, text):
    try:
        data = json.loads(text)
    except ValueError:
        data = None
    if data is not None:
        return [f"{name}: MCP config launches a package without an exact version pin"
                for srv in json_servers(data) if not PIN.search(json.dumps(srv.get("args", [])))]
    out = []
    lines = text.split("\n")
    for m in CMD.finditer(text):
        i = text.count("\n", 0, m.start())
        if not PIN.search(block_text(lines, i)):
            out.append(f"{name}:{i + 1}: MCP config launches a package without an exact version pin")
    return out


def _indent(line):
    """Indent of a line, counting a leading YAML list dash as part of it."""
    return len(line) - len(line.lstrip(" -")) if line.lstrip().startswith("- ") else len(line) - len(line.lstrip())


def block_text(lines, i):
    """The lines of the server block that holds line i (TOML/YAML): bounded by blank lines, a shallower line,
    a TOML [header] or the next list item at the same level, so a neighbour's pin cannot mask this launch."""
    ci = _indent(lines[i])
    lo = i
    while lo > 0 and not lines[i].lstrip().startswith("- "):
        prev = lines[lo - 1]
        if not prev.strip() or _indent(prev) < ci or (ci == 0 and prev.startswith("[")):
            break
        lo -= 1
        if prev.lstrip().startswith("- ") and _indent(prev) == ci:
            break
    hi = i + 1
    while hi < len(lines):
        nxt = lines[hi]
        if not nxt.strip() or _indent(nxt) < ci or (ci == 0 and nxt.startswith("[")) or (nxt.lstrip().startswith("- ") and _indent(nxt) == ci):
            break
        hi += 1
    return "\n".join(lines[lo:hi])[:600]


def has_lock_near(name, files):
    """A tracked lockfile in the folder of `name`, above it or below it."""
    folder = name.rsplit("/", 1)[0] + "/" if "/" in name else ""
    for f in files:
        if f.rsplit("/", 1)[-1] in LOCKS:
            lf = f.rsplit("/", 1)[0] + "/" if "/" in f else ""
            if folder.startswith(lf) or (folder and lf.startswith(folder)):  # a script at the repo root does not count every lockfile below it
                return True
    return False


def launch_problems(name, text, files=(), install_ok=()):
    out = []
    installed = False
    lock_near = None
    for lineno, line in enumerate(text.splitlines(), 1):
        code = line.lstrip()
        skip_new = code.startswith(("#", "echo", "printf")) or ALLOW in line  # escape hatch of the new rules only
        floating = LAUNCH.search(line)
        for m in LAUNCH.finditer(line):
            if not PIN.search(m.group(1)):
                out.append(f"{name}:{lineno}: package launch without an exact version pin: {m.group(0).strip()[:60]}")
        if skip_new or not (name.endswith(SCRIPT_EXT) or "." not in name.rsplit("/", 1)[-1]):
            continue
        im = INSTALL.search(line)
        if im:
            installed = True
            if "--ignore-scripts" not in im.group(1) and name not in install_ok:
                out.append(f"{name}:{lineno}: npm install without --ignore-scripts: {im.group(0).strip()[:60]}")
        bm = BARE_NPX.search(line)
        if bm and not floating and not PIN.search(bm.group(1)) and not installed:
            if lock_near is None:
                lock_near = has_lock_near(name, files)
            if not lock_near:
                out.append(f"{name}:{lineno}: bare npx without a lockfile near it or a prior npm ci: {bm.group(0).strip()[:60]}")
    out += mcp_problems(name, text)
    return out


def lock_problems(root, files, skip=()):
    out = []
    names = set(files)
    for f in files:
        if not f.endswith("package.json") or (skip and f.startswith(skip)):
            continue
        try:
            data = json.loads((root / f).read_text())
        except (ValueError, OSError):
            continue
        if not any(data.get(k) for k in ("dependencies", "devDependencies", "optionalDependencies")):
            continue
        folder = f.rsplit("/", 1)[0] + "/" if "/" in f else ""
        if not any(folder + lock in names for lock in LOCKS):
            out.append(f"{f}: has dependencies but no lockfile next to it")
    return out


def run(base=None, root=None, cfg=None):
    root = pathlib.Path(root or common.ROOT)
    sec = (cfg or {}).get("supply_chain") or {}
    skip, install_ok = tuple(sec.get("skip", ())), dict(sec.get("install_scripts_ok", {}))
    files = common.tracked(root)
    out = lock_problems(root, files, skip)
    for name in files:
        if (skip and name.startswith(skip)) or name.endswith(".md") or not is_text_name(name):
            continue
        p = root / name
        if p.is_file():
            text = decode_bytes(p.read_bytes())
            if text:
                out += launch_problems(name, text, files, install_ok)
    return out
