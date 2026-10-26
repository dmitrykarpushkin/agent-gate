"""The required-text check: listed documents keep their load-bearing phrases."""
import hermetic  # noqa: F401  (first: paths and git isolation)
import pathlib, tempfile, unittest
from agent_gate.checks import check_required_text

PARTS = ["## What failure means here", "## Report format", "Important", "Nit", "path:line"]
CFG = {"required_text": {"docs/REVIEW.md": PARTS, "roles/tester.md": ["docs/REVIEW.md"]}}


class RequiredText(unittest.TestCase):
    def run_in(self, edit=None, drop=None):
        with tempfile.TemporaryDirectory() as t:
            root = pathlib.Path(t)
            (root / "docs").mkdir()
            (root / "roles").mkdir()
            (root / "docs" / "REVIEW.md").write_text("\n".join(PARTS))
            (root / "roles" / "tester.md").write_text("Report in the format of docs/REVIEW.md.")
            if edit:
                path, old, new = edit
                p = root / path
                p.write_text(p.read_text().replace(old, new))
            if drop:
                (root / drop).unlink()
            return check_required_text.run(root=root, cfg=CFG)

    def test_valid_tree_is_clean(self):
        self.assertEqual(self.run_in(), [])

    def test_missing_file(self):
        self.assertEqual(self.run_in(drop="docs/REVIEW.md"), ["docs/REVIEW.md is missing"])

    def test_missing_heading_is_named(self):
        self.assertEqual(self.run_in(edit=("docs/REVIEW.md", "## Report format", "x")), ["docs/REVIEW.md lacks '## Report format'"])

    def test_missing_reference_is_named(self):
        self.assertEqual(self.run_in(edit=("roles/tester.md", "docs/REVIEW.md", "the guide")), ["roles/tester.md lacks 'docs/REVIEW.md'"])

    def test_empty_config_is_off(self):
        self.assertEqual(check_required_text.run(root=".", cfg={}), [])


if __name__ == "__main__":
    unittest.main()
