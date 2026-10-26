"""The one-language check: added lines, file names, the exempt paths and the old-lines-only files."""
import hermetic  # noqa: F401  (first: paths and git isolation)
import unittest
from unittest import mock
from agent_gate.checks import check_language

CYR = "".join(chr(c) for c in (0x43f, 0x440, 0x438, 0x432, 0x435, 0x442))  # a Cyrillic word, built at runtime
CFG = {"language": {"forbid": "cyrillic", "exempt_paths": ["docs/ru/", "LEGACY.md"], "old_lines_only": ["CLAUDE.md"]}}
P = check_language.Policy(CFG)


def lines(pairs, old=None):
    return check_language.check_lines(P, pairs, old)


class Language(unittest.TestCase):
    def test_without_a_forbid_value_the_check_is_off(self):
        off = check_language.Policy({})
        self.assertFalse(off.on)
        self.assertEqual(check_language.check_lines(off, [("a.py", CYR)]), [])

    def test_exact_path_exemption_only(self):
        self.assertEqual(lines([("LEGACY.md", CYR)]), [])
        self.assertTrue(lines([("LEGACY.md.bak", CYR)]))
        self.assertTrue(lines([("x/LEGACY.md", CYR)]))

    def test_directory_exemption_needs_the_slash(self):
        self.assertEqual(lines([("docs/ru/a.md", CYR)]), [])
        self.assertTrue(lines([("docs/rus/a.md", CYR)]))

    def test_old_lines_only_file_keeps_only_its_old_lines(self):
        old = {"CLAUDE.md": {CYR}}
        self.assertEqual(lines([("CLAUDE.md", CYR)], old), [])
        self.assertTrue(lines([("CLAUDE.md", CYR + "!")], old))
        self.assertTrue(lines([("CLAUDE.md", CYR)], {}))

    def test_rejects_the_script_in_new_code_and_allows_english(self):
        self.assertTrue(lines([("src/x.py", "# " + CYR)]))
        self.assertEqual(lines([("src/x.py", "# hello")]), [])

    def test_file_name_with_english_content_is_caught_once(self):
        self.assertTrue(lines([("src/" + CYR + ".py", "# hello")]))
        two = [("src/" + CYR + ".py", "a"), ("src/" + CYR + ".py", "b")]
        self.assertEqual(len(lines(two)), 1)
        self.assertEqual(lines([("docs/ru/" + CYR + ".py", "# hello")]), [])
        self.assertTrue(check_language.check_paths(P, ["src/" + CYR + ".md"]))

    def test_run_scans_added_paths_even_when_the_file_is_empty(self):
        with mock.patch.object(check_language.common, "added_lines", return_value=[]), \
                mock.patch.object(check_language.common, "added_paths", return_value=["src/" + CYR + ".txt"]), \
                mock.patch.object(check_language, "old_lines", return_value={}):
            self.assertTrue(check_language.run("HEAD~1", CFG))

    def test_wider_cyrillic_ranges_are_caught(self):
        for cp in (0x500, 0x52F, 0x2DE0, 0x2DFF, 0xA640, 0xA69F, 0x4FF, 0x1C80):
            self.assertTrue(lines([("src/x.py", "# " + chr(cp))]), hex(cp))
        for cp in (0x3FF, 0x530, 0x2DDF, 0xA63F, 0xA6A0):
            self.assertEqual(lines([("src/x.py", "# " + chr(cp))]), [], hex(cp))

    def test_other_scripts_and_custom_ranges(self):
        greek = check_language.Policy({"language": {"forbid": "greek"}})
        self.assertTrue(check_language.check_lines(greek, [("a", chr(0x3b1))]))
        self.assertEqual(check_language.check_lines(greek, [("a", CYR)]), [])
        custom = check_language.Policy({"language": {"forbid": [["0x41", "0x43"]]}})
        self.assertTrue(check_language.check_lines(custom, [("a", "B")]))
        self.assertEqual(check_language.check_lines(custom, [("a", "d")]), [])
        with self.assertRaises(ValueError):
            check_language.Policy({"language": {"forbid": "klingon"}})


if __name__ == "__main__":
    unittest.main()
