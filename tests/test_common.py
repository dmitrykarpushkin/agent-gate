import hermetic  # noqa: F401  (first: paths and git isolation)
import unittest
from agent_gate import common


class UsableText(unittest.TestCase):
    def test_nul_ratio_exactly_at_the_limit_is_not_yet_binary(self):
        text = "\0" * 3 + "\x01" * 7  # 3 of 10 is exactly NUL_LIMIT; the rest is not printable, so only the limit saves it
        self.assertEqual(common.NUL_LIMIT, 0.30)
        self.assertEqual(common.usable_text(text), "\x01" * 7)
        self.assertIsNone(common.usable_text("\0" * 4 + "\x01" * 6))  # just above the limit and not printable

    def test_printable_share_exactly_ninety_percent_still_reads_as_text(self):
        text = "\0" * 10 + "a" * 9 + "\x01"  # 50% NULs, 9 of 10 remaining characters printable
        self.assertEqual(common.usable_text(text), "a" * 9 + "\x01")
        self.assertIsNone(common.usable_text("\0" * 10 + "a" * 8 + "\x01\x02"))  # 8 of 10

    def test_nul_ratio_exactly_fifty_five_percent_still_reads_as_text(self):
        self.assertEqual(common.usable_text("\0" * 11 + "a" * 9), "a" * 9)
        self.assertIsNone(common.usable_text("\0" * 12 + "a" * 8))

    def test_text_without_nul_is_returned_as_is(self):
        self.assertEqual(common.usable_text("plain\n"), "plain\n")


class DecodeBytes(unittest.TestCase):
    def test_utf8_bom_is_stripped(self):
        self.assertEqual(common.decode_bytes(b"\xef\xbb\xbfhello"), "hello")
        self.assertEqual(common.decode_bytes(b"hello"), "hello")

    def test_utf16_with_a_bom_either_way(self):
        self.assertEqual(common.decode_bytes("key = abc".encode("utf-16")), "key = abc")
        self.assertEqual(common.decode_bytes(b"\xfe\xff" + "key = abc".encode("utf-16-be")), "key = abc")

    def test_utf16_without_bom_both_byte_orders(self):
        self.assertEqual(common.decode_bytes("token = abc".encode("utf-16-le")), "token = abc")
        self.assertEqual(common.decode_bytes("token = abc".encode("utf-16-be")), "token = abc")

    def test_null_share_of_one_byte_parity_exactly_eighty_percent_is_not_taken_for_utf16(self):
        data = "abcdefgh".encode("utf-16-le") + "\u4e2d\u4e2d".encode("utf-16-le")  # 8 of 10 high bytes are NUL
        self.assertEqual(common.decode_bytes(data), data.decode("utf-8").replace("\0", ""))
        more = "abcdefghi".encode("utf-16-le") + "\u4e2d".encode("utf-16-le")  # 9 of 10: read as UTF-16
        self.assertEqual(common.decode_bytes(more), "abcdefghi\u4e2d")

    def test_a_big_text_file_is_decoded_whole_and_a_big_binary_one_is_skipped(self):
        n = common.SAMPLE_BYTES
        text = b"a" * n + b" tail-secret"
        self.assertTrue(common.decode_bytes(text).endswith("tail-secret"))
        self.assertEqual(common.decode_bytes(b"a" * n), "a" * n)
        self.assertIsNone(common.decode_bytes(b"\0" * n + b"abc"))


class ParseAdded(unittest.TestCase):
    def test_a_diff_without_a_header_line_does_not_start_inside_a_hunk(self):
        diff = "--- a/f\n+++ b/f\n@@ -0,0 +1 @@\n+line\n"
        self.assertEqual(list(common.parse_added(diff)), [("f", "line")])

    def test_a_plus_plus_line_inside_a_hunk_is_content(self):
        diff = "diff --git a/f b/f\n--- a/f\n+++ b/f\n@@ -0,0 +2 @@\n+++ b/g\n+x\n"
        self.assertEqual(list(common.parse_added(diff)), [("f", "++ b/g"), ("f", "x")])


class Helpers(unittest.TestCase):
    def test_usable_text(self):
        self.assertEqual(common.usable_text("a\0b\0"), "ab")
        self.assertIsNone(common.usable_text("\0" * 100 + "ab"))
        self.assertIsNone(common.usable_text("\0\x01\0\x02\0\x03\0\x04"))

    def test_header_is_not_content_and_paths_follow_files(self):
        diff = ("diff --git a/a b/a\n--- a/a\n+++ b/a\n@@ -1 +1 @@\n-old\n+new a\n"
                "diff --git a/b b/b\n--- a/b\n+++ b/b\n@@ -0,0 +1 @@\n+new b\n")
        self.assertEqual(list(common.parse_added(diff)), [("a", "new a"), ("b", "new b")])

    def test_added_line_starting_with_plus_plus_is_seen(self):
        diff = ("diff --git a/x.txt b/x.txt\n--- /dev/null\n+++ b/x.txt\n@@ -0,0 +1,2 @@\n"
                "+++ starts with two pluses\n+plain\n")
        self.assertEqual(list(common.parse_added(diff)), [("x.txt", "++ starts with two pluses"), ("x.txt", "plain")])

    def test_quoted_header_does_not_inherit_the_previous_path(self):
        diff = ("diff --git a/tests/a.py b/tests/a.py\n+++ b/tests/a.py\n@@ -0,0 +1 @@\n+x\n"
                'diff --git "a/src/\\303\\251.md" "b/src/\\303\\251.md"\n+++ "b/src/\\303\\251.md"\n@@ -0,0 +1 @@\n+y\n')
        paths = [p for p, _ in common.parse_added(diff)]
        self.assertEqual(paths[0], "tests/a.py")
        self.assertNotEqual(paths[1], "tests/a.py")


if __name__ == "__main__":
    unittest.main()
