"""Literal-path and read-only regression controls for SQLite evidence readers.

Each control creates a fresh SQLite fixture, reads its actual rows through the
artifact helpers, and attempts a write on each source connection. The fixture
is test input; none of these observations is a workload measurement.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from tests.check_factored_execution import read_state
from tests.check_session_identity import db_rows
from tests.check_utf8_inputs import rows, state
from tests.utf8_input_regression import backup


NAMES = (
    'ordinary space',
    'hash#fragment',
    'query?mode=rw',
    'percent%23encoded%3F',
    '中文-κ-🧪',
    'combined #?% 中文',
)


class SQLitePathTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='sqlite-path-control-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()

    def inventory(self):
        return {p.relative_to(self.root).as_posix(): p.read_bytes()
                for p in self.root.rglob('*') if p.is_file()}

    def path_forms(self, path):
        return (('absolute', path),
                ('relative', Path(os.path.relpath(path, Path.cwd()))))

    def test_readers_open_literal_database_and_remain_read_only(self):
        connect = sqlite3.connect
        for name in NAMES:
            path = self.root / name / (name + '.sqlite')
            path.parent.mkdir()
            payload = {'fixture': name, 'value': 17}
            ledger = ('request-κ', '{"key":"中文"}', 'complete', '{"value":17}')
            with connect(path) as db:
                db.execute('CREATE TABLE state(id INTEGER PRIMARY KEY, payload TEXT NOT NULL)')
                db.execute('INSERT INTO state VALUES(1, ?)', (json.dumps(payload),))
                db.execute('CREATE TABLE requests(request_id TEXT PRIMARY KEY, input TEXT NOT NULL, '
                           'status TEXT NOT NULL, output TEXT)')
                db.execute('INSERT INTO requests VALUES(?,?,?,?)', ledger)
            db.close()
            for form, argument in self.path_forms(path):
                with self.subTest(name=name, path_form=form):
                    before = self.inventory()
                    destination = path.parent / ('copy-' + form + '.sqlite')
                    sources = []
                    opened = []

                    def checked_connect(database, *args, **kwargs):
                        connection = connect(database, *args, **kwargs)
                        opened.append(connection)
                        # Only the explicitly requested backup destination is writable.
                        if not kwargs.get('uri') and Path(database).resolve() == destination:
                            return connection
                        actual = connection.execute('PRAGMA database_list').fetchone()[2]
                        self.assertEqual(Path(actual).resolve(), path)
                        # Test before a helper can enable PRAGMA query_only: the URI
                        # itself must preserve read-only mode at open time.
                        with self.assertRaises(sqlite3.OperationalError) as failure:
                            connection.execute('PRAGMA user_version=91')
                        self.assertEqual(failure.exception.sqlite_errorcode, sqlite3.SQLITE_READONLY)
                        sources.append(Path(actual).resolve())
                        return connection

                    try:
                        with patch.object(sqlite3, 'connect', checked_connect):
                            self.assertEqual(read_state(argument), payload)
                            self.assertEqual(db_rows(argument), [ledger])
                            self.assertEqual(state(argument), payload)
                            self.assertEqual(rows(argument, 'SELECT request_id FROM requests'), [(ledger[0],)])
                            backup(argument, destination)
                        self.assertEqual(sources, [path] * 5)
                        with connect(destination) as copied:
                            self.assertEqual(copied.execute('SELECT * FROM requests').fetchall(), [ledger])
                            self.assertEqual(json.loads(copied.execute('SELECT payload FROM state').fetchone()[0]),
                                             payload)
                        copied.close()
                    finally:
                        for connection in opened:
                            connection.close()
                        if destination.exists():
                            destination.unlink()
                    self.assertEqual(self.inventory(), before,
                                     'Reader changed a database or created a truncated-path file')

    def test_missing_database_is_rejected_without_creating_files(self):
        for name in NAMES:
            path = self.root / name / (name + '.sqlite')
            path.parent.mkdir()
            for form, argument in self.path_forms(path):
                calls = (
                    ('state', lambda: read_state(argument)),
                    ('ledger', lambda: db_rows(argument)),
                    ('Unicode reader', lambda: rows(argument, 'SELECT * FROM state')),
                    ('backup', lambda: backup(argument, path.parent / 'copy.sqlite')),
                )
                for reader, call in calls:
                    with self.subTest(name=name, path_form=form, reader=reader):
                        before = self.inventory()
                        with self.assertRaises(sqlite3.OperationalError) as failure:
                            call()
                        self.assertEqual(failure.exception.sqlite_errorcode, sqlite3.SQLITE_CANTOPEN)
                        self.assertEqual(self.inventory(), before,
                                         'Missing read-only source created an unintended database')


if __name__ == '__main__':
    unittest.main()
