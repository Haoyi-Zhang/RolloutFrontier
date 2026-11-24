"""Portable checks that the reproduction entry point preserves prior evidence."""
from __future__ import annotations
import contextlib
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import reproduce


class OutputRefusalTests(unittest.TestCase):
    def refuse(self, out):
        with patch.object(sys, "argv", ["reproduce.py", "--out", str(out)]), contextlib.redirect_stderr(io.StringIO()) as log:
            with self.assertRaises(SystemExit) as error:
                reproduce.main()
        self.assertEqual(error.exception.code, 2)
        self.assertIn("new or empty", log.getvalue())

    def test_prior_generated_result_is_not_removed(self):
        with tempfile.TemporaryDirectory(prefix="output-refusal-") as tmp:
            out = Path(tmp)
            result = out / "unit.json"
            result.write_text('{"prior_evidence":true}\n', encoding="utf-8")
            before = result.read_bytes()
            self.refuse(out)
            self.assertEqual(result.read_bytes(), before)
            self.assertEqual(sorted(p.name for p in out.iterdir()), ["unit.json"])

    def test_unrelated_file_is_also_nonempty(self):
        with tempfile.TemporaryDirectory(prefix="output-refusal-") as tmp:
            out = Path(tmp)
            marker = out / "notes.txt"
            marker.write_text("keep evidence\n", encoding="utf-8")
            self.refuse(out)
            self.assertEqual(marker.read_text(encoding="utf-8"), "keep evidence\n")

    def test_nested_directory_is_also_nonempty(self):
        with tempfile.TemporaryDirectory(prefix="output-refusal-") as tmp:
            out = Path(tmp)
            (out / "nested").mkdir()
            self.refuse(out)
            self.assertTrue((out / "nested").is_dir())


if __name__ == "__main__":
    unittest.main()
