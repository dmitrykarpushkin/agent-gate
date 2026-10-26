"""The signature check: commits by listed authors must carry a gpgsig header; others are not looked at."""
import hermetic  # noqa: F401  (first: paths and git isolation)
import os, pathlib, subprocess, tempfile, unittest
from hermetic import OWNER, BOT, STRANGER
from agent_gate import common
from agent_gate.checks import check_signatures as _sig

CFG = {"signatures": {"signed_emails": [OWNER]}}


def run(base):
    return _sig.run(base, CFG)


class Signatures(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        old = common.ROOT
        common.ROOT = pathlib.Path(self.tmp.name)
        self.addCleanup(setattr, common, "ROOT", old)
        self.git("init", "-q")
        self.git("commit", "-q", "--allow-empty", "-m", "base", who=BOT)
        self.base = self.git("rev-parse", "HEAD")

    def git(self, *a, who=OWNER, name="n"):
        env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,
               "GIT_AUTHOR_NAME": name, "GIT_AUTHOR_EMAIL": who, "GIT_COMMITTER_NAME": name, "GIT_COMMITTER_EMAIL": who}
        return subprocess.run(["git", "-c", "commit.gpgsign=false", *a], cwd=self.tmp.name, env=env, check=True,
                              capture_output=True, text=True).stdout.strip()

    def test_unsigned_bot_commits_pass(self):
        self.git("commit", "-q", "--allow-empty", "-m", "bot work", who=BOT)
        self.assertEqual(run(self.base), [])

    def test_unsigned_owner_commit_is_reported(self):
        self.git("commit", "-q", "--allow-empty", "-m", "owner work")
        out = run(self.base)
        self.assertEqual(len(out), 1)
        self.assertIn("without a signature", out[0])

    def test_a_gpgsig_header_counts_as_signed(self):
        tree = self.git("rev-parse", "HEAD^{tree}")
        obj = (f"tree {tree}\nparent {self.base}\nauthor n <{OWNER}> 1 +0000\ncommitter n <{OWNER}> 1 +0000\n"
               "gpgsig -----BEGIN SSH SIGNATURE-----\n abc\n -----END SSH SIGNATURE-----\n\nsigned\n")
        sha = subprocess.run(["git", "hash-object", "-t", "commit", "-w", "--stdin"], cwd=self.tmp.name, input=obj,
                             check=True, capture_output=True, text=True).stdout.strip()
        self.git("update-ref", "HEAD", sha)
        self.assertEqual(run(self.base), [])

    def test_the_word_gpgsig_in_a_message_does_not_count(self):
        self.git("commit", "-q", "--allow-empty", "-m", "owner work\n\ngpgsig fake")
        self.assertEqual(len(run(self.base)), 1)

    def test_only_commits_after_the_base_are_judged(self):
        self.git("commit", "-q", "--allow-empty", "-m", "owner old")
        base = self.git("rev-parse", "HEAD")
        self.git("commit", "-q", "--allow-empty", "-m", "bot new", who=BOT)
        self.assertEqual(run(base), [])

    def test_every_unsigned_owner_commit_after_the_base_is_reported(self):
        for n in range(3):
            self.git("commit", "-q", "--allow-empty", "-m", f"owner {n}")
        self.assertEqual(len(run(self.base)), 3)

    def test_an_author_name_with_gpgsig_is_not_a_signature(self):
        self.git("commit", "-q", "--allow-empty", "-m", "owner named gpgsig", name="gpgsig")
        self.assertEqual(len(run(self.base)), 1)

    def test_a_case_variant_of_the_owner_email_is_still_the_owner(self):
        self.git("commit", "-q", "--allow-empty", "-m", "owner upper", who=OWNER.upper())
        self.assertEqual(len(run(self.base)), 1)

    def test_without_signed_emails_the_check_is_off(self):
        self.git("commit", "-q", "--allow-empty", "-m", "owner work")
        self.assertEqual(_sig.run(self.base, {}), [])

    def test_an_unparseable_log_is_one_problem_not_a_crash(self):
        from unittest import mock
        with mock.patch.object(common, "git", return_value="abc\0x@y\0def\0"):
            out = run(self.base)
        self.assertEqual(len(out), 1)
        self.assertIn("cannot be parsed", out[0])



SIG = ("-----BEGIN SSH SIGNATURE-----\n"
       " U1NIU0lHAAAAAQAAADMAAAALc3NoLWVkMjU1MTkAAAAg\n"
       " \n"
       " AAAAB3NzaC1lZDI1NTE5\n"
       " -----END SSH SIGNATURE-----")


class SignaturesExtra(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.t = tmp.name
        self.git("init", "-q")
        self.tree = self.git("mktree", stdin="")
        self.head = None
        self.base = self.commit(BOT, BOT, "base")
        old = common.ROOT
        common.ROOT = pathlib.Path(self.t)
        self.addCleanup(setattr, common, "ROOT", old)

    def git(self, *a, stdin=None):
        env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull}
        return subprocess.run(["git", "-c", "commit.gpgsign=false", *a], cwd=self.t, env=env, check=True,
                              input=stdin, capture_output=True, text=True).stdout.strip()

    def commit(self, author, committer, msg, sig=None, parents=None):
        """Write a raw commit object, move HEAD to it, return its sha."""
        parents = [self.head] if parents is None and self.head else (parents or [])
        lines = ["tree " + self.tree] + ["parent " + p for p in parents]
        lines.append("author A <%s> 1700000000 +0000" % author)
        lines.append("committer C <%s> 1700000000 +0000" % committer)
        if sig:
            lines.append("gpgsig " + sig)
        raw = "\n".join(lines) + "\n\n" + msg + "\n"
        sha = self.git("hash-object", "-t", "commit", "-w", "--stdin", stdin=raw)
        self.git("update-ref", "HEAD", sha)
        self.head = sha
        return sha

    def test_signed_owner_commit_with_multiline_gpgsig_passes(self):
        self.commit(OWNER, OWNER, "signed", sig=SIG)
        self.assertEqual(run(self.base), [])

    def test_gpgsig_line_in_message_is_not_a_signature(self):
        sha = self.commit(OWNER, OWNER, "subject\n\ngpgsig x\ngpgsig y")
        out = run(self.base)
        self.assertEqual(len(out), 1, out)
        self.assertTrue(out[0].startswith(sha[:7]), out)

    def test_unsigned_owner_commit_reported_with_short_sha(self):
        sha = self.commit(OWNER, OWNER, "unsigned")
        out = run(self.base)
        self.assertEqual(len(out), 1, out)
        self.assertTrue(out[0].startswith(sha[:7]), out)
        self.assertIsInstance(out[0], str)

    def test_owner_email_compared_case_insensitively(self):
        sha = self.commit(OWNER.upper(), OWNER, "upper")
        out = run(self.base)
        self.assertEqual(len(out), 1, out)
        self.assertTrue(out[0].startswith(sha[:7]))

    def test_unsigned_merge_commit_by_owner_reported(self):
        first = self.commit(BOT, BOT, "main side")
        other = self.commit(BOT, BOT, "other side", parents=[self.base])
        merge = self.commit(OWNER, OWNER, "merge", parents=[first, other])
        out = run(self.base)
        self.assertEqual(len(out), 1, out)
        self.assertTrue(out[0].startswith(merge[:7]), out)

    def test_signed_merge_commit_by_owner_passes(self):
        first = self.commit(BOT, BOT, "main side")
        other = self.commit(BOT, BOT, "other side", parents=[self.base])
        self.commit(OWNER, OWNER, "merge", sig=SIG, parents=[first, other])
        self.assertEqual(run(self.base), [])

    def test_committer_owner_author_bot_not_reported(self):
        self.commit(BOT, OWNER, "bot authored")
        self.assertEqual(run(self.base), [])

    def test_author_owner_committer_bot_is_reported(self):
        sha = self.commit(OWNER, BOT, "owner authored")
        out = run(self.base)
        self.assertEqual(len(out), 1, out)
        self.assertTrue(out[0].startswith(sha[:7]))

    def test_other_authors_never_reported(self):
        self.commit(STRANGER, STRANGER, "x")
        self.commit(BOT, BOT, "y")
        self.assertEqual(run(self.base), [])

    def test_base_equal_to_head_is_empty(self):
        self.commit(OWNER, OWNER, "unsigned before base")
        self.assertEqual(run("HEAD"), [])
        self.assertEqual(run(self.head), [])

    def test_commits_at_or_before_base_are_not_judged(self):
        self.base = self.commit(OWNER, OWNER, "unsigned old")
        self.commit(OWNER, OWNER, "signed new", sig=SIG)
        self.assertEqual(run(self.base), [])

    def test_mixed_signed_and_unsigned_report_only_unsigned(self):
        self.commit(OWNER, OWNER, "s1", sig=SIG)
        u1 = self.commit(OWNER, OWNER, "u1")
        self.commit(BOT, BOT, "bot")
        self.commit(OWNER, OWNER, "s2", sig=SIG)
        u2 = self.commit(OWNER, OWNER, "u2")
        out = run(self.base)
        self.assertEqual(len(out), 2, out)
        starts = {p[:7] for p in out}
        self.assertEqual(starts, {u1[:7], u2[:7]})

    def test_each_commit_reported_once(self):
        shas = [self.commit(OWNER, OWNER, "u%d" % i) for i in range(4)]
        out = run(self.base)
        self.assertEqual(len(out), 4, out)
        self.assertEqual(sorted(p[:7] for p in out), sorted(s[:7] for s in shas))
        self.assertEqual(len(set(out)), 4)

    def test_diamond_merge_does_not_duplicate_reports(self):
        a = self.commit(OWNER, OWNER, "a")
        b = self.commit(OWNER, OWNER, "b", parents=[self.base])
        self.commit(BOT, BOT, "m", parents=[a, b])
        out = run(self.base)
        self.assertEqual(sorted(p[:7] for p in out), sorted([a[:7], b[:7]]))


if __name__ == "__main__":
    unittest.main()
