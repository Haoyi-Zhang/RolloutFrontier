"""Untimed harness checks, separate from the retained five-test smoke job."""
import asyncio
import json
from pathlib import Path
import tempfile
import unittest
from src.controller import canonical
from tests.full_path_costs import fixture, summarize, trial


class CostPathRegression(unittest.TestCase):
    def test_complete_modified_path_measures_shutdown_frames(self):
        directory = Path(__file__).resolve().parents[1] / "results"
        with tempfile.TemporaryDirectory(prefix="cost-path-check-", dir=directory) as tmp:
            owned = Path(tmp)
            _, current, _, _, _ = fixture(0, True)
            for node, values in current.items():
                (owned / f"support-{node}.json").write_text(canonical(values), encoding="utf-8")
            result = asyncio.run(trial(owned, "batch", 0, True, 0))
        self.assertEqual((result["installed"], result["blocked"], result["unchanged"]), (0, 12, 12))
        self.assertEqual(result["rpc_count"], 53)
        self.assertEqual(result["management_connections"], 6)
        self.assertEqual(result["total_tcp_connections"], 59)
        self.assertEqual(result["management_frame_bytes"], 270)
        self.assertEqual(result["total_application_frame_bytes"], result["application_frame_bytes"]+270)
        self.assertEqual(result["owner_persist_calls"], 15)
        self.assertGreater(result["full_lifecycle_ns"], result["timings_ns"]["updates_ns"])

    def test_existing_complete_cost_rows_can_be_summarized_without_reexecution(self):
        root = Path(__file__).resolve().parents[1]
        raw = json.loads((root / "results" / "repair-full-path.json").read_text(encoding="utf-8"))
        expected = json.loads((root / "results" / "repair-full-path-summary.json").read_text(encoding="utf-8"))
        actual = summarize(raw["rows"], 3)
        self.assertEqual(actual["groups"], expected["groups"])
        self.assertEqual((actual["trials"], actual["proposals_total"]), (48, 1152))
        self.assertEqual(actual["rows"], raw["rows"])


if __name__ == "__main__":
    unittest.main()
