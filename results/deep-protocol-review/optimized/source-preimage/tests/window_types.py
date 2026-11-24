"""Owned endpoint constructor metadata; reject Boolean/numeric aliases."""
from pathlib import Path
import tempfile
import subprocess
import sys
import unittest
from unittest.mock import patch
from src.controller import Endpoint
from tests import optimizer_benchmark


class WindowTypeTests(unittest.TestCase):
    def _optimizer_fixture(self):
        return [("owned-check", [], {}, {}, 1)]

    def test_optimizer_checks_run_for_every_measured_plan(self):
        plan = {"search": {}, "frontier_size": 1, "product_mass": 1}
        with patch.object(optimizer_benchmark, "cases", return_value=self._optimizer_fixture()), \
             patch.object(optimizer_benchmark, "execute", return_value=(plan, 1)), \
             patch.object(optimizer_benchmark.checker, "frontier_certificate", return_value=True) as check:
            result = optimizer_benchmark.run(3)
        self.assertEqual(check.call_count, 6)
        self.assertTrue(result["rows"][0]["complete_plan_equal"])

    def test_optimizer_warmup_mismatch_is_not_optimized_away(self):
        with patch.object(optimizer_benchmark, "cases", return_value=self._optimizer_fixture()), \
             patch.object(optimizer_benchmark, "execute", side_effect=[({}, 1), ({"different": True}, 1)]):
            with self.assertRaisesRegex(RuntimeError, "warmup complete-plan mismatch"):
                optimizer_benchmark.run(3)

    def test_optimizer_checker_rejection_is_not_optimized_away(self):
        with patch.object(optimizer_benchmark, "cases", return_value=self._optimizer_fixture()), \
             patch.object(optimizer_benchmark, "execute", return_value=({}, 1)), \
             patch.object(optimizer_benchmark.checker, "frontier_certificate", return_value=False):
            with self.assertRaisesRegex(RuntimeError, "frontier certificate rejected"):
                optimizer_benchmark.run(3)

    def test_noninteger_window_rejected_before_creating_durable_store(self):
        for value in (True,1.0):
            with self.subTest(window=value), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp)/'must-not-create.sqlite'
                with self.assertRaises(ValueError):
                    endpoint = Endpoint(0,['a'],path,window=value)
                    endpoint.disconnect()
                self.assertFalse(path.exists())

    def test_invalid_optimized_benchmark_rejected_before_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'must-not-create'/'measurements.json'
            process = subprocess.run([sys.executable,'-O','-B','-m','tests.full_path_costs','--out',str(path),'--repeats','0'],
                                     capture_output=True,text=True,encoding='utf-8',timeout=15)
            self.assertNotEqual(process.returncode,0)
            self.assertIn('invalid choice',process.stderr)
            self.assertFalse(path.parent.exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)
