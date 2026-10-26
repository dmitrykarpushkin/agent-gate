"""Rule commit-identity: authors and committers come from an allowed list; messages and names carry no banned trailer or word.

Config [commits]: allowed_emails (empty: identities are not judged), allow_web_committer (default true: the committer
noreply@github.com of commits made in the GitHub web interface), banned_trailers (trailer keys such as co-authored-by,
matched on a line of their own), banned_words (fragments matched anywhere, also inside longer words).
The [language] policy also applies to messages and names.

Messages and names are normalised before matching (NFKD with marks and format characters dropped, NFKC, small capital
look-alikes and dashes made plain, white space collapsed, case folded), so a zero width space, a soft hyphen or full
width letters do not hide a banned word. The log is read NUL-separated, so a separator in a message cannot forge a record.
"""
import re, unicodedata
from .. import common
from .check_language import Policy

WEB_COMMITTER = "noreply@github.com"


def _small_capitals():
    """Latin small capital look-alikes (U+1D00 block and friends) mapped to the plain letter."""
    out = {}
    for letter in "abcdefghijklmnopqrstuvwxyz":
        for pattern in ("LATIN LETTER SMALL CAPITAL %s", "LATIN SMALL CAPITAL LETTER %s"):
            try:
                out[ord(unicodedata.lookup(pattern % letter.upper()))] = letter
                break
            except KeyError:
                pass
    return out


SMALL_CAPS = _small_capitals()
DASHES = {c: "-" for c in list(range(0x2010, 0x2016)) + [0x2212, 0xfe58, 0xfe63, 0xff0d, 0x2043, 0x2e3a, 0x2e3b]}


def normalise(text):
    """Make a message comparable: NFKD with marks and format characters (Mn, Me, Cf: combining accents, variation selectors,
    zero width space, soft hyphen, bidi marks) dropped, then NFKC (full width and compatibility forms become plain letters),
    small capital look-alikes and all dashes made plain, white space collapsed, case folded. Line breaks stay for the trailer rule."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if unicodedata.category(c) not in ("Mn", "Me", "Cf"))
    text = unicodedata.normalize("NFKC", text).translate({**SMALL_CAPS, **DASHES})
    text = "".join(c for c in text if unicodedata.category(c) not in ("Mn", "Me", "Cf"))
    text = re.sub(r"[^\S\n]+", " ", text.replace("\r", "\n"))
    return re.sub(r" ?\n ?", "\n", text).casefold()


class Rules:
    """The [commits] table, resolved."""

    def __init__(self, cfg):
        sec = (cfg or {}).get("commits") or {}
        self.allowed = {e.casefold() for e in sec.get("allowed_emails", ())}
        self.web = sec.get("allow_web_committer", True)
        trailers = [normalise(t).strip() for t in sec.get("banned_trailers", ()) if t.strip()]
        words = [normalise(w).strip() for w in sec.get("banned_words", ()) if w.strip()]
        self.line = re.compile(r"(?m)^ ?(" + "|".join(re.escape(t) for t in trailers) + r") ?:") if trailers else None
        self.flat = re.compile("|".join(re.escape(w) for w in words)) if words else None
        self.language = Policy(cfg)

    def banned(self, text):
        """The first banned fragment of a text, or None."""
        norm = normalise(text)
        m = (self.line and self.line.search(norm)) or (self.flat and self.flat.search(re.sub(r"\s+", " ", norm)))
        return m.group(0) if m else None

    def identity_problems(self, sha, author_email, committer_email):
        if not self.allowed:
            return []
        out = []
        for who, mail in (("author", author_email), ("committer", committer_email)):
            if mail.casefold() not in self.allowed and not (who == "committer" and self.web and mail == WEB_COMMITTER):
                out.append(f"{sha[:7]}: {who} {mail} is not an allowed identity")
        return out

    def message_problems(self, sha, message):
        out = []
        if self.language.found(message):
            out.append(f"{sha[:7]}: {self.language.label()} in commit message")
        b = self.banned(message)
        if b:
            out.append(f"{sha[:7]}: banned text in message: {b!r}")
        return out

    def check_commit(self, sha, author_email, committer_email, message, author_name="", committer_name=""):
        out = self.identity_problems(sha, author_email, committer_email) + self.message_problems(sha, message)
        for who, name in (("author", author_name), ("committer", committer_name)):
            if self.language.found(name):
                out.append(f"{sha[:7]}: {self.language.label()} in {who} name")
            b = self.banned(name)
            if b:
                out.append(f"{sha[:7]}: banned text in {who} name: {b!r}")
        return out


def run(base, cfg=None):
    """Every commit in base..HEAD. The fields are separated by NUL (`git log -z`), which cannot occur in any of them, so
    a separator character in a message or a name cannot forge or hide a record."""
    rules = Rules(cfg)
    out = []
    raw = common.git("log", "-z", "--format=%H%x00%ae%x00%ce%x00%an%x00%cn%x00%B", f"{base}..HEAD")
    fields = raw.split("\0")
    if fields and fields[-1] == "":
        fields.pop()
    if len(fields) % 6:
        return [f"commit log has {len(fields)} fields, not a multiple of 6: cannot be parsed"]
    for i in range(0, len(fields), 6):
        sha, ae, ce, an, cn, msg = fields[i:i + 6]
        sha = sha.strip("\n")
        if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", sha):
            out.append(f"{sha[:7]!r}: commit id is not a hash")
        found = rules.check_commit(sha, ae, ce, msg, an, cn)
        whole = "\n".join((ae, ce, an, cn, msg))  # the whole record too, in case a field boundary hides something
        if rules.language.found(whole) and not any(rules.language.label() in p for p in found):
            found.append(f"{sha[:7]}: {rules.language.label()} in commit record")
        out += found
    return out
