"""The git hooks end to end, in scratch repositories with the real hooks installed by hooks/install.sh."""
import hermetic  # noqa: F401  (first: paths and git isolation)
import pathlib, shutil, subprocess, tempfile, unittest
import gitsafe
from hermetic import OWNER, BOT, STRANGER, ROOT

INSTALL = ROOT / "hooks" / "install.sh"
CYR = "".join(chr(c) for c in (0x43f, 0x440, 0x438))  # Cyrillic letters, built at runtime


def key():
    return "sk-ant-" + "a" * 24  # the shape of a credential, built at runtime


def sh(cwd, *cmd, **kw):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, **kw)


class Scratch(unittest.TestCase):
    """A repo with the hooks installed and an origin that is a local bare repository."""
    CONFIG = ""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        t = pathlib.Path(self.tmp.name)
        self.remote, self.repo = t / "remote.git", t / "repo"
        sh(t, "git", "init", "-q", "--bare", "-b", "main", str(self.remote))
        sh(t, "git", "init", "-q", "-b", "main", str(self.repo))
        gitsafe.assert_sandbox(self.repo)
        self.identity(OWNER)
        sh(self.repo, "git", "remote", "add", "origin", str(self.remote))
        r = sh(self.repo, "sh", str(INSTALL))
        self.assertEqual(r.returncode, 0, r.stderr)
        if self.CONFIG:
            (self.repo / "agent-gate.toml").write_text(self.CONFIG)

    def identity(self, email, repo=None):
        for k, v in (("user.name", "t"), ("user.email", email)):
            sh(repo or self.repo, "git", "config", k, v)

    def write(self, name, text):
        p = self.repo / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)

    def commit(self, msg="next", *extra):
        sh(self.repo, "git", "add", "-A")
        return sh(self.repo, "git", "commit", "-q", "--allow-empty", "-m", msg, *extra)

    def push(self, ref="HEAD:main", repo=None):
        return sh(repo or self.repo, "git", "push", "-q", "origin", ref)


PUSH_CONFIG = '[push]\nbranches = ["main"]\ntest_command = "python3 -m unittest discover -s tests"\n'


class PrePush(Scratch):
    CONFIG = PUSH_CONFIG

    def setUp(self):
        super().setUp()
        self.write_test(True)
        self.assertEqual(self.commit("one").returncode, 0)

    def write_test(self, ok):
        self.write("tests/test_x.py", "import unittest\nclass T(unittest.TestCase):\n    def test(self):\n"
                                      "        self.assertTrue(%s)\n" % ok)

    def test_install_points_git_at_the_hooks_of_this_clone(self):
        self.assertEqual(sh(self.repo, "git", "config", "core.hooksPath").stdout.strip(), str(INSTALL.parent.resolve()))

    def test_green_goes_through_and_says_what_it_ran(self):
        r = self.push()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("tests green", r.stdout)
        self.assertIn("secrets: ok", r.stdout)

    def test_red_test_is_blocked_and_shows_the_failure(self):
        self.assertEqual(self.push().returncode, 0)
        self.write_test(False)
        self.commit()
        r = self.push()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("tests are red", r.stderr)
        self.assertIn("FAIL: test", r.stderr)
        self.assertIn("AssertionError", r.stderr)

    def test_pushed_sha_is_checked_not_working_copy(self):
        self.assertEqual(self.push().returncode, 0)
        self.write_test(False)
        self.commit("red")
        sh(self.repo, "git", "branch", "redref")
        sh(self.repo, "git", "reset", "-q", "--hard", "HEAD~1")  # the working copy is green again
        r = self.push("redref:refs/heads/main")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("tests are red", r.stderr)

    def test_only_the_pushed_tip_is_tested_not_each_commit_in_range(self):
        # Pins the documented limit: a red commit in the middle of a push is not tested when the tip is green.
        self.assertEqual(self.push().returncode, 0)
        self.write_test(False)
        self.commit("red middle")
        self.write_test(True)
        self.commit("green tip")
        r = self.push()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(sh(self.repo, "git", "rev-parse", "HEAD").stdout, sh(self.remote, "git", "rev-parse", "main").stdout)

    def test_other_branch_not_checked_unless_listed(self):
        self.write_test(False)
        self.commit("red")
        self.assertEqual(self.push("HEAD:refs/heads/side").returncode, 0)

    def test_a_listed_branch_is_checked(self):
        self.write(".gitignore", "")
        (self.repo / "agent-gate.toml").write_text(PUSH_CONFIG.replace('["main"]', '["main", "release"]'))
        self.commit("rules")
        self.assertEqual(self.push().returncode, 0)
        self.write_test(False)
        self.commit("red")
        r = self.push("HEAD:refs/heads/release")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("tests are red", r.stderr)

    def test_a_secret_committed_past_the_pre_commit_hook_is_stopped_at_push(self):
        self.assertEqual(self.push().returncode, 0)
        self.write("notes.txt", "k = " + key() + "\n")
        self.assertEqual(self.commit("sneak", "--no-verify").returncode, 0)
        self.write("notes.txt", "clean again\n")
        self.commit("remove it")
        r = self.push()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("notes.txt: possible anthropic key", r.stdout)
        self.assertIn("checks are red", r.stderr)

    def test_the_whole_range_is_judged_on_a_first_push_to_an_empty_remote(self):
        self.write("notes.txt", "k = " + key() + "\n")
        self.commit("sneak", "--no-verify")
        self.write("notes.txt", "clean again\n")
        self.commit("remove it")
        r = self.push()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("possible anthropic key", r.stdout)

    def test_a_push_cannot_switch_off_its_own_tests(self):
        self.assertEqual(self.push().returncode, 0)
        self.write_test(False)
        (self.repo / "agent-gate.toml").write_text(PUSH_CONFIG.replace("python3 -m unittest discover -s tests", "true"))
        self.commit("red, and tests switched off")
        r = self.push()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("tests are red", r.stderr)

    def test_shallow_clone_is_unshallowed_before_the_checks_run(self):
        self.assertEqual(self.push().returncode, 0)
        self.commit("two")
        self.assertEqual(self.push().returncode, 0)
        shallow = pathlib.Path(self.tmp.name) / "shallow"
        self.assertEqual(sh(self.tmp.name, "git", "clone", "-q", "--depth", "1", "file://" + str(self.remote), str(shallow)).returncode, 0)
        self.identity(OWNER, shallow)
        self.assertEqual(sh(shallow, "sh", str(INSTALL)).returncode, 0)
        sh(shallow, "git", "commit", "-q", "--allow-empty", "-m", "three")
        r = self.push(repo=shallow)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("shallow clone", r.stderr)
        self.assertEqual(sh(shallow, "git", "rev-parse", "--is-shallow-repository").stdout.strip(), "false")


class Identity(Scratch):
    CONFIG = '[commits]\nallowed_emails = ["%s", "%s"]\n[signatures]\nsigned_emails = ["%s"]\n' % (OWNER, BOT, OWNER)

    def setUp(self):
        super().setUp()
        self.identity(BOT)
        self.assertEqual(self.commit("rules").returncode, 0)
        self.assertEqual(self.push().returncode, 0)

    def test_a_foreign_identity_is_refused_at_commit_time(self):
        self.identity(STRANGER)
        r = self.commit("work")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("is not an allowed identity", r.stdout + r.stderr)

    def test_a_foreign_author_is_refused_at_push_time(self):
        self.write("a.txt", "a\n")
        self.commit("work", "--no-verify", "--author", "x <%s>" % STRANGER)
        r = self.push()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("author %s is not an allowed identity" % STRANGER, r.stdout)

    def test_an_unsigned_commit_by_a_listed_author_is_refused_at_push(self):
        self.identity(OWNER)
        self.write("a.txt", "a\n")
        self.assertEqual(self.commit("work").returncode, 0)
        r = self.push()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("commit by %s without a signature" % OWNER, r.stdout)

    def test_the_bot_identity_needs_no_signature(self):
        self.write("a.txt", "a\n")
        self.assertEqual(self.commit("work").returncode, 0)
        self.assertEqual(self.push().returncode, 0)


class PreCommit(Scratch):
    CONFIG = ('[commits]\nbanned_trailers = ["co-authored-by"]\nbanned_words = ["generated with"]\n'
              '[language]\nforbid = "cyrillic"\nold_lines_only = ["NOTES.md"]\n')

    def test_secret_is_stopped_before_it_enters_history(self):
        self.write("notes.txt", "key = " + key() + "\n")
        r = self.commit()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("anthropic key", r.stdout + r.stderr)
        self.assertNotEqual(sh(self.repo, "git", "rev-parse", "-q", "--verify", "HEAD").returncode, 0)

    def test_a_key_file_is_stopped_by_its_name(self):
        self.write("deploy/id_ed25519", "whatever\n")
        r = self.commit()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("sensitive file name", r.stdout + r.stderr)

    def test_clean_commit_goes_through_and_only_added_lines_count(self):
        self.write("notes.txt", "one\n")
        self.assertEqual(self.commit().returncode, 0)
        self.write("notes.txt", "one\ntwo\n")
        self.assertEqual(self.commit().returncode, 0)

    def test_forbidden_script_is_stopped_before_it_enters_history(self):
        self.write("notes.txt", "hello " + CYR + "\n")
        r = self.commit()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("Cyrillic", r.stdout + r.stderr)

    def test_old_line_in_an_old_lines_only_file_is_not_flagged(self):
        old = "rule " + CYR + "\n"
        self.write("NOTES.md", old)
        self.assertEqual(self.commit("m", "--no-verify").returncode, 0)
        self.write("NOTES.md", old + "new english line\n")
        self.assertEqual(self.commit().returncode, 0)
        self.write("NOTES.md", old + "new english line\nnew " + CYR + "\n")
        self.assertNotEqual(self.commit().returncode, 0)

    def test_banned_text_in_the_message_is_refused_at_commit_time(self):
        for message in ("Generated with some tool", "tidy\n\nCo-Authored-By: someone <a@example.invalid>"):
            self.write("m.txt", message)
            r = self.commit(message)
            self.assertNotEqual(r.returncode, 0, message)
            self.assertIn("commit-msg: banned text", r.stderr)
        self.assertNotEqual(sh(self.repo, "git", "rev-parse", "-q", "--verify", "HEAD").returncode, 0)

    def test_forbidden_script_in_the_message_is_refused(self):
        r = self.commit("fix " + CYR)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("commit-msg: Cyrillic", r.stderr)

    def test_verbose_commit_diff_below_the_scissors_line_is_not_the_message(self):
        self.write("NOTES.md", "rule\n")
        self.assertEqual(self.commit("start").returncode, 0)
        self.write("NOTES.md", "rule\nmore co-authored-by: x\n")
        sh(self.repo, "git", "add", "-A")
        r = sh(self.repo, "git", "commit", "-v", "-m", "plain msg")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_modules_committed_to_the_repo_cannot_shadow_the_standard_library_in_the_hooks(self):
        for name in ("json.py", "subprocess.py", "re.py", "tomllib.py"):
            self.write(name, "raise SystemExit('shadowed')\n")
        self.assertEqual(self.commit("modules named like the standard library", "--no-verify").returncode, 0)
        self.write("notes.txt", "fine\n")
        r = self.commit("clean")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.write("notes.txt", "fine\nkey = " + key() + "\n")
        r = self.commit("key")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("anthropic key", r.stdout + r.stderr)

    def test_rules_of_head_apply_not_the_staged_config(self):
        self.assertEqual(self.commit("start").returncode, 0)
        self.write("agent-gate.toml", "")  # staged: no rules at all
        self.write("notes.txt", "hello " + CYR + "\n")
        self.assertNotEqual(self.commit().returncode, 0)


class FailClosed(unittest.TestCase):
    def test_a_missing_launcher_refuses_the_commit(self):
        with tempfile.TemporaryDirectory() as t:
            t = pathlib.Path(t)
            gate = t / "agent-gate"
            for d in ("agent_gate", "bin", "hooks"):
                shutil.copytree(ROOT / d, gate / d, ignore=shutil.ignore_patterns("__pycache__"))
            repo = t / "repo"
            sh(t, "git", "init", "-q", "-b", "main", str(repo))
            gitsafe.assert_sandbox(repo)
            sh(repo, "git", "config", "user.name", "t")
            sh(repo, "git", "config", "user.email", OWNER)
            self.assertEqual(sh(repo, "sh", str(gate / "hooks" / "install.sh")).returncode, 0)
            (gate / "bin" / "stopline").unlink()
            (repo / "a.txt").write_text("a\n")
            sh(repo, "git", "add", "-A")
            r = sh(repo, "git", "commit", "-qm", "m")
            self.assertNotEqual(r.returncode, 0)


if __name__ == "__main__":
    unittest.main()
