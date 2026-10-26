"""Shared git and decoding helpers for the checks. Each check returns a list of problem strings.

ROOT is the repository being judged. The command line sets it to the top level of the current git work tree;
tests point it at their scratch repositories."""
import pathlib, subprocess

ROOT = pathlib.Path.cwd()


def set_root(path):
    """Point every helper at the repository at path."""
    global ROOT
    ROOT = pathlib.Path(path)
    return ROOT


def tracked(root=None):
    """Names of all tracked files of root (default ROOT)."""
    out = subprocess.run(["git", "ls-files", "-z"], cwd=root or ROOT, capture_output=True, check=True).stdout.decode("utf-8", "replace")
    return [f for f in out.split("\0") if f]


def git(*args):
    # bytes, decoded here: text mode would turn a lone CR in the output into a newline and hide the rest of an added line
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, check=True).stdout.decode("utf-8", errors="replace")


SAMPLE_BYTES = 1_000_000  # the start of a file that decides text or binary; a text file is then scanned whole
NUL_LIMIT = 0.30  # more NULs than this and the content is binary, unless it reads as UTF-16 text


def usable_text(text):
    """Return text with NULs removed (so UTF-16 content matches like ASCII), or None for genuinely binary content:
    a NUL ratio above NUL_LIMIT is kept only when it looks like UTF-16 (at most 55% NULs and the other characters
    are almost all printable), which an image, an archive, a pyc or a zero-filled file never does."""
    if "\0" not in text:
        return text
    nul = text.count("\0")
    rest = text.replace("\0", "")
    if nul / len(text) > NUL_LIMIT:
        printable = sum(1 for c in rest if c.isprintable() or c in "\t\r\n")
        if nul / len(text) > 0.55 or not rest or printable / len(rest) < 0.9:
            return None
    return rest


def decode_bytes(data):
    """Decode file bytes for scanning: BOM or NUL-interleaved UTF-16 first, then UTF-8, then latin-1 (never skips).
    Returns None for binary content (see usable_text). Binary is judged on the first SAMPLE_BYTES, a text file is
    decoded whole, so a secret deep inside a big text file is still seen."""
    if len(data) > SAMPLE_BYTES and _decode(data[:SAMPLE_BYTES]) is None:
        return None
    return _decode(data)


def _decode(data):
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        text = data.decode("utf-16", errors="replace")
    elif data[:3] == b"\xef\xbb\xbf":
        text = data.decode("utf-8-sig", errors="replace")
    else:
        text = None
        if b"\0" in data:  # BOM-less UTF-16: NULs sit on one byte parity
            even, odd = data[0::2].count(0), data[1::2].count(0)
            half = len(data) // 2
            if max(even, odd) > 0.8 * half and min(even, odd) < 0.1 * half:
                text = data.decode("utf-16-le" if odd >= even else "utf-16-be", errors="replace")
        if text is None:
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError:
                text = data.decode("latin-1")
    return usable_text(text)


def parse_added(diff_text):
    """Yield (path, line) for every added line of a unified diff. Only lines after an @@ marker are content, so an
    added line that itself starts with ++ is still seen (it shows up as +++...). All added text of a file is kept,
    NULs are stripped (UTF-16 diffs from `git diff --text`) and binary content is skipped."""
    path, in_hunk, buf = None, False, []

    def flush():
        text = usable_text("\n".join(buf)) if buf else None
        return [(path, l) for l in text.split("\n")] if text is not None else []

    for line in diff_text.split("\n"):  # newline only: splitlines() also cuts at CR, FF, U+2028 and drops the tail of an added line
        if line.startswith("diff --git"):
            yield from flush()
            buf, in_hunk = [], False
        elif not in_hunk and line.startswith("+++ b/"):
            path = line[6:].split("\t")[0]
        elif not in_hunk and line.startswith('+++ "b/'):  # git quotes odd names; never keep the previous file's path
            path = line[7:].rstrip('"')
        elif line.startswith("@@"):
            in_hunk = True
        elif in_hunk and line.startswith("+"):
            buf.append(line[1:])
    yield from flush()


def added_lines(base, head="HEAD", text=False):
    """Yield (path, line) for every line added between base and head. text=True also reads files git treats as binary."""
    extra = ["--text"] if text else []
    yield from parse_added(git("-c", "core.quotepath=false", "diff", "--no-renames", "--unified=0", "--no-color", *extra, f"{base}..{head}"))


def added_paths(base, head="HEAD"):
    """Names of files added, modified or renamed (new name) between base and head, so a file with no added lines is still seen."""
    out = git("-c", "core.quotepath=false", "diff", "--name-only", "--diff-filter=AMR", "-z", f"{base}..{head}")
    return [n for n in out.split("\0") if n]


def _blob_text(blob):
    """Decoded text of a blob ("" for the all-zero id of an absent file, None for binary content)."""
    if not blob or set(blob) == {"0"}:
        return ""
    data = subprocess.run(["git", "cat-file", "blob", blob], cwd=ROOT, capture_output=True, check=True).stdout
    return decode_bytes(data)


def _raw_rows(raw):
    """Yield (fields, path) from `diff-tree --raw -z` output; fields = mode_old, mode_new, blob_old, blob_new, status."""
    parts = raw.split("\0")
    i = 0
    while i + 1 < len(parts):
        if parts[i].startswith(":"):
            yield parts[i][1:].split(" "), parts[i + 1]
            i += 2
        else:
            i += 1


def merge_added_lines(sha, parents):
    """Lines a merge commit has in a file that NO parent had in that file (conflict resolutions, evil merges). Read from the
    blobs, not from `show --cc`, which prints "Binary files differ" for a file with a NUL byte and hides its content."""
    per_parent = []
    for p in parents:
        rows = {}
        for f, path in _raw_rows(git("diff-tree", "-r", "-z", "--no-renames", "--no-abbrev", "--diff-filter=AM", p, sha)):
            rows[path] = (f[2], f[3], f[0], f[1])  # parent blob, merge blob, parent mode, merge mode
        per_parent.append(rows)
    for path in sorted(set.intersection(*[set(r) for r in per_parent])):
        if any("160000" in (r[path][2], r[path][3]) for r in per_parent):
            continue  # a gitlink holds a commit id, not a blob
        new = _blob_text(per_parent[0][path][1])
        if new is None:
            continue
        seen = set()
        for rows in per_parent:
            seen.update((_blob_text(rows[path][0]) or "").split("\n"))
        for line in new.split("\n"):
            if line not in seen:
                yield path, line


def history_added_lines(base, head="HEAD"):
    """Yield (path, line) for every line added by any single commit in base..head, so a line added in one commit and
    removed in a later one is still seen. A merge commit yields only what it adds that no parent had (conflict
    resolutions, evil merges); the rest comes from the commits it merges."""
    for sha in git("rev-list", f"{base}..{head}").split():
        parents = git("rev-list", "--no-walk", "--parents", sha).split()[1:]
        if len(parents) > 1:
            yield from merge_added_lines(sha, parents)
        else:
            yield from parse_added(git("-c", "core.quotepath=false", "show", "--no-renames", "--unified=0", "--no-color", "--text",
                                       "--format=", sha))


def parse_raw(raw):
    """Yield (path, blob_sha) from `diff-tree --raw -z` output (non-combined: one parent, or none with --root)."""
    parts = raw.split("\0")
    i = 0
    while i + 1 < len(parts):
        meta = parts[i]
        if not meta.startswith(":"):
            i += 1
            continue
        fields = meta[1:].split(" ")
        yield parts[i + 1], fields[3]
        i += 2


def history_added_blobs(base, head="HEAD"):
    """Yield (commit, path, blob_sha) for every file a commit in base..head adds or changes. For a merge commit only a file
    that differs from EVERY parent (the same path and content) counts, so what the merge merely brings in is left to the
    commits it merges."""
    for sha in git("rev-list", f"{base}..{head}").split():
        parents = git("rev-list", "--no-walk", "--parents", sha).split()[1:]
        flags = ["diff-tree", "-r", "-z", "--no-renames", "--diff-filter=AM"]
        if len(parents) > 1:
            sets = [set(parse_raw(git(*flags, p, sha))) for p in parents]
            found = set.intersection(*sets)
        else:
            found = set(parse_raw(git(*flags, "--root", "--no-commit-id", sha)))
        for path, blob in sorted(found):
            yield sha, path, blob


def staged_lines(text=True):
    """Yield (path, line) for every line added in the index (what the next commit would record) of ROOT.
    text=True also reads files git treats as binary (the secrets check); False skips them like the push-time language check."""
    extra = ["--text"] if text else []
    out = subprocess.run(["git", "-c", "core.quotepath=false", "diff", "--cached", "--no-renames", "--unified=0", "--no-color", *extra], cwd=ROOT,
                         capture_output=True, check=True).stdout.decode("utf-8", errors="replace")
    yield from parse_added(out)
