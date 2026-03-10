"""Unit tests for file_reorg_mvp_ai.py core logic."""
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from file_reorg_mvp_ai import (
    normalize_rel_path,
    split_top_folder,
    has_suspicious_version,
    format_size,
    chunk_list,
    unique_target_path,
    FileRecord,
    RuleEngine,
    Planner,
    OperationExecutor,
    OperationPlan,
    DEFAULT_RULES,
)


class TestNormalizeRelPath(unittest.TestCase):
    def test_forward_slashes(self):
        self.assertEqual(normalize_rel_path("a/b/c"), "a\\b\\c")

    def test_strips_leading_trailing(self):
        self.assertEqual(normalize_rel_path("\\foo\\bar\\"), "foo\\bar")

    def test_empty(self):
        self.assertEqual(normalize_rel_path(""), "")

    def test_single_name(self):
        self.assertEqual(normalize_rel_path("file.txt"), "file.txt")


class TestSplitTopFolder(unittest.TestCase):
    def test_normal_path(self):
        self.assertEqual(split_top_folder("01_Ops\\sub\\file.txt"), "01_Ops")

    def test_root(self):
        self.assertEqual(split_top_folder(""), "[ROOT]")

    def test_file_only(self):
        self.assertEqual(split_top_folder("file.txt"), "file.txt")


class TestHasSuspiciousVersion(unittest.TestCase):
    def test_copy(self):
        self.assertTrue(has_suspicious_version("report copy.docx"))

    def test_copia(self):
        self.assertTrue(has_suspicious_version("report copia.docx"))

    def test_parenthesized_number(self):
        self.assertTrue(has_suspicious_version("file (2).txt"))

    def test_version(self):
        self.assertTrue(has_suspicious_version("doc v2.pdf"))

    def test_final(self):
        self.assertTrue(has_suspicious_version("plan final.xlsx"))

    def test_clean_name(self):
        self.assertFalse(has_suspicious_version("report_2024.docx"))


class TestFormatSize(unittest.TestCase):
    def test_bytes(self):
        self.assertEqual(format_size(100), "100 B")

    def test_kb(self):
        result = format_size(2048)
        self.assertIn("KB", result)

    def test_mb(self):
        result = format_size(5 * 1024 * 1024)
        self.assertIn("MB", result)

    def test_zero(self):
        self.assertEqual(format_size(0), "0 B")


class TestChunkList(unittest.TestCase):
    def test_exact(self):
        result = chunk_list([1, 2, 3, 4], 2)
        self.assertEqual(result, [[1, 2], [3, 4]])

    def test_remainder(self):
        result = chunk_list([1, 2, 3], 2)
        self.assertEqual(result, [[1, 2], [3]])

    def test_empty(self):
        self.assertEqual(chunk_list([], 5), [])

    def test_single_chunk(self):
        result = chunk_list([1, 2], 10)
        self.assertEqual(result, [[1, 2]])


class TestUniqueTargetPath(unittest.TestCase):
    def test_non_existing(self):
        p = Path(tempfile.gettempdir()) / "__test_unique_nonexist_12345.txt"
        self.assertEqual(unique_target_path(p), p)

    def test_existing_file(self):
        tmp = Path(tempfile.gettempdir()) / "__test_unique_exist.txt"
        tmp.touch()
        try:
            result = unique_target_path(tmp)
            self.assertNotEqual(result, tmp)
            self.assertIn("__dup", result.name)
        finally:
            tmp.unlink(missing_ok=True)


class TestRuleEngine(unittest.TestCase):
    def _make_record(self, source_path="C:\\test\\file.xlsx", name="file.xlsx",
                     extension=".xlsx", top_folder="TestFolder"):
        return FileRecord(
            source_path=source_path,
            relative_path="TestFolder\\file.xlsx",
            name=name,
            extension=extension,
            size_bytes=1024,
            modified_at="2025-01-01 00:00:00",
            top_folder=top_folder,
        )

    def test_default_rules_loaded(self):
        engine = RuleEngine()
        self.assertTrue(len(engine.rules) > 0)

    def test_rules_sorted_by_priority(self):
        engine = RuleEngine()
        priorities = [r.get("priority", 9999) for r in engine.rules]
        self.assertEqual(priorities, sorted(priorities))

    def test_attendance_rule(self):
        engine = RuleEngine()
        record = self._make_record(
            source_path="C:\\root\\Attendance Report\\Q1.xlsx",
            name="Q1.xlsx",
            extension=".xlsx",
            top_folder="Attendance Report"
        )
        record.relative_path = "Attendance Report\\Q1.xlsx"
        engine.apply(record)
        self.assertEqual(record.suggested_action, "move")
        self.assertIn("Attendance", record.suggested_target_rel)

    def test_root_file_flags(self):
        engine = RuleEngine()
        record = self._make_record(top_folder="[ROOT]")
        engine.apply(record)
        self.assertIn("root_file", record.risk_flags)

    def test_suspicious_name_flags(self):
        engine = RuleEngine()
        record = self._make_record(name="doc copy.xlsx")
        engine.apply(record)
        self.assertIn("version_or_duplicate_pattern", record.risk_flags)

    def test_long_path_flags(self):
        engine = RuleEngine()
        long_path = "C:\\" + "a" * 250 + "\\file.xlsx"
        record = self._make_record(source_path=long_path)
        engine.apply(record)
        self.assertIn("long_path_risk", record.risk_flags)

    def test_save_and_load_rules(self):
        engine = RuleEngine()
        tmp = Path(tempfile.gettempdir()) / "__test_rules.json"
        try:
            engine.save_rules(tmp)
            engine2 = RuleEngine(rules=[])
            engine2.load_rules(tmp)
            self.assertEqual(len(engine.rules), len(engine2.rules))
        finally:
            tmp.unlink(missing_ok=True)


class TestPlanner(unittest.TestCase):
    def test_move_action_target(self):
        engine = RuleEngine()
        planner = Planner(engine)
        root = Path("C:\\TestRoot")

        record = FileRecord(
            source_path="C:\\TestRoot\\Attendance Report\\Q1.xlsx",
            relative_path="Attendance Report\\Q1.xlsx",
            name="Q1.xlsx",
            extension=".xlsx",
            size_bytes=1024,
            modified_at="2025-01-01 00:00:00",
            top_folder="Attendance Report",
        )

        plans = planner.build_plan(root, [record])
        self.assertEqual(len(plans), 1)
        self.assertEqual(plans[0].action, "move")
        self.assertTrue(plans[0].target_path != "")


class TestOperationExecutor(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.log_dir = self.tmp_dir / "_reorg_logs"

    def tearDown(self):
        shutil.rmtree(str(self.tmp_dir), ignore_errors=True)

    def test_validate_missing_source(self):
        executor = OperationExecutor(self.tmp_dir, self.log_dir)
        plans = [OperationPlan(
            source_path=str(self.tmp_dir / "nonexistent.txt"),
            action="move",
            target_path=str(self.tmp_dir / "dest.txt"),
            relative_target_path="dest.txt"
        )]
        errors = executor.validate_plan(plans)
        self.assertTrue(any("Missing source" in e for e in errors))

    def test_validate_duplicate_targets(self):
        executor = OperationExecutor(self.tmp_dir, self.log_dir)
        src1 = self.tmp_dir / "a.txt"
        src2 = self.tmp_dir / "b.txt"
        src1.touch()
        src2.touch()
        dst = str(self.tmp_dir / "out.txt")
        plans = [
            OperationPlan(source_path=str(src1), action="move", target_path=dst, relative_target_path="out.txt"),
            OperationPlan(source_path=str(src2), action="move", target_path=dst, relative_target_path="out.txt"),
        ]
        errors = executor.validate_plan(plans)
        self.assertTrue(any("Duplicate target" in e for e in errors))

    def test_dry_run_no_file_move(self):
        executor = OperationExecutor(self.tmp_dir, self.log_dir)
        src = self.tmp_dir / "original.txt"
        src.write_text("hello")
        dst = str(self.tmp_dir / "moved.txt")
        plans = [OperationPlan(
            source_path=str(src), action="move", target_path=dst, relative_target_path="moved.txt"
        )]
        manifest_json, _ = executor.execute(plans, dry_run=True)
        self.assertTrue(src.exists(), "File should still exist after dry run")
        self.assertFalse(Path(dst).exists(), "Target should not exist after dry run")

    def test_real_run_moves_file(self):
        executor = OperationExecutor(self.tmp_dir, self.log_dir)
        src = self.tmp_dir / "original.txt"
        src.write_text("hello")
        dst_path = self.tmp_dir / "dest" / "moved.txt"
        plans = [OperationPlan(
            source_path=str(src), action="move",
            target_path=str(dst_path), relative_target_path="dest\\moved.txt"
        )]
        executor.execute(plans, dry_run=False)
        self.assertFalse(src.exists(), "Source should be gone after real run")
        self.assertTrue(dst_path.exists(), "Target should exist after real run")


if __name__ == "__main__":
    unittest.main()
