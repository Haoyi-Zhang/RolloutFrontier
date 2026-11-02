"""Owned endpoint constructor metadata; reject Boolean/numeric aliases."""
from pathlib import Path
import tempfile
import subprocess
import sys
import unittest
from src.controller import Endpoint


class WindowTypeTests(unittest.TestCase):
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
