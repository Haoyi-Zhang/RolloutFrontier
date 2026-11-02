"""Pure delivery-contract controls; no sockets, stores, timing or study reruns.

Saved rows are read or copied in memory only. Child interpreters exercise the
default data-only binding CLI under explicit locale modes, never a benchmark.
This explicit CI module is separate from the retained five-test smoke job.
"""
import asyncio
from contextlib import redirect_stdout
from copy import deepcopy
import hashlib
from io import StringIO
from itertools import product
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from lifecycle_table import derive
from src.controller import Endpoint, MAX_SEQ
from src import network
from tests.full_path_costs import POLICIES, summarize
from tests import check_effect_drain
from verify_claims import verify

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'results/durable-state-costs'
PRODUCER = 'tests/full_path_costs.py'
CAPTURE = DATA / 'source-preimage' / PRODUCER
RETAINED_TABLE = (
    '% Derived from results/durable-state-costs/measurements.json; all48rows/1152proposals.\n'
    'Fixed & 0/0 & 582.5/609.2 & 894.9/909.9 \\\\\n'
    'Greedy & 24/0 & 629.0/591.4 & 1115.2/929.0 \\\\\n'
    'Max mass & 0/24 & 594.1/624.4 & 905.3/1128.5 \\\\\n'
    'Batch choice & 24/0 & 623.8/615.5 & 1213.7/1025.9 \\\\\n'
)


def preserved_producer():
    """Check the registered historical bytes, never reseal them as current."""
    environment = json.loads((DATA / 'environment.json').read_text(encoding='utf-8'))
    entries = [entry for entry in environment['sources'] if entry['path'] == PRODUCER]
    if len(entries) != 1:
        raise ValueError('ambiguous measured producer identity')
    expected = entries[0]['sha256']
    try:
        captured = CAPTURE.read_bytes()
    except OSError as error:
        raise ValueError('measured producer preimage missing') from error
    if hashlib.sha256(captured).hexdigest() != expected:
        raise ValueError('measured producer preimage differs')
    return expected, captured


class ProfileAdmission(unittest.TestCase):
    def test_malformed_profiles_raise_validation_and_leave_state_unchanged(self):
        good = dict(node=1, generation=0, support=['a'])
        malformed = [None, [], 1, 'profile', {}, {**good, 'extra': 1},
                     {k: v for k, v in good.items() if k != 'support'}]
        malformed += [{**good, 'node': value} for value in (True, 1.0, -1, 6)]
        malformed += [{**good, 'generation': value} for value in (False, 0.0, -1, MAX_SEQ + 1)]
        malformed += [{**good, 'support': value} for value in
                      (None, 'a', ('a',), ['a', 'a'], ['b', 'a'], [''], [1])]
        owner = Endpoint(0, ['a'])
        before = deepcopy(owner.state)
        for profile in malformed:
            with self.subTest(profile=profile), self.assertRaises(ValueError):
                owner.handle(dict(op='merge', profile=profile))
            self.assertEqual(owner.state, before)

    def test_valid_merge_still_respects_authority_generations_and_detachment(self):
        owner = Endpoint(0, ['a'])
        profile = dict(node=1, generation=1, support=['a'])
        self.assertEqual(owner.merge(profile)['status'], 'merged')
        profile['support'].clear()
        self.assertEqual(owner.state['catalog']['1']['support'], ['a'])
        self.assertEqual(owner.merge(dict(node=1, generation=1, support=['a']))['status'], 'unchanged')
        self.assertEqual(owner.merge(dict(node=1, generation=1, support=['b']))['status'], 'equivocation-rejected')
        self.assertEqual(owner.merge(dict(node=1, generation=0, support=['b']))['status'], 'unchanged')
        self.assertEqual(owner.merge(dict(node=0, generation=1, support=[]))['status'], 'self-authority-rejected')
        self.assertEqual(owner.merge(owner.profile())['status'], 'unchanged')


class AdapterAdmission(unittest.IsolatedAsyncioTestCase):
    async def test_real_service_callback_returns_invalid_and_continues_without_sockets(self):
        owner = Endpoint(0, ['a'])  # No durable path: memory only.
        before = deepcopy(owner.state)
        net = object.__new__(network.Network)  # Do not create a directory.
        net.nodes, net.servers, net.ports, net.server_writers = {}, {}, {}, {}
        net.supports, net.directory, net.window, net.policy = [['a']], ROOT, 8, 'predicate'
        server = SimpleNamespace(sockets=[SimpleNamespace(getsockname=lambda: ('127.0.0.1', 1))])
        starter = AsyncMock(return_value=server)
        with patch.object(network, 'Endpoint', return_value=owner), \
                patch.object(asyncio, 'start_server', starter):
            await net.start_node(0)
        callback = starter.call_args.args[0]
        requests = [dict(op='merge', profile=value) for value in (None, [], 1, 'profile')]
        requests.append(dict(op='read'))
        reader = SimpleNamespace(readline=AsyncMock(side_effect=[
            (json.dumps(request) + '\n').encode() for request in requests] + [b'']))

        class Writer:
            def __init__(self):
                self.frames, self.closed = [], False

            def write(self, data):
                self.frames.append(data)

            async def drain(self):
                pass

            def close(self):
                self.closed = True

            async def wait_closed(self):
                pass

        writer = Writer()
        await callback(reader, writer)
        responses = [json.loads(frame) for frame in writer.frames]
        self.assertEqual([row['status'] for row in responses], ['invalid'] * 4 + ['observed'])
        self.assertEqual([row['reason'] for row in responses[:-1]], ['ValueError'] * 4)
        self.assertEqual(owner.state, before)
        self.assertTrue(writer.closed)


class RepetitionAndMedians(unittest.TestCase):
    def setUp(self):
        self.data = json.loads((DATA / 'measurements.json').read_text(encoding='utf-8'))

    def test_retained_rows_and_published_table_are_unchanged(self):
        before = deepcopy(self.data['rows'])
        result = summarize(self.data['rows'], 3)
        self.assertEqual(result['groups'], self.data['groups'])
        self.assertEqual((result['trials'], result['proposals_total']), (48, 1152))
        self.assertEqual(self.data['rows'], before)
        # Keep the standalone artifact CI independent of the paper directory.
        self.assertEqual(derive(result), RETAINED_TABLE)

    def test_old_cohort_reaggregation_keeps_its_own_medians(self):
        rows = json.loads((ROOT / 'results/repair-full-path.json').read_text(encoding='utf-8'))['rows']
        saved = json.loads((ROOT / 'results/repair-full-path-summary.json').read_text(encoding='utf-8'))
        self.assertEqual(summarize(rows, 3)['groups'], saved['groups'])

    def test_complete_typed_repetition_product_for_every_supported_repeat_count(self):
        for repeats in range(1, 6):
            # Tiny schema fixture, not a measurement or benchmark output.
            rows = [dict(padding_atoms=p, mismatch=m, policy=k, repeat=r,
                         installed=0, blocked=0, unchanged=24, proposals=24,
                         rpc_count=0, owner_persist_calls=0,
                         full_lifecycle_ns=1000 + r, timings_ns={'owned_ns': 100})
                    for p, m, k, r in product((0, 11999), (False, True), POLICIES, range(repeats))]
            with self.subTest(repeats=repeats):
                result = summarize(list(reversed(rows)), repeats)
                self.assertEqual((result['trials'], len(result['groups'])), (16 * repeats, 16))

    def test_duplicate_missing_and_untyped_repetition_identities_reject(self):
        for value in (1, True, 0.0, -1, 3, '0', None):
            rows = deepcopy(self.data['rows'])
            rows[0]['repeat'] = value
            with self.subTest(repeat=value), self.assertRaises(ValueError):
                summarize(rows, 3)
        rows = deepcopy(self.data['rows'])
        del rows[0]['repeat']
        with self.assertRaises(ValueError):
            summarize(rows, 3)
        with self.assertRaises(ValueError):
            summarize(self.data['rows'][:-1], 3)
        for value in (True, 3.0, 0, 6):
            with self.subTest(repeats=value), self.assertRaises(ValueError):
                summarize(self.data['rows'], value)

    def test_actual_finalize_cli_reaggregates_or_rejects_before_any_output_write(self):
        source = ROOT / 'owned-finalize-input.json'
        destination = ROOT / 'owned-finalize-output.json'
        original_read, original_exists = Path.read_text, Path.exists
        for duplicate in (False, True):
            rows = deepcopy(self.data['rows'])
            if duplicate:
                rows[0]['repeat'] = 1
            written = []

            def read(path, *args, **kwargs):
                if path == source:
                    self.assertEqual(kwargs.get('encoding'), 'utf-8')
                    return json.dumps({'rows': rows})
                return original_read(path, *args, **kwargs)

            def write(path, text, *args, **kwargs):
                self.assertEqual(path, destination)
                written.append(json.loads(text))
                return len(text)

            # Virtual output boundary only: no directory or output file is made.
            with self.subTest(duplicate=duplicate), \
                    patch.object(sys, 'argv', ['full_path_costs.py', '--out', str(destination),
                                              '--finalize-from', str(source)]), \
                    patch.object(Path, 'exists', new=lambda path: False if path == destination else original_exists(path)), \
                    patch.object(Path, 'mkdir', autospec=True), \
                    patch.object(Path, 'read_text', autospec=True, side_effect=read), \
                    patch.object(Path, 'write_text', autospec=True, side_effect=write), \
                    redirect_stdout(StringIO()):
                if duplicate:
                    with self.assertRaisesRegex(ValueError, 'missing/duplicate repetition identity'):
                        runpy.run_path(str(ROOT / PRODUCER), run_name='__main__')
                    self.assertEqual(written, [])
                else:
                    runpy.run_path(str(ROOT / PRODUCER), run_name='__main__')
                    self.assertEqual(len(written), 1)
                    self.assertEqual(written[0]['groups'], self.data['groups'])
                    self.assertEqual(written[0]['rows'], rows)

    def test_typed_group_identities_reject_aliases_and_missing_fields(self):
        for key, value in [('padding_atoms', False), ('padding_atoms', 0.0),
                           ('mismatch', 0), ('mismatch', 0.0), ('policy', []),
                           ('policy', 'unknown')]:
            rows = deepcopy(self.data['rows'])
            rows[0][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                summarize(rows, 3)
        for key in ('padding_atoms', 'mismatch', 'policy'):
            rows = deepcopy(self.data['rows'])
            del rows[0][key]
            with self.subTest(missing=key), self.assertRaises(ValueError):
                summarize(rows, 3)

    def test_ns_roundtrip_rounds_only_the_display_and_rejects_real_disagreement(self):
        for delta in (-1, 1):
            rows = deepcopy(self.data['rows'])
            first = rows[0]
            group = sorted([row for row in rows if all(row[key] == first[key]
                           for key in ('padding_atoms', 'mismatch', 'policy'))],
                           key=lambda row: row['full_lifecycle_ns'])
            group[1]['full_lifecycle_ns'] += delta  # In-memory precision control only.
            result = summarize(rows, 3)
            with self.subTest(delta=delta):
                self.assertEqual(result['groups'][0]['full_lifecycle_median_ms'],
                                 group[1]['full_lifecycle_ns'] / 1e6)
                self.assertEqual(derive(result), derive(self.data))
                result['groups'][0]['full_lifecycle_median_ms'] += 0.000001
                with self.assertRaisesRegex(ValueError, 'raw/summary disagreement'):
                    derive(result)


class Utf8Bindings(unittest.TestCase):
    def test_manifest_and_result_reads_are_explicit_utf8(self):
        original = Path.read_text

        def checked(path, *args, **kwargs):
            self.assertEqual(kwargs.get('encoding'), 'utf-8')
            return original(path, *args, **kwargs)

        with patch.object(Path, 'read_text', autospec=True, side_effect=checked):
            self.assertEqual(verify(ROOT / 'results'), 33)

    def test_numeric_type_and_value_guards_are_not_waived(self):
        for value in (True, 1.0, '1', 2):
            def read(path, *args, **kwargs):
                self.assertEqual(kwargs.get('encoding'), 'utf-8')
                return json.dumps([dict(id='owned', result_file='owned.json', path=['n'], expected=1)]
                                  if path.name == 'claim_bindings.json' else {'n': value})
            with self.subTest(value=value), \
                    patch.object(Path, 'read_text', autospec=True, side_effect=read), \
                    self.assertRaisesRegex(ValueError, 'claim binding mismatch'):
                verify(ROOT / 'results')

    def test_default_cli_with_utf8_mode_disabled_and_enabled(self):
        for mode in ('0', '1'):
            env = dict(os.environ, PYTHONUTF8=mode, PYTHONCOERCECLOCALE='0',
                       LC_ALL='C', LANG='C', PYTHONDONTWRITEBYTECODE='1')
            command = [sys.executable] + ([] if __debug__ else ['-O'])
            command += ['-B', str(ROOT / 'verify_claims.py')]
            result = subprocess.run(command, cwd=ROOT, env=env, capture_output=True,
                                    text=True, encoding='utf-8', timeout=10,
                                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            with self.subTest(utf8_mode=mode):
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout), {'verified_numeric_bindings': 33})


class RecordedSources(unittest.TestCase):
    def test_measured_producer_preimage_is_exact_and_not_current(self):
        expected, captured = preserved_producer()
        self.assertEqual(hashlib.sha256(captured).hexdigest(), expected)
        self.assertNotEqual(hashlib.sha256((ROOT / PRODUCER).read_bytes()).hexdigest(), expected)

    def test_missing_corrupt_or_current_producer_cannot_replace_measured_bytes(self):
        original = Path.read_bytes
        for replacement in (None, CAPTURE.read_bytes() + b'\n', (ROOT / PRODUCER).read_bytes()):
            def read(path):
                if path == CAPTURE:
                    if replacement is None:
                        raise FileNotFoundError('owned missing-preimage control')
                    return replacement
                return original(path)
            with self.subTest(missing=replacement is None), patch.object(Path, 'read_bytes', new=read), \
                    self.assertRaises(ValueError):
                preserved_producer()

    def test_existing_effect_source_guard_uses_preserved_controller_before_database_checks(self):
        # Stop at the archive boundary: exercise the actual source guard only,
        # without extracting the 96 databases or changing any persistent input.
        class SourcesChecked(Exception):
            pass

        with patch.object(check_effect_drain.zipfile, 'ZipFile', side_effect=SourcesChecked) as archive:
            with self.assertRaises(SourcesChecked):
                check_effect_drain.verify()
            archive.assert_called_once()
        capture = check_effect_drain.DATA / 'source-preimage/src/controller.py'
        original = Path.read_bytes
        for replacement in (capture.read_bytes() + b'\n', (ROOT / 'src/controller.py').read_bytes()):
            def read(path):
                return replacement if path == capture else original(path)
            with patch.object(Path, 'read_bytes', new=read), \
                    patch.object(check_effect_drain.zipfile, 'ZipFile') as archive:
                with self.assertRaisesRegex(ValueError, 'Executed input differs src/controller.py'):
                    check_effect_drain.verify()
                archive.assert_not_called()
        is_file = Path.is_file
        with patch.object(Path, 'is_file', new=lambda path: False if path == capture else is_file(path)), \
                patch.object(check_effect_drain.zipfile, 'ZipFile') as archive:
            with self.assertRaisesRegex(ValueError, 'Measured source preimage missing src/controller.py'):
                check_effect_drain.verify()
            archive.assert_not_called()


if __name__ == '__main__':
    unittest.main(verbosity=2)
