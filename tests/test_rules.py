"""rules.toml stays honest: every file it names exists and every check is enforcing some rule."""
import hermetic  # noqa: F401  (first: paths and git isolation)
import tomllib, unittest
from hermetic import ROOT
from agent_gate.checks import ALL


class Rules(unittest.TestCase):
    def setUp(self):
        self.rules = tomllib.loads((ROOT / "rules.toml").read_text())["rule"]

    def test_every_rule_has_the_fields_and_a_unique_id(self):
        ids = [r["id"] for r in self.rules]
        self.assertEqual(len(ids), len(set(ids)))
        for r in self.rules:
            self.assertTrue(r["rule"] and r["limits"] and r["enforced_by"], r["id"])

    def test_every_enforcing_file_exists(self):
        for r in self.rules:
            for path in r["enforced_by"]:
                self.assertTrue((ROOT / path).is_file(), (r["id"], path))

    def test_every_check_enforces_a_rule(self):
        named = {p for r in self.rules for p in r["enforced_by"]}
        for mod in ALL.values():
            self.assertIn("agent_gate/checks/" + mod.__name__.rsplit(".", 1)[1] + ".py", named)


if __name__ == "__main__":
    unittest.main()
