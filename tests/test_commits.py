"""The commit identity and message check, and the normalisation that defeats look-alike evasions."""
import hermetic  # noqa: F401  (first: paths and git isolation)
import os, pathlib, subprocess, tempfile, unicodedata, unittest
from hermetic import OWNER, BOT
from agent_gate import common
from agent_gate.checks import check_commits

CYR = "".join(chr(c) for c in (0x43f, 0x440, 0x438, 0x432, 0x435, 0x442))  # a Cyrillic word, built at runtime
CFG = {"commits": {"allowed_emails": [OWNER, BOT], "banned_trailers": ["co-authored-by", "claude-session"],
                   "banned_words": ["generated with", "claude", "anthropic"]},
       "language": {"forbid": "cyrillic"}}
RULES = check_commits.Rules(CFG)


def run(base):
    return check_commits.run(base, CFG)


class Commits(unittest.TestCase):
    def test_owner_and_bot_ok(self):
        self.assertEqual(RULES.check_commit("abc1234", OWNER, OWNER, "state: add"), [])
        self.assertEqual(RULES.check_commit("abc1234", BOT, BOT, "state: add"), [])

    def test_unknown_author_rejected(self):
        self.assertTrue(RULES.check_commit("abc1234", "x@y.z", OWNER, "m"))

    def test_cyrillic_message_rejected(self):
        self.assertTrue(RULES.check_commit("abc1234", BOT, BOT, CYR))

    def test_web_committer_allowed(self):
        self.assertEqual(RULES.check_commit("abc1234", OWNER, check_commits.WEB_COMMITTER, "m"), [])

    def test_trailers_and_ai_mentions_rejected(self):
        self.assertTrue(RULES.check_commit("abc1234", BOT, BOT, "m\n\nCo-Authored-By: someone"))
        self.assertTrue(RULES.check_commit("abc1234", BOT, BOT, "Generated with a tool"))
        self.assertTrue(RULES.check_commit("abc1234", BOT, BOT, "ask Claude"))

    def test_evasions_of_the_banned_words_are_caught(self):
        zw = chr(0x200b)  # zero width space (a format character)
        cases = {
            "format character inside the word": "ask Cl" + zw + "aude",
            "soft hyphen inside the word": "ask An" + chr(0xad) + "thropic",
            "full width letters": "ask " + "".join(chr(ord(c) + 0xfee0) for c in "Claude"),
            "upper case": "ASK CLAUDE",
            "non breaking space in the phrase": "Generated" + chr(0xa0) + "with a tool",
            "many spaces in the phrase": "generated   with a tool",
            "newline in the phrase": "generated\nwith a tool",
            "trailer with leading spaces": "m\n\n  Co-Authored-By: someone",
            "trailer with a format character": "m\n\nCo-Authored" + zw + "-By: someone",
            "session trailer with a no break space": "m\n\nClaude-Session" + chr(0xa0) + ": x",
        }
        for name, msg in cases.items():
            self.assertTrue(RULES.check_commit("abc1234", BOT, BOT, msg), name)

    def test_more_evasions_of_the_banned_words_are_caught(self):
        vs = chr(0xfe0f)  # variation selector
        comb = chr(0x301)  # combining acute accent
        small = {c: unicodedata.lookup("LATIN LETTER SMALL CAPITAL " + c) for c in "CLAUDE"}
        cases = {
            "variation selector": "ask Cla" + vs + "ude",
            "combining mark": "ask Cla" + comb + "ude",
            "small capitals": "ask " + "".join(small[c] for c in "CLAUDE"),
            "small capitals anthropic": "ask " + "".join(unicodedata.lookup("LATIN LETTER SMALL CAPITAL " + c) if c != "H" else "h" for c in "ANTHROPIC"),
            "hyphen U+2010": "m\n\nCo" + chr(0x2010) + "Authored" + chr(0x2010) + "By: x",
            "hyphen U+2011": "m\n\nCo" + chr(0x2011) + "Authored" + chr(0x2011) + "By: x",
            "dash U+2013": "m\n\nCo" + chr(0x2013) + "Authored" + chr(0x2013) + "By: x",
            "dash U+2015": "m\n\nCo" + chr(0x2015) + "Authored" + chr(0x2015) + "By: x",
            "word joined": "uses ClaudeCode here",
            "underscore": "see claude_x",
            "digit": "claude3",
        }
        for name, msg in cases.items():
            self.assertTrue(RULES.check_commit("abc1234", BOT, BOT, msg), name)

    def test_separator_characters_in_a_message_cannot_forge_or_hide_a_record(self):
        with tempfile.TemporaryDirectory() as t:
            def git(*a, who=BOT):
                env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,
                       "GIT_AUTHOR_NAME": "n", "GIT_AUTHOR_EMAIL": who, "GIT_COMMITTER_NAME": "n", "GIT_COMMITTER_EMAIL": who}
                return subprocess.run(["git", "-c", "commit.gpgsign=false", *a], cwd=t, env=env, check=True,
                                      capture_output=True, text=True).stdout.strip()
            git("init", "-q")
            git("commit", "-q", "--allow-empty", "-m", "base")
            base = git("rev-parse", "HEAD")
            old = common.ROOT
            common.ROOT = pathlib.Path(t)
            self.addCleanup(setattr, common, "ROOT", old)
            git("commit", "-q", "--allow-empty", "-m", "bare \x1e separator")
            self.assertEqual(run(base), [])
            forged = "ok\x1e" + "a" * 40 + "\x1f" + BOT + "\x1f" + BOT + "\x1fn\x1fn\x1fclean"
            git("commit", "-q", "--allow-empty", "-m", forged + "\n\nCo-Authored-By: x")
            out = run(base)
            self.assertTrue(any("banned" in p for p in out), out)
            git("commit", "-q", "--allow-empty", "-m", "x\x1f" * 7 + " ask Claude")
            self.assertTrue(any("Claude".casefold() in p.casefold() for p in run(base)))

    def test_cyrillic_in_extended_ranges_is_caught(self):
        for cp in (0x1c80, 0x2de0, 0xa640):  # outside 0x400-0x4ff
            self.assertTrue(RULES.check_commit("abc1234", BOT, BOT, "ok " + chr(cp)), hex(cp))

    def test_author_and_committer_names_are_checked(self):
        zw = chr(0x200b)
        self.assertTrue(RULES.check_commit("abc1234", BOT, BOT, "m", author_name="Cl" + zw + "aude"))
        self.assertTrue(RULES.check_commit("abc1234", BOT, BOT, "m", committer_name="Claude"))
        self.assertTrue(RULES.check_commit("abc1234", BOT, BOT, "m", author_name="Anthropic Bot"))
        self.assertTrue(RULES.check_commit("abc1234", BOT, BOT, "m", committer_name=CYR))
        self.assertEqual(RULES.check_commit("abc1234", BOT, BOT, "m", author_name="repo-bot", committer_name="Jane Doe"), [])

    def test_run_checks_names_of_a_temp_repo(self):
        with tempfile.TemporaryDirectory() as t:
            def git(*a, name="n"):
                e = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull, "GIT_AUTHOR_EMAIL": BOT,
                     "GIT_COMMITTER_EMAIL": BOT, "GIT_AUTHOR_NAME": name, "GIT_COMMITTER_NAME": name}
                return subprocess.run(["git", "-c", "commit.gpgsign=false", *a], cwd=t, env=e, check=True,
                                      capture_output=True, text=True).stdout.strip()
            git("init", "-q")
            git("commit", "-q", "--allow-empty", "-m", "base")
            base = git("rev-parse", "HEAD")
            old = common.ROOT
            common.ROOT = pathlib.Path(t)
            self.addCleanup(setattr, common, "ROOT", old)
            git("commit", "-q", "--allow-empty", "-m", "fine")
            self.assertEqual(run(base), [])
            git("commit", "-q", "--allow-empty", "-m", "named", name="Cl" + chr(0x200b) + "aude")
            out = run(base)
            self.assertEqual(len(out), 2, out)  # author and committer
            self.assertTrue(all("name" in p for p in out), out)

    def test_run_reads_history_of_a_temp_repo(self):
        with tempfile.TemporaryDirectory() as t:
            def git(*a, who=OWNER):
                env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,
                       "GIT_AUTHOR_NAME": "n", "GIT_AUTHOR_EMAIL": who, "GIT_COMMITTER_NAME": "n", "GIT_COMMITTER_EMAIL": who}
                return subprocess.run(["git", "-c", "commit.gpgsign=false", *a], cwd=t, env=env, check=True,
                                      capture_output=True, text=True).stdout.strip()
            git("init", "-q")
            git("commit", "-q", "--allow-empty", "-m", "base")
            base = git("rev-parse", "HEAD")
            old = common.ROOT
            common.ROOT = pathlib.Path(t)
            self.addCleanup(setattr, common, "ROOT", old)
            self.assertEqual(run(base), [])
            git("commit", "-q", "--allow-empty", "-m", "clean one")
            self.assertEqual(run(base), [])
            git("commit", "-q", "--allow-empty", "-m", "bad author", who="x@y.z")
            git("commit", "-q", "--allow-empty", "-m", "trailer\n\nCo-Authored-By: someone <a@b.c>")
            out = run(base)
            self.assertEqual(len(out), 3, out)
            self.assertEqual(sum("not an allowed identity" in p for p in out), 2, out)
            self.assertEqual(sum("banned text" in p for p in out), 1, out)
            self.assertEqual(sum("clean" in p for p in out), 0, out)

    def test_run_whole_record_net_catches_cyrillic_only_the_email_fields_hold_and_never_doubles_up(self):
        with tempfile.TemporaryDirectory() as t:
            def git(*a, mail=OWNER, name="n"):
                env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,
                       "GIT_AUTHOR_NAME": name, "GIT_AUTHOR_EMAIL": mail, "GIT_COMMITTER_NAME": name, "GIT_COMMITTER_EMAIL": mail}
                return subprocess.run(["git", "-c", "commit.gpgsign=false", *a], cwd=t, env=env, check=True,
                                      capture_output=True, text=True).stdout.strip()
            git("init", "-q")
            git("commit", "-q", "--allow-empty", "-m", "base")
            base = git("rev-parse", "HEAD")
            old = common.ROOT
            common.ROOT = pathlib.Path(t)
            self.addCleanup(setattr, common, "ROOT", old)
            git("commit", "-q", "--allow-empty", "-m", "mail", mail="a" + CYR + "@users.noreply.github.com")
            out = run(base)
            self.assertEqual(sum("Cyrillic in commit record" in p for p in out), 1, out)
            self.assertEqual(sum("not an allowed identity" in p for p in out), 2, out)
            git("reset", "-q", "--hard", base)
            git("commit", "-q", "--allow-empty", "-m", "body " + CYR)  # the message check sees it: the net stays silent
            out = run(base)
            self.assertEqual(sum("Cyrillic" in p for p in out), 1, out)
            git("reset", "-q", "--hard", base)
            git("commit", "-q", "--allow-empty", "-m", "name", name=CYR)  # author and committer name: two reports, no net
            out = run(base)
            self.assertEqual(sorted(p.split(": ", 1)[1] for p in out), ["Cyrillic in author name", "Cyrillic in committer name"], out)


class Config(unittest.TestCase):
    def test_without_allowed_emails_identities_are_not_judged(self):
        rules = check_commits.Rules({})
        self.assertEqual(rules.check_commit("abc1234", "x@y.z", "x@y.z", "ask Claude"), [])

    def test_the_web_committer_can_be_refused(self):
        rules = check_commits.Rules({"commits": {"allowed_emails": [OWNER], "allow_web_committer": False}})
        self.assertTrue(rules.check_commit("abc1234", OWNER, check_commits.WEB_COMMITTER, "m"))

    def test_emails_compare_case_insensitively(self):
        self.assertEqual(RULES.check_commit("abc1234", OWNER.upper(), OWNER, "m"), [])

    def test_a_trailer_is_banned_only_on_its_own_line_and_a_word_anywhere(self):
        self.assertEqual(RULES.banned("see co-authored-by: in the docs"), None)
        self.assertEqual(RULES.banned("x\nCo-authored-by: y"), "co-authored-by:")
        self.assertEqual(RULES.banned("talked to anthropic support"), "anthropic")


if __name__ == "__main__":
    unittest.main()
