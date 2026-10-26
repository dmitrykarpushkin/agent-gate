"""Rule commit-signature: a commit authored by one of the listed people carries a signature.

Config [signatures]: signed_emails (author emails whose commits must be signed; empty: the check is off). Commits of
other authors (a bot identity, for example) are not looked at.

Presence only: the commit object has a gpgsig header. Whether the signature is valid needs the allowed-signers file
or keyring of the people involved and is not judged here (`git verify-commit` on a machine that has it)."""
from .. import common


def has_signature(sha):
    """True when the header part of the commit object (up to the first blank line) has a gpgsig line."""
    header = common.git("cat-file", "commit", sha).split("\n\n", 1)[0]
    return any(line.startswith("gpgsig") for line in header.split("\n"))


def run(base, cfg=None):
    """Every commit in base..HEAD whose author is listed and that has no signature header."""
    signed = {e.casefold() for e in ((cfg or {}).get("signatures") or {}).get("signed_emails", ())}
    if not signed:
        return []
    raw = common.git("log", "-z", "--format=%H%x00%ae", f"{base}..HEAD")
    fields = raw.split("\0")
    if fields and fields[-1] == "":
        fields.pop()
    if len(fields) % 2:
        return [f"commit log has {len(fields)} fields, not a multiple of 2: cannot be parsed"]
    out = []
    for i in range(0, len(fields), 2):
        sha, email = fields[i].strip("\n"), fields[i + 1]
        if email.casefold() in signed and not has_signature(sha):
            out.append(f"{sha[:7]}: commit by {email} without a signature")
    return out
