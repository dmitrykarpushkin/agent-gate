"""agent-gate.toml: parsing, the shipped examples, and the bundled model lifecycle file."""
import hermetic  # noqa: F401  (first: paths and git isolation)
import datetime, json, unittest
from hermetic import ROOT
from agent_gate import config
from agent_gate.checks import check_pinned_models


class Config(unittest.TestCase):
    def test_the_example_config_parses_and_enables_every_check(self):
        cfg = config.from_tree(ROOT / "examples")
        self.assertEqual(config.enabled(cfg), list(config.ALL_CHECKS))
        self.assertEqual(config.get(cfg, "push.branches"), ["main"])

    def test_this_repos_own_config_parses(self):
        cfg = config.from_tree(ROOT)
        self.assertIn("secrets", config.enabled(cfg))

    def test_errors_are_loud(self):
        with self.assertRaises(config.ConfigError):
            config.parse("[a\n", "x")
        with self.assertRaises(config.ConfigError):
            config.enabled({"checks": {"enabled": ["nope"]}})
        with self.assertRaises(config.ConfigError):
            config.section({"secrets": 3}, "secrets")

    def test_get_walks_dotted_names(self):
        self.assertEqual(config.get({"a": {"b": 1}}, "a.b"), 1)
        self.assertEqual(config.get({"a": {"b": 1}}, "a.c", "d"), "d")
        self.assertEqual(config.get({"a": 1}, "a.b"), None)


class BundledLifecycle(unittest.TestCase):
    def test_the_bundled_file_loads_and_names_its_source(self):
        data = json.loads(check_pinned_models.BUNDLED.read_text())
        self.assertTrue(data["source"].startswith("https://"))
        for info in data["models"].values():
            self.assertIn(info["status"], ("active", "deprecated", "retired"))
            if info["retires"]:
                datetime.date.fromisoformat(info["retires"])


if __name__ == "__main__":
    unittest.main()
