"""Data-only historical-source checks; never execute the preserved study sources."""
from contextlib import contextmanager
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from tests import check_effect_drain as check

ROOT = check.ROOT
DATA = check.DATA
SPLIT_SOURCES = ('src/effect_ledger.py', 'src/network.py')


class EffectDrainBindingTests(unittest.TestCase):
    @contextmanager
    def fixture(self):
        # All negative controls edit disposable copies, never retained evidence.
        with tempfile.TemporaryDirectory(prefix='effect-source-binding-') as temporary:
            root = Path(temporary)
            data = root / 'results/effect-drain'
            shutil.copytree(DATA, data)
            registration = json.loads((data / 'registration.json').read_text(encoding='utf-8'))
            for rel in registration['source_bindings']:
                target = root / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / rel, target)
            with patch.object(check, 'ROOT', root), patch.object(check, 'DATA', data):
                yield root, data

    def test_packaged_historical_observations_and_all_database_snapshots(self):
        self.assertEqual(check.verify(), dict(status='PASS', lifecycles=24,
            database_snapshots=96, independent_performance_comparison_claimed=False))

    def test_repaired_live_sources_are_distinct_from_recorded_preimages(self):
        bindings = json.loads((DATA / 'registration.json').read_text(encoding='utf-8'))['source_bindings']
        for rel in SPLIT_SOURCES:
            with self.subTest(source=rel):
                captured = DATA / 'source-preimage' / rel
                self.assertEqual(hashlib.sha256(captured.read_bytes()).hexdigest(), bindings[rel])
                self.assertNotEqual(hashlib.sha256((ROOT / rel).read_bytes()).hexdigest(), bindings[rel])

    def test_missing_preimage_is_not_replaced_by_live_code(self):
        for rel in SPLIT_SOURCES:
            with self.subTest(source=rel), self.fixture() as (_, data):
                (data / 'source-preimage' / rel).unlink()
                with self.assertRaisesRegex(ValueError, 'Measured source preimage missing ' + rel):
                    check.verify()

    def test_corrupt_preimage_is_rejected(self):
        for rel in SPLIT_SOURCES:
            with self.subTest(source=rel), self.fixture() as (_, data):
                captured = data / 'source-preimage' / rel
                captured.write_bytes(captured.read_bytes() + b'\n')
                with self.assertRaisesRegex(ValueError, 'Executed input differs ' + rel):
                    check.verify()

    def test_live_source_cannot_substitute_for_recorded_preimage(self):
        for rel in SPLIT_SOURCES:
            with self.subTest(source=rel), self.fixture() as (root, data):
                shutil.copyfile(root / rel, data / 'source-preimage' / rel)
                with self.assertRaisesRegex(ValueError, 'Executed input differs ' + rel):
                    check.verify()

    def test_later_live_edits_do_not_relabel_historical_observations(self):
        with self.fixture() as (root, _):
            for rel in (*SPLIT_SOURCES, 'tests/effect_drain_study.py'):
                live = root / rel
                live.write_bytes(live.read_bytes() + b'\n# Disposable current-source edit.\n')
            self.assertEqual(check.verify()['status'], 'PASS')

    def test_executed_driver_is_the_recorded_snapshot_not_the_live_driver(self):
        bindings = json.loads((DATA / 'registration.json').read_text(encoding='utf-8'))['source_bindings']
        rel = 'tests/effect_drain_study.py'
        snapshot = gzip.decompress((DATA / 'execution-source.py.gz').read_bytes())
        self.assertEqual(hashlib.sha256(snapshot).hexdigest(), bindings[rel])
        self.assertNotEqual(hashlib.sha256((ROOT / rel).read_bytes()).hexdigest(), bindings[rel])
        with self.fixture() as (root, data):
            (data / 'execution-source.py.gz').write_bytes(gzip.compress((root / rel).read_bytes()))
            with self.assertRaisesRegex(ValueError, 'Historical source differs'):
                check.verify()


if __name__ == '__main__':
    unittest.main()
