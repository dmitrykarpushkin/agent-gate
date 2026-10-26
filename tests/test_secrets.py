"""The secrets check: credential shapes in added lines, sensitive file names, big blobs, the allowlist, history and merges."""
import hermetic  # noqa: F401  (first: paths and git isolation)
import os, pathlib, random, shutil, subprocess, sys, tempfile, time, unittest, unittest.mock
import gitsafe
from hermetic import LAUNCHER
from agent_gate import common
from agent_gate.checks import check_secrets

ALLOW = check_secrets.ALLOW_FILE
SECRET = "gh" + "p_" + "a1B2c3D4" * 3  # built from pieces, never a real token


def sh(cwd, *cmd):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)


def cli(cwd, *args):
    return subprocess.run([sys.executable, "-I", str(LAUNCHER), *args], cwd=cwd, capture_output=True, text=True)


class Shapes(unittest.TestCase):
    def test_rejects_known_shapes(self):
        bad = ["sk-ant-" + "a" * 20, "ghp_" + "b" * 24, "AKIA" + "C" * 16,
               "-----BEGIN " + "PRIVATE KEY-----", "x.trycloud" + "flare.com", "pass" + "word = hunter22x"]
        for b in bad:
            self.assertTrue(check_secrets.check_lines([("a.txt", b)]), b)

    def test_allows_reference_to_helper(self):
        self.assertEqual(check_secrets.check_lines([("a.md", "use the secret helper with NAME")]), [])

class TunnelPatternSpeed(unittest.TestCase):
    def test_long_single_character_line_is_checked_fast(self):
        import time
        for ch in ("a", "-", "0"):
            line = ch * 300_000
            t = time.monotonic()
            self.assertEqual(check_secrets.check_lines([("f.txt", line)]), [])
            self.assertLess(time.monotonic() - t, 1.0, "tunnel url pattern is slow on a long line of %r" % ch)

    def test_tunnel_urls_are_still_found(self):
        for host in ("abc-12.try" + "cloudflare.com", "x.y.ngrok" + "-free.app", "my-box.tail1234.ts" + ".net", "a" * 63 + ".ts" + ".net"):
            self.assertEqual(check_secrets.check_lines([("f.txt", "see https://" + host + "/x")]), ["f.txt: possible tunnel url"], host)
        self.assertEqual(check_secrets.check_lines([("f.txt", "a" * 300 + ".ts" + ".net")]), [])  # a label over 63 characters is not a host name


class MorePatterns(unittest.TestCase):
    def test_other_provider_keys_google_keys_and_bearer_tokens_are_caught(self):
        bad = {
            "openai key": "sk-proj-" + "a1B2" * 10,
            "openai key (legacy)": "sk-" + "a1B2c3D4" * 5,
            "google api key": "AIza" + "Sy" + "a" * 33,
            "groq key": "gsk_" + "a1B2" * 13,
            "huggingface token": "hf_" + "aB" * 17,
            "xai key": "xai-" + "a1B2" * 20,
            "bearer token": "Authorization: Bearer " + "abcDEF123456" * 3,
        }
        for name, text in bad.items():
            hits = check_secrets.check_lines([("a.txt", text)])
            self.assertTrue(hits, name)
            self.assertIn(name.split(" (")[0].split()[0], hits[0].lower(), name)

    def test_harmless_lookalikes_pass(self):
        ok = ["Authorization: Bearer <token>", "send a Bearer header", "the sk- prefix", "task-force-one-two-three-four-five",
              "ask-for-help-with-this-long-sentence-xx", "hf_ is a prefix", "AIza is a prefix", "disk-usage-report-for-the-server-01"]
        for text in ok:
            self.assertEqual(check_secrets.check_lines([("a.txt", text)]), [], text)


class GapPatterns(unittest.TestCase):
    def test_long_dotted_line_is_checked_fast_for_credential_urls(self):
        import time
        for unit in ("a.", "a-", "aa.ts"):
            line = unit * (300_000 // len(unit))
            t = time.monotonic()
            self.assertEqual(check_secrets.check_lines([("f.txt", line)]), [])
            self.assertLess(time.monotonic() - t, 1.0, "credential url pattern is slow on %r" % unit)

    def test_more_credential_shapes_are_caught(self):
        a = "aB3dE6gH9jK2mN5pQ8"
        bad = {
            "stripe key": "sk_" + "live_" + a + "xyz",
            "stripe key (restricted)": "rk_" + "live_" + a + "xyz",
            "npm token": "npm" + "_" + "a1B2c3" * 6,
            "sendgrid key": "SG" + "." + a + "." + a + "-_",
            "jwt": "eyJ" + a + "." + "eyJ" + a + "." + a,
            "url with credentials": "postgres" + "://" + "admin" + ":" + "hunter2x" + "@" + "db.example.org/app",
            "cloudflare token": "CLOUDFLARE_API" + "_TOKEN=" + a + "xyz",
            "api key assignment": "api" + "_key = '" + a + "xyz'",
            "ngrok host": "https://" + "abc-12" + ".ngrok-free" + ".app/x",
            "tailscale host": "box" + "." + "tail1a2b3" + ".ts" + ".net",
        }
        for name, text in bad.items():
            hits = check_secrets.check_lines([("a.txt", text)])
            self.assertTrue(hits, name)

    def test_lookalikes_for_the_new_patterns_pass(self):
        ok = ["sk_live_ is the Stripe prefix", "pk_" + "live_" + "a" * 20, "npm_ prefix", "SG.xxx", "eyJ is the JWT start",
              "https://user:<password>@host/path", "https://user:${PASS}@host/path", "https://example.org/a:b@c",
              "CLOUDFLARE_API_TOKEN=$CLOUDFLARE_API_TOKEN", "CLOUDFLARE_API_TOKEN=<token>", "api_key = os.environ['K']",
              "api_key = None", "api_key: str", "api_key: YOUR_API_KEY_GOES_HERE_PLEASE", "api_key = ANTHROPIC_API_KEY_FROM_ENV", "apikey = get_api_key_from_environment()", "the ngrok-free tunnel", "a .ts.net host", "ts.net"]
        for text in ok:
            self.assertEqual(check_secrets.check_lines([("a.txt", text)]), [], text)


class FullTree(unittest.TestCase):
    def make_repo(self, files):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        t = pathlib.Path(self.tmp.name)
        sh(t, "git", "init", "-q", "-b", "main")
        for name, text in files.items():
            (t / name).parent.mkdir(parents=True, exist_ok=True)
            (t / name).write_text(text)
        sh(t, "git", "add", "-A")
        return t

    def test_secret_already_in_the_tree_is_found(self):
        t = self.make_repo({"notes/a.md": "fine\n", "notes/b.md": "key sk-ant-" + "a" * 20 + "\n"})
        problems = check_secrets.run_tree(t)
        self.assertEqual(len(problems), 1)
        self.assertIn("notes/b.md", problems[0])
        self.assertIn("anthropic key", problems[0])

    def test_clean_tree_is_clean(self):
        t = self.make_repo({"a.md": "nothing here\n"})
        self.assertEqual(check_secrets.run_tree(t), [])

    def test_untracked_files_are_not_scanned(self):
        t = self.make_repo({"a.md": "ok\n"})
        (t / "local.txt").write_text("ghp_" + "b" * 24 + "\n")
        self.assertEqual(check_secrets.run_tree(t), [])

    def test_binary_files_are_skipped_without_crashing(self):
        t = self.make_repo({"a.md": "ok\n"})
        (t / "b.bin").write_bytes(b"\xff\xfe\x00\x01 sk-ant-" + b"a" * 20)
        sh(t, "git", "add", "-A")
        self.assertEqual(check_secrets.run_tree(t), [])

    def test_command_line_mode_exits_1_on_a_hit(self):
        t = self.make_repo({"x.txt": "AKIA" + "C" * 16 + "\n"})
        r = cli(t, "tree", str(t))
        self.assertEqual(r.returncode, 1)
        self.assertIn("x.txt: possible aws key id", r.stdout)

    def test_command_line_mode_exits_0_when_clean(self):
        t = self.make_repo({"x.txt": "hello\n"})
        r = cli(t, "tree", str(t))
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_staged_mode_sees_only_what_is_staged(self):
        t = self.make_repo({"a.md": "ok\n"})
        sh(t, "git", "-c", "user.name=t", "-c", "user.email=t@x", "-c", "commit.gpgsign=false", "commit", "-qm", "one")
        (t / "b.md").write_text("ghp_" + "b" * 24 + "\n")
        (t / "c.md").write_text("AKIA" + "C" * 16 + "\n")
        sh(t, "git", "add", "b.md")  # c.md stays untracked
        r = cli(t, "staged")
        self.assertEqual(r.returncode, 1)
        self.assertIn("b.md: possible github token", r.stdout)
        self.assertNotIn("c.md", r.stdout)

    def test_staged_mode_is_quiet_when_clean(self):
        t = self.make_repo({"a.md": "ok\n"})
        r = cli(t, "staged")
        self.assertEqual((r.returncode, r.stdout), (0, ""), r.stderr)

    def test_reading_a_secret_from_the_environment_is_not_a_secret(self):
        self.assertEqual(check_secrets.check_lines([("a.py", 'secret = os.environ.get("X_SECRET")')]), [])
        self.assertTrue(check_secrets.check_lines([("a.py", 'sec' + 'ret = "hunter22x"')]))

    def test_a_real_token_in_a_test_file_is_found(self):
        token = "gh" + "p_" + "a1B2c3D4e5" * 4
        self.assertTrue(check_secrets.check_lines([("tests/x.py", token)]))
        t = self.make_repo({"tests/x.py": f"T = '{token}'\n"})
        self.assertTrue(check_secrets.run_tree(t))

    def test_a_skipped_file_is_exempt_and_only_by_its_exact_path(self):
        token = "gh" + "p_" + "a1B2c3D4e5" * 4
        skip = ("agent_gate/checks/check_secrets.py",)
        self.assertEqual(check_secrets.check_lines([("agent_gate/checks/check_secrets.py", token)], skip), [])
        for name in ("agent_gate/checks/check_secrets.py.bak", "agent_gate/checks/check_secrets.py.orig", "x/agent_gate/checks/check_secrets.py"):
            self.assertTrue(check_secrets.check_lines([(name, token)], skip), name)

    def test_the_tree_scan_reads_skip_from_the_config(self):
        token = "gh" + "p_" + "a1B2c3D4e5" * 4
        t = self.make_repo({"fixture.txt": token + "\n", "agent-gate.toml": '[secrets]\nskip = ["fixture.txt"]\n'})
        r = cli(t, "tree", str(t))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_this_repository_is_clean(self):
        if not (hermetic.ROOT / ".git").exists():
            self.skipTest("not a git checkout")
        self.assertEqual(check_secrets.run_tree(hermetic.ROOT, ("agent_gate/checks/check_secrets.py",)), [])


class RenamedFiles(unittest.TestCase):
    def commit(self, t, msg):
        sh(t, "git", "-c", "user.name=t", "-c", "user.email=t@x", "-c", "commit.gpgsign=false", "commit", "-qm", msg)

    def test_a_moved_file_still_shows_its_added_lines(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        t = pathlib.Path(self.tmp.name)
        sh(t, "git", "init", "-q", "-b", "main")
        (t / "old.txt").write_text("line one\nline two\nline three\n")
        sh(t, "git", "add", "-A")
        self.commit(t, "one")
        sh(t, "git", "mv", "old.txt", "new.txt")
        self.commit(t, "move")
        old_root = common.ROOT
        common.ROOT = t
        self.addCleanup(setattr, common, "ROOT", old_root)
        self.assertEqual(sorted(common.added_lines("HEAD~1")), [("new.txt", "line one"), ("new.txt", "line three"), ("new.txt", "line two")])

    def test_a_moved_file_is_seen_in_the_staged_diff(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        t = pathlib.Path(self.tmp.name)
        sh(t, "git", "init", "-q", "-b", "main")
        (t / "old.txt").write_text("ok\nok2\nAKIA" + "C" * 16 + "\n")
        sh(t, "git", "add", "-A")
        self.commit(t, "one")
        sh(t, "git", "mv", "old.txt", "new.txt")
        r = cli(t, "staged")
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("new.txt: possible aws key id", r.stdout)


class PushHistory(unittest.TestCase):
    def test_a_secret_added_then_removed_in_the_range_is_still_found(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        t = pathlib.Path(self.tmp.name)
        sh(t, "git", "init", "-q", "-b", "main")
        commit = ["git", "-c", "user.name=t", "-c", "user.email=t@x", "-c", "commit.gpgsign=false", "commit", "-qm", "c"]
        (t / "a.txt").write_text("fine\n")
        sh(t, "git", "add", "-A")
        sh(t, *commit)
        base = sh(t, "git", "rev-parse", "HEAD").stdout.strip()
        (t / "a.txt").write_text("fine\nAKIA" + "C" * 16 + "\n")
        sh(t, "git", "add", "-A")
        sh(t, *commit)
        (t / "a.txt").write_text("fine\n")
        sh(t, "git", "add", "-A")
        sh(t, *commit)
        old_root = common.ROOT
        common.ROOT = t
        self.addCleanup(setattr, common, "ROOT", old_root)
        self.assertEqual(list(common.added_lines(base)), [])  # the net diff is empty
        self.assertEqual(check_secrets.run(base), ["a.txt: possible aws key id"])

    def test_a_secret_in_a_file_moved_in_the_range_is_found_by_the_push_check(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        t = pathlib.Path(self.tmp.name)
        sh(t, "git", "init", "-q", "-b", "main")
        commit = ["git", "-c", "user.name=t", "-c", "user.email=t@x", "-c", "commit.gpgsign=false", "commit", "-qm", "c"]
        (t / "old.txt").write_text("fine\nAKIA" + "C" * 16 + "\nmore\n")
        sh(t, "git", "add", "-A")
        sh(t, *commit)
        base = sh(t, "git", "rev-parse", "HEAD").stdout.strip()
        sh(t, "git", "mv", "old.txt", "new.txt")
        sh(t, *commit)
        old_root = common.ROOT
        common.ROOT = t
        self.addCleanup(setattr, common, "ROOT", old_root)
        self.assertEqual(check_secrets.run(base), ["new.txt: possible aws key id"])



class DiffParsing(unittest.TestCase):
    def test_secret_after_a_line_separator_character_is_still_seen(self):
        tok = "sk-ant-" + "api03-" + "x" * 20
        for sep in ("\r", "\x0c", "\u2028", "\x0b", "\x85"):
            diff = "diff --git a/n.txt b/n.txt\n--- /dev/null\n+++ b/n.txt\n@@ -0,0 +1 @@\n+note" + sep + tok + "\n"
            found = check_secrets.check_lines(common.parse_added(diff))
            self.assertEqual(found, ["n.txt: possible anthropic key"], repr(sep))

    def test_a_secret_after_a_lone_cr_is_seen_through_git_in_the_push_and_staged_paths(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        t = pathlib.Path(self.tmp.name)
        sh(t, "git", "init", "-q", "-b", "main")
        commit = ["git", "-c", "user.name=t", "-c", "user.email=t@x", "-c", "commit.gpgsign=false", "commit", "-qm", "c"]
        (t / "a.txt").write_text("fine\n")
        sh(t, "git", "add", "-A")
        sh(t, *commit)
        base = sh(t, "git", "rev-parse", "HEAD").stdout.strip()
        tok = "sk-ant-" + "api03-" + "x" * 20
        (t / "cr.txt").write_bytes(("note\r" + tok + "\n").encode())
        sh(t, "git", "add", "-A")
        r = cli(t, "staged")
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("cr.txt: possible anthropic key", r.stdout)
        sh(t, *commit)
        old_root = common.ROOT
        common.ROOT = t
        self.addCleanup(setattr, common, "ROOT", old_root)
        self.assertEqual(check_secrets.run(base), ["cr.txt: possible anthropic key"])

    def test_tree_scan_sees_a_secret_after_a_line_separator_character(self):
        import shutil
        t = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, t, True)
        sh(t, "git", "init", "-q")
        (t / "n.txt").write_text("note\u2028" + "sk-ant-" + "api03-" + "x" * 20 + "\n", encoding="utf-8", newline="")
        sh(t, "git", "add", "n.txt")
        self.assertEqual(check_secrets.run_tree(t), ["n.txt: possible anthropic key"])

    def test_added_line_starting_with_plus_plus_is_seen(self):
        diff = ("diff --git a/x.txt b/x.txt\n--- /dev/null\n+++ b/x.txt\n@@ -0,0 +1,2 @@\n"
                "+++ starts with two pluses\n+plain\n")
        self.assertEqual(list(common.parse_added(diff)),
                         [("x.txt", "++ starts with two pluses"), ("x.txt", "plain")])

    def test_header_is_not_content_and_paths_follow_files(self):
        diff = ("diff --git a/a b/a\n--- a/a\n+++ b/a\n@@ -1 +1 @@\n-old\n+new a\n"
                "diff --git a/b b/b\n--- a/b\n+++ b/b\n@@ -0,0 +1 @@\n+new b\n")
        self.assertEqual(list(common.parse_added(diff)), [("a", "new a"), ("b", "new b")])

    def test_bearer_needs_a_digit_so_prose_is_not_flagged(self):
        self.assertEqual(check_secrets.check_lines([("a.md", "bearer authenticationschemesdescribed")]), [])
        self.assertTrue(check_secrets.check_lines([("a.py", "Authorization: Bea" + "rer abcdef0123456789abcdefghij")]))


    def test_quoted_header_does_not_inherit_the_previous_path(self):
        diff = ("diff --git a/tests/a.py b/tests/a.py\n+++ b/tests/a.py\n@@ -0,0 +1 @@\n+x\n"
                'diff --git "a/src/\\303\\251.md" "b/src/\\303\\251.md"\n+++ "b/src/\\303\\251.md"\n@@ -0,0 +1 @@\n+y\n')
        paths = [p for p, _ in common.parse_added(diff)]
        self.assertEqual(paths[0], "tests/a.py")
        self.assertNotEqual(paths[1], "tests/a.py")


class MergeCommits(unittest.TestCase):
    """A secret added only by a merge commit (an evil merge or a conflict resolution) must be seen by the history scan."""

    def make_repo(self, t):
        def git(*a):
            return sh(t, "git", "-c", "commit.gpgsign=false", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *a)
        git("init", "-q", "-b", "main")
        (pathlib.Path(t) / "f.txt").write_text("one\n")
        git("add", "-A"); git("commit", "-qm", "base")
        base = git("rev-parse", "HEAD").stdout.strip()
        git("checkout", "-qb", "side")
        (pathlib.Path(t) / "g.txt").write_text("side\n")
        git("add", "-A"); git("commit", "-qm", "side")
        git("checkout", "-q", "main")
        (pathlib.Path(t) / "f.txt").write_text("one\nmain\n")
        git("add", "-A"); git("commit", "-qm", "main")
        return git, base

    def scan(self, t, base, fn=None):
        old = common.ROOT
        common.ROOT = pathlib.Path(t)
        try:
            return fn() if fn else check_secrets.run(base)
        finally:
            common.ROOT = old

    def test_a_merge_resolving_a_gitlink_does_not_crash_the_scans(self):
        with tempfile.TemporaryDirectory() as t:
            git, base = self.make_repo(t)
            t1 = git("rev-parse", "HEAD").stdout.strip()
            git("checkout", "-q", "side")
            git("update-index", "--add", "--cacheinfo", "160000," + base + ",sub")
            git("commit", "-qm", "link side")
            git("checkout", "-q", "main")
            git("update-index", "--add", "--cacheinfo", "160000," + t1 + ",sub")
            git("commit", "-qm", "link main")
            git("merge", "--no-ff", "--no-commit", "side")
            third = git("rev-parse", "HEAD").stdout.strip()
            git("update-index", "--cacheinfo", "160000," + third + ",sub")
            git("commit", "-qm", "merge")
            self.assertEqual(self.scan(t, base), [])
            self.assertIsInstance(self.scan(t, base, lambda: list(common.history_added_lines(base))), list)

    def test_evil_merge_secret_is_found(self):
        with tempfile.TemporaryDirectory() as t:
            git, base = self.make_repo(t)
            git("merge", "--no-ff", "--no-commit", "side")
            (pathlib.Path(t) / "evil.txt").write_text("key = " + "sk-ant-" + "a1B2c3D4e5F6g7" + "\n")
            git("add", "-A"); git("commit", "-qm", "merge")
            self.assertEqual(self.scan(t, base), ["evil.txt: possible anthropic key"])

    def test_conflict_resolution_secret_is_found(self):
        with tempfile.TemporaryDirectory() as t:
            git, base = self.make_repo(t)
            git("checkout", "-q", "side")
            (pathlib.Path(t) / "f.txt").write_text("one\nside\n")
            git("add", "-A"); git("commit", "-qm", "side f")
            git("checkout", "-q", "main")
            self.assertNotEqual(git("merge", "--no-ff", "side").returncode, 0)
            (pathlib.Path(t) / "f.txt").write_text("one\ntok = " + "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2" + "\n")
            git("add", "-A"); git("commit", "-qm", "merge")
            self.assertEqual(self.scan(t, base), ["f.txt: possible github token"])

    def test_conflict_resolution_with_a_nul_byte_is_still_scanned(self):
        with tempfile.TemporaryDirectory() as t:
            git, base = self.make_repo(t)
            git("checkout", "-q", "side")
            (pathlib.Path(t) / "f.txt").write_text("one\nside\n")
            git("add", "-A"); git("commit", "-qm", "side f")
            git("checkout", "-q", "main")
            self.assertNotEqual(git("merge", "--no-ff", "side").returncode, 0)
            body = "a\ncaf\u00e9 \x00 sk-ant-" + "a" * 20 + "\nc\n"
            (pathlib.Path(t) / "f.txt").write_bytes(body.encode("utf-8"))
            git("add", "-A"); git("commit", "-qm", "merge")
            lines = self.scan(t, base, lambda: list(common.history_added_lines(base)))
            self.assertTrue(any("sk-ant-" in l for _, l in lines), lines)
            self.assertTrue(any("\u00e9" in l for _, l in lines), lines)
            self.assertEqual(self.scan(t, base), ["f.txt: possible anthropic key"])

    def test_clean_merge_does_not_scan_the_side_branch_twice(self):
        with tempfile.TemporaryDirectory() as t:
            git, base = self.make_repo(t)
            git("merge", "--no-ff", "-m", "merge", "side")
            lines = self.scan(t, base, lambda: list(common.history_added_lines(base)))
            self.assertEqual(sorted(lines), [("f.txt", "main"), ("g.txt", "side")])


class Scratch:
    def __init__(self, t):
        self.t = pathlib.Path(t)
        self.git("init", "-q", "-b", "main")
        self.write("README.md", "x\n")
        self.commit("base")
        self.base = self.git("rev-parse", "HEAD").stdout.strip()

    def git(self, *a):
        return subprocess.run(["git", "-c", "commit.gpgsign=false", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *a],
                              cwd=self.t, capture_output=True, text=True)

    def write(self, name, text="data\n", size=None):
        p = self.t / name
        p.parent.mkdir(parents=True, exist_ok=True)
        if size:
            p.write_bytes((b"0123456789abcdef" * (size // 16 + 1))[:size])
        else:
            p.write_text(text)

    def commit(self, msg):
        self.git("add", "-A")
        self.git("commit", "-qm", msg)

    def scan(self, base=None):
        old = common.ROOT
        common.ROOT = self.t
        try:
            return check_secrets.run(base or self.base)
        finally:
            common.ROOT = old

    def staged(self):
        return cli(self.t, "staged")


class PathRules(unittest.TestCase):
    BAD = [".env", "app/.env", ".env.production", "a/b/server.pem", "k.P12", "k.pfx", "tls.key", "store.keystore", "id_rsa",
           "ssh/id_rsa.bak", "id_ed25519", "credentials.json", "gcp/credentials-prod.json"]
    GOOD = [".env.example", "x/.env.sample", ".env.template", "id_rsa.pub", "id_ed25519.pub", "keys.md", "monkey.py",
            "environment.py", "credentials.md", "my_credentials_helper.py", "pem.txt"]

    MORE_BAD = ["credentials", "home/.aws/credentials", "secrets.json", "x/token.json", ".netrc", ".npmrc", "a/.pgpass", "AuthKey_AB12.p8",
                "db.kdbx", "release.jks", "putty.ppk", "backup.gpg", "service-account.json", "gcp/service-account-prod.json",
                "prod.env", "config/staging.ENV", "deploy_id_rsa", "x/my-id_ed25519", "key_id_ecdsa"]
    MORE_GOOD = ["credentials.md", "secrets.md", "token.js", "npmrc.md", "service.json", "environment.py", "gpg.txt", "rsa_notes.md"]

    def test_more_credential_names(self):
        for name in self.MORE_BAD:
            self.assertTrue(check_secrets.sensitive_name(name), name)
        for name in self.MORE_GOOD:
            self.assertFalse(check_secrets.sensitive_name(name), name)

    def test_allowlist_star_does_not_cross_a_slash(self):
        self.assertTrue(check_secrets.allowed("web/a.pem", ["web/*.pem"]))
        self.assertFalse(check_secrets.allowed("web/deep/a.pem", ["web/*.pem"]))
        self.assertFalse(check_secrets.allowed("evil/web/a.pem", ["web/*.pem"]))
        self.assertFalse(check_secrets.allowed("a/b/c.pem", ["*.pem"]))
        self.assertTrue(check_secrets.allowed("c.pem", ["*.pem"]))
        self.assertTrue(check_secrets.allowed("web/deep/a.pem", ["web/**/*.pem"]))
        self.assertTrue(check_secrets.allowed("web/a.pem", ["web/?.pem"]))
        self.assertFalse(check_secrets.allowed("web/ab.pem", ["web/?.pem"]))

    def test_glob_character_classes(self):
        a = check_secrets.allowed
        self.assertTrue(a("a5.txt", ["a[0-9].txt"]))
        self.assertFalse(a("ab.txt", ["a[0-9].txt"]))
        self.assertFalse(a("aa.txt", ["a[0-9].txt"]))  # the class holds the digits only, not the characters before it
        self.assertFalse(a("a[.txt", ["a[0-9].txt"]))
        self.assertTrue(a("ab.txt", ["a[!0-9].txt"]))
        self.assertFalse(a("a5.txt", ["a[!0-9].txt"]))
        self.assertTrue(a("xb", ["x[abc]"]))
        self.assertFalse(a("xd", ["x[abc]"]))

    def test_a_negated_class_does_not_cross_a_slash(self):
        a = check_secrets.allowed
        self.assertFalse(a("x/", ["x[!abc]"]))
        self.assertFalse(a("a/b.pem", ["a[!x]b.pem"]))
        self.assertTrue(a("aqb.pem", ["a[!x]b.pem"]))

    def test_a_bracket_without_a_closing_one_and_a_stray_closing_one_are_literal(self):
        a = check_secrets.allowed
        self.assertTrue(a("a[b", ["a[b"]))
        self.assertFalse(a("ab", ["a[b"]))
        self.assertTrue(a("[]x", ["[]x"]))
        self.assertTrue(a("ab]c", ["ab]c"]))
        self.assertFalse(a("abc", ["ab]c"]))
        self.assertTrue(a("a]bz", ["a]b?"]))
        self.assertFalse(a("a]b/", ["a]b?"]))

    def test_double_star_forms(self):
        a = check_secrets.allowed
        self.assertTrue(a("x", ["**/x"]))
        self.assertTrue(a("a/b/x", ["**/x"]))
        self.assertFalse(a("ax", ["**/x"]))
        self.assertFalse(a("a/bx", ["**/x"]))
        self.assertTrue(a("a/b/c", ["a/**"]))
        self.assertTrue(a("a/bx", ["**x"]))
        self.assertTrue(a("x", ["**x"]))
        self.assertFalse(a("ay", ["**x"]))  # ** consumes itself only, the x after it still has to be there
        self.assertTrue(a("a/x/b.pem", ["a/**/b.pem"]))
        self.assertTrue(a("a/b.pem", ["a/**/b.pem"]))

    def test_an_allowlist_line_of_only_wildcards_is_refused(self):
        for pat in ("*", "**", "*/*", "**/*"):
            globs, problems = check_secrets.parse_allow(pat + "  # everything\n")
            self.assertEqual(globs, [], pat)
            self.assertTrue(problems, pat)

    def test_a_malformed_bracket_glob_is_reported_and_never_crashes(self):
        for pat in ("[/]x", "[!/]x", "[z-a]x", "[!]x]"):
            globs, problems = check_secrets.parse_allow(pat + "  # odd\n")
            self.assertEqual(globs, [], pat)
            self.assertTrue(problems, pat)
            self.assertFalse(check_secrets.allowed("x", globs), pat)

    def test_names(self):
        for name in self.BAD:
            self.assertTrue(check_secrets.sensitive_name(name), name)
        for name in self.GOOD:
            self.assertFalse(check_secrets.sensitive_name(name), name)

    def test_each_bad_name_is_found_in_pushed_history(self):
        with tempfile.TemporaryDirectory() as t:
            s = Scratch(t)
            for name in self.BAD:
                s.write(name)
            s.commit("add")
            self.assertEqual(sorted(s.scan()), sorted(f"{n}: sensitive file name (not in {ALLOW})" for n in self.BAD))

    def test_good_names_pass(self):
        with tempfile.TemporaryDirectory() as t:
            s = Scratch(t)
            for name in self.GOOD:
                s.write(name)
            s.commit("add")
            self.assertEqual(s.scan(), [])

    def test_a_file_added_and_removed_in_the_range_is_still_found(self):
        with tempfile.TemporaryDirectory() as t:
            s = Scratch(t)
            s.write("tls.key"); s.commit("add")
            (s.t / "tls.key").unlink(); s.commit("remove")
            self.assertEqual(len(s.scan()), 1)

    def test_a_file_in_the_base_commit_is_not_judged(self):
        with tempfile.TemporaryDirectory() as t:
            s = Scratch(t)
            s.write("old.pem"); s.commit("old")
            s.base = s.git("rev-parse", "HEAD").stdout.strip()
            s.write("README.md", "y\n"); s.commit("later")
            self.assertEqual(s.scan(), [])


class Allowlist(unittest.TestCase):
    def test_entry_in_the_base_version_allows_the_file(self):
        with tempfile.TemporaryDirectory() as t:
            s = Scratch(t)
            s.write(ALLOW, "# comment\nweb/public/*.pem  # public test certificate\n"); s.commit("allow")
            s.base = s.git("rev-parse", "HEAD").stdout.strip()
            s.write("web/public/a.pem"); s.commit("add")
            self.assertEqual(s.scan(), [])

    def test_a_commit_cannot_allow_its_own_file(self):
        with tempfile.TemporaryDirectory() as t:
            s = Scratch(t)
            s.write(ALLOW, "tls.key  # because\n")
            s.write("tls.key")
            s.commit("add both")
            self.assertEqual(len(s.scan()), 1)

    def test_entry_without_a_reason_is_a_problem_and_allows_nothing(self):
        with tempfile.TemporaryDirectory() as t:
            s = Scratch(t)
            s.write(ALLOW, "tls.key\n"); s.commit("allow")
            s.base = s.git("rev-parse", "HEAD").stdout.strip()
            s.write("tls.key"); s.commit("add")
            out = s.scan()
            self.assertEqual(len(out), 2, out)
            self.assertTrue(any("without a reason" in p for p in out), out)

    def test_a_blank_or_missing_reason_is_refused_in_parse_allow(self):
        for text in ("a.txt  #   \n", "a.txt  #\n", "a.txt #\t\n", "a.txt\n", "  a.txt   \n"):
            globs, problems = check_secrets.parse_allow(text)
            self.assertEqual(globs, [], text)
            self.assertEqual(len(problems), 1, (text, problems))
            self.assertIn("without a reason", problems[0], text)
        globs, problems = check_secrets.parse_allow("a.txt  # why\n# comment\n\n")
        self.assertEqual((globs, problems), (["a.txt"], []))

    def test_other_files_are_still_judged(self):
        with tempfile.TemporaryDirectory() as t:
            s = Scratch(t)
            s.write(ALLOW, "a.pem  # fine\n"); s.commit("allow")
            s.base = s.git("rev-parse", "HEAD").stdout.strip()
            s.write("a.pem"); s.write("b.pem"); s.commit("add")
            self.assertEqual([p.split(":")[0] for p in s.scan()], ["b.pem"])


class LargeFiles(unittest.TestCase):
    LIMIT = 5 * 1024 * 1024

    def test_big_blob_is_found_and_small_is_not(self):
        with tempfile.TemporaryDirectory() as t:
            s = Scratch(t)
            s.write("small.bin", size=self.LIMIT)
            s.write("big.bin", size=self.LIMIT + 1)
            s.commit("add")
            out = s.scan()
            self.assertEqual(len(out), 1, out)
            self.assertIn("big.bin: 5242881 bytes is over the 5 MB limit", out[0])

    def test_allowlist_covers_a_big_file(self):
        with tempfile.TemporaryDirectory() as t:
            s = Scratch(t)
            s.write(ALLOW, "assets/*.bin  # data set\n"); s.commit("allow")
            s.base = s.git("rev-parse", "HEAD").stdout.strip()
            s.write("assets/big.bin", size=self.LIMIT + 1); s.commit("add")
            self.assertEqual(s.scan(), [])


class PathMerges(unittest.TestCase):
    def test_evil_merge_adds_a_key_file(self):
        with tempfile.TemporaryDirectory() as t:
            s = Scratch(t)
            s.git("checkout", "-qb", "side"); s.write("g.txt", "side\n"); s.commit("side")
            s.git("checkout", "-q", "main"); s.write("f.txt", "main\n"); s.commit("main")
            s.git("merge", "--no-ff", "--no-commit", "side")
            s.write("deploy.pem"); s.commit("merge")
            self.assertEqual([p.split(":")[0] for p in s.scan()], ["deploy.pem"])

    def test_clean_merge_does_not_report_the_side_branch_twice(self):
        with tempfile.TemporaryDirectory() as t:
            s = Scratch(t)
            s.git("checkout", "-qb", "side"); s.write("side.key"); s.commit("side")
            s.git("checkout", "-q", "main"); s.write("f.txt", "main\n"); s.commit("main")
            s.git("merge", "--no-ff", "-m", "merge", "side")
            self.assertEqual(len(s.scan()), 1)


class GitFailure(unittest.TestCase):
    def test_staged_paths_outside_a_repo_raises_instead_of_returning_clean(self):
        with tempfile.TemporaryDirectory() as t:
            old = common.ROOT
            common.ROOT = pathlib.Path(t)
            self.addCleanup(setattr, common, "ROOT", old)
            env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
            with unittest.mock.patch.dict(os.environ, env, clear=True):
                os.environ["GIT_CEILING_DIRECTORIES"] = str(pathlib.Path(t).parent)
                with self.assertRaises(subprocess.CalledProcessError):
                    check_secrets.staged_paths()

    def test_blob_sizes_raises_when_git_fails_and_skips_a_missing_object(self):
        with tempfile.TemporaryDirectory() as t:
            s = Scratch(t)
            real = s.git("rev-parse", "HEAD:README.md").stdout.strip()
            missing = "0123456789abcdef0123456789abcdef01234567"
            self.assertEqual(check_secrets.blob_sizes([real, missing], s.t), {real: 2})
            self.assertEqual(check_secrets.blob_sizes([], s.t), {})
        with tempfile.TemporaryDirectory() as t:
            env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
            env["GIT_CEILING_DIRECTORIES"] = str(pathlib.Path(t).parent)
            with unittest.mock.patch.dict(os.environ, env, clear=True):
                with self.assertRaises(subprocess.CalledProcessError):
                    check_secrets.blob_sizes(["0123456789abcdef0123456789abcdef01234567"], t)


class StagedPaths(unittest.TestCase):
    def test_staged_key_file_blocks(self):
        with tempfile.TemporaryDirectory() as t:
            s = Scratch(t)
            s.write("x/id_ed25519"); s.git("add", "-A")
            r = s.staged()
            self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
            self.assertIn("x/id_ed25519: sensitive file name", r.stdout)

    def test_staged_big_file_blocks(self):
        with tempfile.TemporaryDirectory() as t:
            s = Scratch(t)
            s.write("big.bin", size=5 * 1024 * 1024 + 1); s.git("add", "-A")
            r = s.staged()
            self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
            self.assertIn("big.bin", r.stdout)

    def test_staged_example_file_passes_and_allowlist_is_read_from_head(self):
        with tempfile.TemporaryDirectory() as t:
            s = Scratch(t)
            s.write(".env.example"); s.write("a.pem"); s.write(ALLOW, "a.pem  # public\n")
            s.git("add", "-A")
            self.assertEqual(s.staged().returncode, 1)  # the entry is staged, not yet committed
            s.git("reset", "-q", "a.pem")
            self.assertEqual(s.staged().returncode, 0)
            s.commit("allow")
            s.write("a.pem"); s.git("add", "-A")
            self.assertEqual(s.staged().returncode, 0)



def scan(repo, base):
    old = common.ROOT
    common.ROOT = pathlib.Path(repo)
    try:
        return check_secrets.run(base)
    finally:
        common.ROOT = old


class ScratchRepo(unittest.TestCase):
    """A real scratch git repo with the real hooks installed."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = pathlib.Path(self.tmp.name) / "repo"
        sh(self.tmp.name, "git", "init", "-q", "-b", "main", str(self.repo))
        for k, v in (("user.name", "t"), ("user.email", "t@example.invalid"), ("commit.gpgsign", "false")):
            sh(self.repo, "git", "config", k, v)
        self.assertEqual(sh(self.repo, "sh", str(hermetic.ROOT / "hooks" / "install.sh")).returncode, 0)
        gitsafe.assert_sandbox(self.repo)
        (self.repo / "README.txt").write_text("hello\n")
        sh(self.repo, "git", "add", "-A")
        self.assertEqual(sh(self.repo, "git", "commit", "-qm", "base").returncode, 0)
        self.base = sh(self.repo, "git", "rev-parse", "HEAD").stdout.strip()

    def tearDown(self):
        self.tmp.cleanup()

    def commit(self):
        sh(self.repo, "git", "add", "-A")
        return sh(self.repo, "git", "commit", "-qm", "next")

    def history(self):
        # a commit made with the hook bypassed, then the push-time scan over base..HEAD
        sh(self.repo, "git", "add", "-A")
        sh(self.repo, "git", "commit", "-qm", "next", "--no-verify")
        return "\n".join(scan(self.repo, self.base))


class HookSeesHiddenContent(ScratchRepo):
    def test_utf16_file_is_blocked_by_the_hook(self):
        (self.repo / "notes.txt").write_bytes(("token = " + SECRET + "\n").encode("utf-16"))
        r = self.commit()
        self.assertNotEqual(r.returncode, 0, r.stderr)
        self.assertIn("github token", r.stdout + r.stderr)

    def test_utf16_be_without_bom_is_blocked_by_the_hook(self):
        (self.repo / "notes.txt").write_bytes(("x\ntoken = " + SECRET + "\n").encode("utf-16-be"))
        self.assertNotEqual(self.commit().returncode, 0)

    def test_diff_attribute_file_is_blocked_by_the_hook(self):
        (self.repo / ".gitattributes").write_text("*.lock -diff\n")
        (self.repo / "deps.lock").write_text("token = " + SECRET + "\n")
        r = self.commit()
        self.assertNotEqual(r.returncode, 0, r.stderr)
        self.assertIn("github token", r.stdout + r.stderr)

    def test_binary_attribute_file_is_blocked_by_the_hook(self):
        (self.repo / ".gitattributes").write_text("*.dat binary\n")
        (self.repo / "x.dat").write_text("token = " + SECRET + "\n")
        self.assertNotEqual(self.commit().returncode, 0)

    def test_clean_utf16_and_diff_files_pass(self):
        (self.repo / ".gitattributes").write_text("*.lock -diff\n")
        (self.repo / "deps.lock").write_text("nothing here\n")
        (self.repo / "notes.txt").write_bytes("just notes\n".encode("utf-16"))
        r = self.commit()
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_push_time_history_scan_sees_utf16_and_diff_files(self):
        (self.repo / ".gitattributes").write_text("*.lock -diff\n")
        (self.repo / "deps.lock").write_text("token = " + SECRET + "\n")
        (self.repo / "notes.txt").write_bytes(("token = " + SECRET + "\n").encode("utf-16"))
        out = self.history()
        self.assertIn("deps.lock: possible github token", out)
        self.assertIn("notes.txt: possible github token", out)

    def test_big_random_binary_is_fast_and_not_flagged(self):
        blob = random.Random(7).randbytes(5 * 1024 * 1024)
        (self.repo / "blob.bin").write_bytes(blob)
        (self.repo / "zeros.bin").write_bytes(b"\0" * (2 * 1024 * 1024))
        (self.repo / "mod.pyc").write_bytes(b"\xa7\x0d\x0d\x0a" + b"\0" * 20 + bytes(range(256)) * 40)
        t = time.monotonic()
        r = self.commit()
        took = time.monotonic() - t
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertLess(took, 15, "hook took %.1fs on a 5 MB binary" % took)
        t = time.monotonic()
        self.assertEqual(self.history().strip(), "")
        self.assertLess(time.monotonic() - t, 15)


class FullTreeEncodings(ScratchRepo):
    def test_full_tree_finds_secrets_in_utf16_and_latin1_files(self):
        (self.repo / "a.txt").write_bytes(("token = " + SECRET + "\n").encode("utf-16"))
        (self.repo / "b.txt").write_bytes(("caf\xe9 token = " + SECRET + "\n").encode("latin-1"))
        (self.repo / "c.txt").write_bytes(("token = " + SECRET + "\n").encode("utf-16-le"))
        sh(self.repo, "git", "add", "-A")
        found = check_secrets.run_tree(self.repo)
        for n in ("a.txt", "b.txt", "c.txt"):
            self.assertIn("%s: possible github token" % n, found)

    def test_full_tree_skips_genuine_binary_and_caps_size(self):
        (self.repo / "zeros.bin").write_bytes(b"\0" * 5000 + SECRET.encode())
        sh(self.repo, "git", "add", "-A")
        self.assertEqual(check_secrets.run_tree(self.repo), [])

    def test_full_tree_finds_secret_beyond_one_megabyte(self):
        (self.repo / "big.txt").write_bytes(b"a\n" * 600_000 + SECRET.encode())
        (self.repo / "wide.txt").write_bytes((("x" * 99 + "\n") * 12_000 + "token = " + SECRET + "\n").encode("utf-16"))
        sh(self.repo, "git", "add", "-A")
        found = check_secrets.run_tree(self.repo)
        self.assertIn("big.txt: possible github token", found)
        self.assertIn("wide.txt: possible github token", found)

    def test_diff_scan_finds_secret_beyond_one_megabyte(self):
        (self.repo / "big.txt").write_bytes(b"a\n" * 600_000 + SECRET.encode() + b"\n")
        self.assertIn("big.txt: possible github token", self.history())





if __name__ == "__main__":
    unittest.main()
