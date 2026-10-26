"""The change-record check: independent verifier, evidence with detail, a person's yes for irreversible kinds."""
import hermetic  # noqa: F401  (first: paths and git isolation)
import pathlib, tempfile, unittest
from agent_gate.checks import check_changes

GOOD = {"status": "verified", "kind": "feature", "author": "a1", "verifier": "b2", "evidence": "run 1",
        "test_author": "t3", "risk": "low", "revert": "git revert the merge"}
OK1 = 'msg-0123456789abcdefghij "yes, do it today"'
OK2 = 'msg-0123456789abcdefghik "go ahead with it"'
OK3 = 'msg-0123456789abcdefghil "approved, spend the money"'


class ChangesTaskTests(unittest.TestCase):
    def test_bare_task_is_reported_and_named_tests_pass(self):
        t = "- [x] parser; tests: test_parser\n- [ ] docs, tests: none, text only\n- [ ] bare task\nplain line\n"
        out = check_changes.check_task_tests("0029-x", t)
        self.assertEqual(len(out), 1)
        self.assertIn("bare task", out[0])

    def test_empty_tests_value_does_not_count(self):
        self.assertEqual(len(check_changes.check_task_tests("0029-x", "- [ ] a, tests:\n")), 1)

    def test_test_author_required_and_differs_from_author(self):
        rec = dict(GOOD)
        del rec["test_author"]
        cr = check_changes.check_record
        self.assertTrue(any("without test_author" in p for p in cr("0029-x", dict(rec))))
        self.assertTrue(any("equals author" in p for p in cr("0029-x", dict(rec, test_author=" A1 "))))
        self.assertTrue(any("placeholder" in p for p in cr("0029-x", dict(rec, test_author="tbd"))))
        self.assertEqual(cr("0029-x", dict(rec, test_author="t3")), [])

    def test_records_before_the_configured_numbers_and_drafts_are_exempt(self):
        rec = {"status": "verified", "kind": "feature", "author": "a1", "verifier": "b2", "evidence": "run 1"}
        later = check_changes.Policy({"changes": {"task_tests_from": 29, "risk_from": 29}})
        self.assertEqual(check_changes.check_record("0028-old", dict(rec), later), [])
        self.assertTrue(check_changes.check_record("0029-new", dict(rec), later))
        self.assertEqual(check_changes.check_record("0029-x", dict(rec, status="proposed")), [])

    def test_run_checks_tasks_file_of_new_changes_only(self):
        with tempfile.TemporaryDirectory() as d:
            for name in ("0028-old", "0029-new"):
                c = pathlib.Path(d, "changes", name)
                c.mkdir(parents=True)
                (c / "proposal.md").write_text("p")
                (c / "tasks.md").write_text("- [ ] bare\n")
                (c / "verification.md").write_text("---\nstatus: proposed\nkind: feature\nauthor: a1\n---\n")
            out = check_changes.run(root=d, cfg={"changes": {"task_tests_from": 29}})
            self.assertEqual(len(out), 1)
            self.assertIn("0029-new: task without tests", out[0])

    def test_risk_and_revert_from_verified(self):
        rec = dict(GOOD)
        del rec["risk"]
        self.assertTrue(any("risk" in p for p in check_changes.check_record("c", rec)))
        self.assertTrue(any("revert" in p for p in check_changes.check_record("c", dict(GOOD, revert="tbd"))))


class Changes(unittest.TestCase):
    def rec(self, **kw):
        base = dict(GOOD)
        base.update(kw)
        return {k: v for k, v in base.items() if v is not None}

    def test_core_branches_each_report_their_own_problem(self):
        cr = check_changes.check_record
        self.assertEqual(cr("c", None), ["c: verification.md has no front matter"])
        self.assertEqual(cr("c", self.rec(status="bogus")), ["c: bad status 'bogus'"])
        self.assertEqual(cr("c", self.rec(status=None)), ["c: bad status None"])
        self.assertEqual(cr("c", self.rec(kind="bogus")), ["c: bad kind 'bogus'"])
        self.assertEqual(cr("c", self.rec(kind=None)), ["c: bad kind None"])
        self.assertEqual(cr("c", self.rec(author=None, verifier="b2")), ["c: missing author"])
        self.assertEqual(cr("c", self.rec(verifier=None)), ["c: verified without verifier"])
        self.assertEqual(cr("c", self.rec(status="applied", verifier=None)), ["c: verified without verifier"])
        self.assertEqual(cr("c", self.rec(status="proposed", verifier=None, evidence=None)), [])
        self.assertEqual(cr("c", self.rec(cost_usd="0")), [])
        self.assertEqual(cr("c", self.rec(status="applied", cost_usd="0")), [])
        self.assertEqual(cr("c", self.rec(status="applied", cost_usd=str(check_changes.SPEND_LIMIT_USD))), [])
        self.assertEqual(len(cr("c", self.rec(status="applied", cost_usd="10.5"))), 1)

    def test_duplicate_front_matter_key_reported(self):
        meta = check_changes.parse_front("---\nstatus: draft\nstatus: applied\nkind: feature\nauthor: a1\n---\n")
        self.assertEqual(meta["status"], "applied")
        self.assertEqual(meta.duplicates, ["status"])
        self.assertTrue(any("duplicate key 'status'" in p for p in check_changes.check_record("c", meta)))
        self.assertEqual(check_changes.parse_front("---\nstatus: draft\n---\n").duplicates, [])

    def test_placeholder_verifier_rejected_from_verified(self):
        for v in ("pending", "none", "-", "tbd", "todo", "n/a", "TBD", " Pending ", "--", "?", "..."):
            for status in ("verified", "applied"):
                problems = check_changes.check_record("c", self.rec(status=status, verifier=v))
                self.assertTrue(any("placeholder" in p for p in problems), (v, status, problems))
        self.assertEqual(check_changes.check_record("c", self.rec(status="proposed", verifier="pending")), [])
        self.assertEqual(check_changes.check_record("c", self.rec(verifier="agent-2")), [])

    def test_valid(self):
        self.assertEqual(check_changes.check_record("c", self.rec()), [])

    def test_self_verification_rejected(self):
        self.assertTrue(check_changes.check_record("c", self.rec(verifier="a1")))

    def test_verifier_compared_after_strip_and_casefold(self):
        for v in ("OPUS-1", " opus-1 ", "Opus-1"):
            problems = check_changes.check_record("c", self.rec(author="opus-1", verifier=v))
            self.assertTrue(any("verifier equals author" in x for x in problems), v)
        self.assertEqual(check_changes.check_record("c", self.rec(author="opus-1", verifier="opus-2")), [])

    def test_evidence_that_is_one_empty_word_is_rejected(self):
        for bad in ("ok", "done", "verified", "yes", "n/a", "-"):
            problems = check_changes.check_record("c", self.rec(evidence=bad))
            self.assertTrue(any("evidence" in x for x in problems), bad)
            self.assertTrue(check_changes.check_record("c", self.rec(status="applied", evidence=bad)), bad)

    def test_evidence_styles_used_by_real_records_pass(self):
        good = ("fresh clone of 9f8e7d6; 133 tests OK; run_all ok", "9f8e7d6", "a" * 40, "https://example.org/run/1",
                "src/checks/check_changes.py", "run 1", "fresh-agent verification at 1a2b3c4")
        for ok in good:
            self.assertEqual(check_changes.check_record("c", self.rec(evidence=ok)), [], ok)

    def test_verified_needs_evidence(self):
        self.assertTrue(check_changes.check_record("c", self.rec(evidence=None)))

    def test_fix_needs_before_after(self):
        self.assertTrue(check_changes.check_record("c", self.rec(kind="fix")))
        self.assertEqual(check_changes.check_record("c", self.rec(kind="fix", before="red", after="green")), [])

    def test_service_applied_needs_user_yes(self):
        self.assertTrue(check_changes.check_record("c", self.rec(kind="service", status="applied")))
        self.assertEqual(check_changes.check_record(
            "c", self.rec(kind="service", status="applied", approved_by_user=OK1)), [])

    def test_new_kinds_need_user_yes(self):
        for kind in ("production", "deletion", "force_push"):
            self.assertTrue(check_changes.check_record("c", self.rec(kind=kind, status="applied")), kind)
            self.assertTrue(check_changes.check_record(
                "c", self.rec(kind=kind, status="applied", approved_by_user="  ")), kind)
            self.assertEqual(check_changes.check_record(
                "c", self.rec(kind=kind, status="applied", approved_by_user=OK1)), [])
            self.assertEqual(check_changes.check_record("c", self.rec(kind=kind)), [])

    def test_approval_format(self):
        bad = ["", "  ", "no", "yes", "msg-0123456789abcdefghij", '"yes, do it today"',
               'msg-0123456789abcdefghij "yes do"', 'msg-0123456789abcdefghij ""',
               'msg-0 "yes, do it today"', 'msg-0123456789abcdefghij yes do it today',
               "msg-0123456789abcdefghij 'yes, do it today'", '-msg0123456789abcdefghij "yes, do it today"',
               'msg-0123456789abcdefghij "yes, do it today" extra']
        for v in bad:
            for status in ("draft", "verified", "applied"):
                self.assertTrue(check_changes.check_record(
                    "c", self.rec(kind="service", status=status, approved_by_user=v)), (v, status))
            self.assertTrue(check_changes.check_record("c", self.rec(approved_by_user=v)), v)
        self.assertEqual(check_changes.check_record("c", self.rec(approved_by_user=OK1)), [])
        self.assertEqual(check_changes.parse_approval(OK1), "msg-0123456789abcdefghij")
        self.assertIsNone(check_changes.parse_approval(None))

    def test_approval_reuse_across_kinds(self):
        a = ("a", self.rec(kind="service", status="applied", approved_by_user=OK1))
        b = ("b", self.rec(kind="money", status="applied", approved_by_user=OK1))
        self.assertTrue(check_changes.check_reuse([a, b]))
        c = ("c", self.rec(kind="money", status="applied", approved_by_user=OK2))
        self.assertEqual(check_changes.check_reuse([a, c]), [])
        shared = ("s", self.rec(kind="money", status="applied", approved_by_user=OK1, approval_scope="shared"))
        a_shared = ("a", self.rec(kind="service", status="applied", approved_by_user=OK1, approval_scope="shared"))
        self.assertEqual(check_changes.check_reuse([a_shared, shared]), [])
        feat = ("f", self.rec(kind="feature", approved_by_user=OK1))
        self.assertEqual(check_changes.check_reuse([a, feat]), [])

    def test_cost_above_limit_needs_yes(self):
        self.assertTrue(check_changes.check_record("c", self.rec(status="applied", cost_usd="10.01")))
        self.assertEqual(check_changes.check_record("c", self.rec(status="applied", cost_usd="10")), [])
        self.assertEqual(check_changes.check_record(
            "c", self.rec(status="applied", cost_usd="50", approved_by_user=OK3)), [])
        self.assertEqual(check_changes.check_record("c", self.rec(cost_usd="50")), [])

    def test_a_custom_approval_id_and_spend_limit(self):
        pol = check_changes.Policy({"changes": {"approval_id": r"issue-\d+", "spend_limit_usd": 1}})
        self.assertEqual(check_changes.parse_approval('issue-42 "yes, ship it"', pol), "issue-42")
        self.assertIsNone(check_changes.parse_approval(OK1, pol))
        self.assertTrue(check_changes.check_record("c", self.rec(status="applied", cost_usd="2"), pol))

    def test_spend_limit_edge_decides_whether_an_approval_is_reusable_across_kinds(self):
        svc = ("s", self.rec(kind="service", approved_by_user=OK1))
        for cost, reported in (("10", 0), ("10.01", 1), ("11", 1), ("ten", 0), ("0", 0)):
            other = ("f", self.rec(kind="feature", cost_usd=cost, approved_by_user=OK1))
            self.assertEqual(len(check_changes.check_reuse([svc, other])), reported, cost)
        self.assertFalse(check_changes.needs_yes({"kind": "feature", "cost_usd": "10"}))
        self.assertTrue(check_changes.needs_yes({"kind": "feature", "cost_usd": "10.01"}))
        self.assertFalse(check_changes.needs_yes({"kind": "feature", "cost_usd": "nan"}))
        self.assertFalse(check_changes.needs_yes({"kind": "feature"}))

    def test_without_the_changes_folder_the_check_is_quiet(self):
        with tempfile.TemporaryDirectory() as t:
            self.assertEqual(check_changes.run(root=t), [])

    def test_front_matter_and_edges_of_the_shape_rules(self):
        self.assertIsNone(check_changes.parse_front(""))
        self.assertIsNone(check_changes.parse_front("status: draft\n---\n"))
        self.assertIsNone(check_changes.parse_front("---\nstatus: draft\n"))  # never closed
        self.assertTrue(check_changes.evidence_has_detail("a/b.md"))  # exactly 6 characters
        self.assertFalse(check_changes.evidence_has_detail("a/b.m"))
        three = 'msg-0123456789abcdefghij "one two three"'
        two = 'msg-0123456789abcdefghij "one two"'
        self.assertEqual(check_changes.parse_approval(three), "msg-0123456789abcdefghij")
        self.assertIsNone(check_changes.parse_approval(two))
        self.assertIsNone(check_changes.parse_approval(None))

    def test_run_reports_each_missing_file_by_name_and_only_those(self):
        with tempfile.TemporaryDirectory() as t:
            d = pathlib.Path(t, "changes", "0002-x")
            d.mkdir(parents=True)
            (d / "proposal.md").write_text("x")
            self.assertEqual(sorted(check_changes.run(root=t)), ["0002-x: missing tasks.md", "0002-x: missing verification.md"])
            (d / "tasks.md").write_text("x")
            (d / "verification.md").write_text("---\nstatus: proposed\nkind: feature\nauthor: a\n---\n")
            self.assertEqual(check_changes.run(root=t), [])

    def test_the_archive_folder_itself_is_not_a_record_and_a_good_archived_record_passes(self):
        with tempfile.TemporaryDirectory() as t:
            d = pathlib.Path(t, "changes", "archive", "0003-y")
            d.mkdir(parents=True)
            for f in check_changes.FILES:
                (d / f).write_text("---\nstatus: proposed\nkind: feature\nauthor: a\n---\n" if f == "verification.md" else "x")
            self.assertEqual(check_changes.run(root=t), [])

    def test_cost_must_be_numeric(self):
        for bad in ("ten", "$5", "", "nan", "inf", "-1"):
            self.assertTrue(check_changes.check_record("c", self.rec(cost_usd=bad)), bad)
        self.assertIsNone(check_changes.parse_cost("abc"))
        self.assertEqual(check_changes.parse_cost("2.5"), 2.5)

    def test_run_rejects_reused_approval_end_to_end(self):
        with tempfile.TemporaryDirectory() as t:
            for name, kind in (("0005-a", "service"), ("0006-b", "money")):
                d = pathlib.Path(t, "changes", name)
                d.mkdir(parents=True)
                for f in check_changes.FILES:
                    (d / f).write_text(
                        f"---\nstatus: applied\nkind: {kind}\nauthor: a1\nverifier: b2\nevidence: e\n"
                        f"approved_by_user: {OK1}\n---\n" if f == "verification.md" else "x")
            self.assertTrue(any("reused" in p for p in check_changes.run(root=t)))

    def test_archive_is_checked_too(self):
        with tempfile.TemporaryDirectory() as t:
            d = pathlib.Path(t, "changes", "archive", "0003-y")
            d.mkdir(parents=True)
            for f in check_changes.FILES:
                (d / f).write_text("---\nstatus: applied\nkind: money\nauthor: a\n---\n" if f == "verification.md" else "x")
            self.assertTrue(check_changes.run(root=t))

    def test_applied_with_open_task_reported(self):
        for status, tasks, bad in (("applied", "- [x] a\n- [ ] b\n", True), ("applied", "- [x] a\n", False),
                                   ("verified", "- [ ] b\n", False)):
            with tempfile.TemporaryDirectory() as t:
                d = pathlib.Path(t, "changes", "0002-x")
                d.mkdir(parents=True)
                (d / "proposal.md").write_text("x")
                (d / "tasks.md").write_text(tasks)
                (d / "verification.md").write_text(
                    f"---\nstatus: {status}\nkind: feature\nauthor: a1\nverifier: b2\nevidence: run 1\n---\n")
                self.assertEqual(any("open task" in p for p in check_changes.run(root=t)), bad, (status, tasks))

    def test_directory_missing_files_reported(self):
        with tempfile.TemporaryDirectory() as t:
            d = pathlib.Path(t, "changes", "0002-x")
            d.mkdir(parents=True)
            (d / "proposal.md").write_text("x")
            self.assertTrue(check_changes.run(root=t))

    def test_duplicate_change_number_reported(self):
        self.assertEqual(check_changes.check_numbers(["0011-a", "0012-b", "0013-c"]), [])
        bad = check_changes.check_numbers(["0012-a", "0012-b"])
        self.assertEqual(len(bad), 1)
        self.assertIn("0012-a", bad[0]); self.assertIn("0012-b", bad[0])

    def test_run_reports_duplicate_number_across_live_and_archive(self):
        with tempfile.TemporaryDirectory() as t:
            for sub in ("0007-x", "archive/0007-y"):
                d = pathlib.Path(t, "changes", sub)
                d.mkdir(parents=True)
                for f in check_changes.FILES:
                    (d / f).write_text("---\nstatus: proposed\nkind: feature\nauthor: a\n---\n" if f == "verification.md" else "x")
            self.assertTrue(any("change number 0007" in p for p in check_changes.run(root=t)))


if __name__ == "__main__":
    unittest.main()
