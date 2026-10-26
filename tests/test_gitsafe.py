import hermetic  # noqa: F401  (first: paths and git isolation)
import os, pathlib, re, subprocess, sys, tempfile, unittest
import gitsafe

HERE = pathlib.Path(__file__).resolve().parent


def git(cwd, *a, env=None):
    return subprocess.run(["git", "-c", "commit.gpgsign=false", *a], cwd=cwd, env=env, capture_output=True, text=True)


class GitSafe(unittest.TestCase):
    """The failure this guards against: a hook in a linked worktree exported GIT_DIR and the fixtures wrote into the outer repo."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.t = pathlib.Path(self.tmp.name)
        git(self.t, "init", "-q", "--bare", str(self.t / "sink.git"))
        git(self.t, "init", "-q", "-b", "main", str(self.t / "outer"))
        git(self.t / "outer", "remote", "add", "origin", str(self.t / "sink.git"))

    def tearDown(self):
        self.tmp.cleanup()

    def fixture_under_hook_env(self, preamble):
        """A fixture like test_hooks.Scratch, run in a child whose environment has GIT_DIR of the outer repo."""
        code = preamble + (
            "import subprocess, sys\nt = sys.argv[1]\n"
            "g = lambda cwd, *a: subprocess.run(['git', '-c', 'commit.gpgsign=false', *a], cwd=cwd, capture_output=True)\n"
            "g(t, 'init', '-q', '-b', 'main', t + '/repo')\n"
            "g(t + '/repo', 'config', 'user.name', 't'); g(t + '/repo', 'config', 'user.email', 't@example.invalid')\n"
            "g(t + '/repo', 'commit', '-q', '--allow-empty', '-m', 'one')\n"
            "g(t + '/repo', 'push', '-q', 'origin', 'HEAD:refs/heads/main')\n")
        env = dict(os.environ, GIT_DIR=str(self.t / "outer" / ".git"))
        subprocess.run([sys.executable, "-c", code, str(self.t)], cwd=self.t, env=env, capture_output=True, check=True)

    def outer_touched(self):
        cfg = git(self.t / "outer", "config", "--local", "--get", "user.name").stdout.strip()
        refs = git(self.t / "sink.git", "for-each-ref").stdout.strip()
        return cfg, refs

    def test_without_the_scrub_the_fixture_leaks_into_the_outer_repo(self):
        # Pins the mechanism, so the next test proves something.
        self.fixture_under_hook_env("")
        cfg, refs = self.outer_touched()
        self.assertEqual(cfg, "t")
        self.assertIn("refs/heads/main", refs)

    def test_importing_gitsafe_keeps_the_fixture_in_its_own_repo(self):
        self.fixture_under_hook_env("import sys; sys.path.insert(0, %r); import gitsafe\n" % str(HERE))
        self.assertEqual(self.outer_touched(), ("", ""))

    def test_assert_sandbox_refuses_a_remote_origin_and_the_enclosing_repo(self):
        repo = self.t / "r"
        git(self.t, "init", "-q", str(repo))
        gitsafe.assert_sandbox(repo)  # a fresh local repo is fine
        git(repo, "remote", "add", "origin", "https://github.com/example/x")
        with self.assertRaises(RuntimeError):
            gitsafe.assert_sandbox(repo)
        if gitsafe._common_dir(HERE) is not None:
            with self.assertRaises(RuntimeError):
                gitsafe.assert_sandbox(HERE)

    def test_scrub_drops_injected_git_config(self):
        env = {"GIT_CONFIG_PARAMETERS": "'core.bare=true'", "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "core.bare",
               "GIT_CONFIG_VALUE_0": "true", "GIT_CONFIG_KEY_12": "a", "GIT_CONFIG_VALUE_12": "b", "GIT_DIR": "/x", "PATH": "/bin"}
        self.assertEqual(gitsafe.scrub(env), {"PATH": "/bin"})

    def test_importing_gitsafe_drops_injected_config_from_the_child(self):
        injected = ("GIT_CONFIG_PARAMETERS", "GIT_CONFIG_COUNT", "GIT_CONFIG_KEY_0", "GIT_CONFIG_VALUE_0")
        code = ("import sys; sys.path.insert(0, %r); import gitsafe, os; print(sorted(k for k in os.environ if k in %r))"
                % (str(HERE), injected))
        env = dict(os.environ, GIT_CONFIG_PARAMETERS="'core.bare=true'", GIT_CONFIG_COUNT="1",
                   GIT_CONFIG_KEY_0="core.bare", GIT_CONFIG_VALUE_0="true")
        r = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, check=True)
        self.assertEqual(r.stdout.strip(), "[]")

    def test_assert_sandbox_refuses_an_origin_that_is_the_enclosing_repo(self):
        outer = gitsafe._common_dir(HERE)
        if outer is None:
            self.skipTest("not inside a git repository")
        repo = self.t / "r2"
        git(self.t, "init", "-q", str(repo))
        top = pathlib.Path(gitsafe._git(HERE, "rev-parse", "--show-toplevel"))
        for url in (str(outer), str(top), "file://" + str(outer), str(outer) + "/../" + outer.name):
            git(repo, "remote", "remove", "origin")
            git(repo, "remote", "add", "origin", url)
            with self.assertRaises(RuntimeError, msg=url):
                gitsafe.assert_sandbox(repo)

    def test_assert_sandbox_allows_a_local_bare_sink_and_a_relative_one(self):
        repo = self.t / "r3"
        git(self.t, "init", "-q", str(repo))
        for url in (str(self.t / "sink.git"), "file://" + str(self.t / "sink.git"), "../sink.git"):
            git(repo, "remote", "remove", "origin")
            git(repo, "remote", "add", "origin", url)
            gitsafe.assert_sandbox(repo)


class EveryGitTestImportsGitsafe(unittest.TestCase):
    """A test file that runs git without importing gitsafe (directly or through hermetic) can write into the enclosing repo under a hook."""
    ALLOW = {"gitsafe.py": "the module itself", "hermetic.py": "imports it"}
    RUNS_GIT = re.compile(r"""["']git["']|\bgit\s+(init|commit|clone|push|add|config|remote)\b""")
    IMPORTS = re.compile(r"^\s*(import (gitsafe|hermetic)\b|from (gitsafe|hermetic) import|import [^#\n]*\b(gitsafe|hermetic)\b)", re.M)

    def test_scan(self):
        bad = []
        for f in sorted(HERE.glob("*.py")):
            if f.name in self.ALLOW:
                continue
            src = f.read_text()
            if self.RUNS_GIT.search(src) and not self.IMPORTS.search(src):
                bad.append(f.name)
        self.assertEqual(bad, [], "run git without importing gitsafe")

    def test_scan_notices_a_missing_import(self):
        self.assertTrue(self.RUNS_GIT.search("subprocess.run(['git', 'init'])"))
        self.assertTrue(self.RUNS_GIT.search("os.system('git init x')"))
        self.assertFalse(self.IMPORTS.search("# import gitsafe\nx = 1"))
        self.assertTrue(self.IMPORTS.search("import os\nimport gitsafe  # noqa\n"))

if __name__ == "__main__":
    unittest.main()
