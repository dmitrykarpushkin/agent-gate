"""The core-sync check: every target file carries the core text between the markers, unchanged."""
import hermetic  # noqa: F401  (first: paths and git isolation)
import pathlib, tempfile, unittest
from agent_gate.checks import check_core_sync

CORE = "# Core\n\n- Done means every criterion passed with attached output.\n- Irreversible steps wait for a person's yes.\n"
CFG = {"core_sync": {"source": "docs/CORE.md", "targets": ["CLAUDE.md", "AGENTS.md"]}}


class CoreSync(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)
        (self.root / "docs").mkdir()
        (self.root / "docs" / "CORE.md").write_text(CORE)
        for t in ("CLAUDE.md", "AGENTS.md"):
            (self.root / t).write_text("Intro for this agent.\n\n" + check_core_sync.wrap(CORE) + "\n\nMore.\n")

    def run_check(self, cfg=CFG):
        return check_core_sync.run(root=self.root, cfg=cfg)

    def test_in_sync(self):
        self.assertEqual(self.run_check(), [])

    def test_trailing_spaces_and_crlf_do_not_count(self):
        (self.root / "AGENTS.md").write_text(check_core_sync.wrap(CORE).replace("\n", "  \r\n"))
        self.assertEqual(self.run_check(), [])

    def test_a_changed_core_block_is_reported(self):
        p = self.root / "AGENTS.md"
        p.write_text(p.read_text().replace("person's yes", "person's yes, or not"))
        problems = self.run_check()
        self.assertEqual(len(problems), 1)
        self.assertIn("AGENTS.md carries a core block that differs", problems[0])

    def test_a_changed_source_makes_every_target_stale(self):
        (self.root / "docs" / "CORE.md").write_text(CORE + "- New rule.\n")
        self.assertEqual(len(self.run_check()), 2)

    def test_a_missing_block_and_a_missing_file_are_reported(self):
        (self.root / "CLAUDE.md").write_text("no markers here\n")
        (self.root / "AGENTS.md").unlink()
        problems = self.run_check()
        self.assertTrue(any("CLAUDE.md has no complete core block" in p for p in problems), problems)
        self.assertTrue(any("AGENTS.md cannot be read" in p for p in problems), problems)

    def test_a_second_core_block_is_reported(self):
        p = self.root / "CLAUDE.md"
        p.write_text(p.read_text() + "\n" + check_core_sync.wrap(CORE) + "\n")
        self.assertTrue(any("more than one" in x for x in self.run_check()))

    def test_custom_markers(self):
        cfg = {"core_sync": dict(CFG["core_sync"], start="# >>> core", end="# <<< core")}
        for t in ("CLAUDE.md", "AGENTS.md"):
            (self.root / t).write_text("# >>> core\n" + CORE + "\n# <<< core\n")
        self.assertEqual(self.run_check(cfg), [])

    def test_off_without_a_source_and_loud_without_targets_or_source_file(self):
        self.assertEqual(self.run_check({}), [])
        self.assertTrue(self.run_check({"core_sync": {"source": "docs/CORE.md"}}))
        self.assertTrue(self.run_check({"core_sync": {"source": "docs/NONE.md", "targets": ["CLAUDE.md"]}}))


if __name__ == "__main__":
    unittest.main()
