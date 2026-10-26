"""The runner: a crashing check is a problem, an unusable base is a warning, rules come from the base commit."""
import hermetic  # noqa: F401  (first: paths and git isolation)
import io, pathlib, subprocess, tempfile, types, unittest
import gitsafe
from hermetic import OWNER, git_env
from agent_gate import config, run_all


def fake(result=None, boom=None):
    def run(base, cfg=None):
        if boom:
            raise boom
        return result or []
    return types.SimpleNamespace(run=run)


class Crash(unittest.TestCase):
    def test_crashing_check_is_a_problem_and_others_still_run(self):
        checks = [("first", fake(boom=KeyError("x"))), ("second", fake(["bad thing"])), ("third", fake())]
        bad, lines = run_all.run_checks(checks, "HEAD~1")
        text = "\n".join(lines)
        self.assertTrue(bad)
        self.assertIn("first: 1 problem(s)", text)
        self.assertIn("check crashed: KeyError", text)
        self.assertIn("second: 1 problem(s)", text)
        self.assertIn("third: ok", text)

    def test_all_green_is_not_bad(self):
        bad, lines = run_all.run_checks([("a", fake()), ("b", fake())], "HEAD~1")
        self.assertFalse(bad)
        self.assertEqual(lines, ["a: ok", "b: ok"])


class Repo(unittest.TestCase):
    """A scratch repository with two commits; the runner judges the second against the first."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.t = pathlib.Path(self.tmp.name)
        self.git("init", "-q", "-b", "main")
        gitsafe.assert_sandbox(self.t)
        self.commit("README.md", "x\n", "base")
        self.base = self.git("rev-parse", "HEAD")

    def git(self, *a, who=OWNER):
        return subprocess.run(["git", *a], cwd=self.t, env=git_env(who), capture_output=True, text=True, check=True).stdout.strip()

    def commit(self, name, text, msg, who=OWNER):
        (self.t / name).parent.mkdir(parents=True, exist_ok=True)
        (self.t / name).write_text(text)
        self.git("add", "-A")
        self.git("commit", "-qm", msg, who=who)

    def run_gate(self, base):
        out, err = io.StringIO(), io.StringIO()
        code = run_all.run(base, root=self.t, out=out, err=err)
        return code, out.getvalue(), err.getvalue()

    def test_unusable_base_warns_and_falls_back(self):
        self.commit("a.txt", "a\n", "second")
        for base in ("0" * 40, "no-such-ref-anywhere"):
            code, out, err = self.run_gate(base)
            self.assertIn("falling back to HEAD~1", err)
            self.assertEqual(code, 0, out)

    def test_usable_base_does_not_warn(self):
        self.commit("a.txt", "a\n", "second")
        self.assertEqual(self.run_gate(self.base)[2], "")

    def test_a_single_commit_without_a_base_is_an_error_not_green(self):
        with tempfile.TemporaryDirectory() as t:
            subprocess.run(["git", "init", "-q"], cwd=t, env=git_env(), check=True)
            subprocess.run(["git", "commit", "-q", "--allow-empty", "-m", "only"], cwd=t, env=git_env(), check=True)
            self.assertEqual(run_all.run(None, root=t, out=io.StringIO(), err=io.StringIO()), 1)

    def test_rules_come_from_the_base_commit_so_a_push_cannot_relax_them(self):
        self.commit(config.FILE, '[commits]\nallowed_emails = ["%s"]\n' % OWNER, "rules")
        base = self.git("rev-parse", "HEAD")
        # the same push widens the allowed list and commits as the newly allowed identity
        self.commit(config.FILE, '[commits]\nallowed_emails = ["%s", "x@example.invalid"]\n' % OWNER, "widen", who="x@example.invalid")
        code, out, _ = self.run_gate(base)
        self.assertEqual(code, 1, out)
        self.assertIn("is not an allowed identity", out)
        self.assertIn("rules from agent-gate.toml at " + base[:12], out)
        # after that push is in, the wider list is the base and applies
        code, out, _ = self.run_gate("HEAD")
        self.assertEqual(code, 0, out)

    def test_without_config_at_the_base_the_work_tree_file_is_used(self):
        self.commit(config.FILE, '[checks]\nenabled = ["secrets"]\n', "rules")
        code, out, _ = self.run_gate(self.base)
        self.assertIn("1 checks", out)
        self.assertIn("rules from agent-gate.toml in the work tree", out)

    def test_a_config_that_does_not_parse_is_red(self):
        self.commit(config.FILE, "[commits\n", "broken")
        base = self.git("rev-parse", "HEAD")
        self.commit("a.txt", "a\n", "next")
        code, out, _ = self.run_gate(base)
        self.assertEqual(code, 1)
        self.assertIn("does not parse", out)

    def test_an_unknown_check_name_is_red(self):
        self.commit(config.FILE, '[checks]\nenabled = ["secrets", "secretz"]\n', "typo")
        code, out, _ = self.run_gate(self.base)
        self.assertEqual(code, 1)
        self.assertIn("secretz", out)


if __name__ == "__main__":
    unittest.main()
