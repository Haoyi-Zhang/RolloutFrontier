"""Durable certificate sequence fields use exact integer types at recovery."""
import asyncio
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from src.network import Client, Network


class RecoveryTypeAliasTests(unittest.IsolatedAsyncioTestCase):
    async def test_boolean_and_float_certificate_sequences_fail_closed(self):
        for envelope in (False, True):
            for alias in (True, 1.0):
                with self.subTest(envelope=envelope, alias=repr(alias)):
                    with tempfile.TemporaryDirectory() as directory:
                        root = Path(directory)
                        net = Network(root, [['a']])
                        await net.start()
                        client = Client(net)
                        try:
                            branches = [{'0': ['a']}]
                            result = (await client.acquire_box('saved', branches, {'0': [['a']]})
                                      if envelope else await client.acquire('saved', branches))
                            self.assertEqual(result['status'], 'admitted')
                            client.disconnect()
                            with sqlite3.connect(root / 'origin-0.sqlite') as db:
                                saved = json.loads(db.execute('SELECT payload FROM state WHERE id=1').fetchone()[0])
                                saved['attempts']['1']['certificate']['sequences']['0'] = alias
                                db.execute('UPDATE state SET payload=? WHERE id=1', (json.dumps(saved),))
                            reopened = None
                            try:
                                with self.assertRaisesRegex(ValueError, 'certificate binding'):
                                    reopened = Client(net)
                            finally:
                                if reopened is not None:
                                    reopened.disconnect()
                            # Invalid origin recovery never releases the owner
                            # guard or authorizes a mutation without a certificate.
                            self.assertEqual(net.nodes[0].install([])['status'], 'blocked')
                        finally:
                            client.disconnect()
                            await net.stop()


if __name__ == '__main__':
    unittest.main(verbosity=2)
