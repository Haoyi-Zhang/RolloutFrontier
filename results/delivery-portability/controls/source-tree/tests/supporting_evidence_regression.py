"""Ensure revision evidence checks reject logically inconsistent retained data."""
import csv
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
import zipfile
from tests.check_supporting_evidence import DATA, accepted, check_batch, check_effects, rectangles, replay


class RevisionEvidenceRegression(unittest.TestCase):
    batch_directory = DATA / 'batch-generalization'
    effects_directory = DATA / 'effect-drain'

    def copy_batch(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        target = Path(temporary.name) / 'batch'
        shutil.copytree(self.batch_directory, target)
        return target

    @staticmethod
    def contexts(target):
        return [json.loads(line) for line in (target / 'contexts.jsonl').read_text().splitlines()]

    @staticmethod
    def write_contexts(target, contexts):
        (target / 'contexts.jsonl').write_text(
            ''.join(json.dumps(row) + '\n' for row in contexts), encoding='utf-8')

    @staticmethod
    def encode(rectangle):
        return {str(owner): [[('left.' if owner == 0 else 'right.') + str(value)]
                            for value in sorted(values)]
                for owner, values in enumerate(rectangle)}

    def replace_policy(self, context, policy, rectangle):
        context['boxes'][policy] = self.encode(rectangle)
        cells = set(map(tuple, context['relation']))
        for regime, schedule in context['schedules'].items():
            context['observations'][regime][policy] = replay(
                cells, context['initial'], rectangle, schedule)
        context['changed_from_mass'] = context['boxes']['batch'] != context['boxes']['mass']

    def test_relation_must_match_registered_family_and_seed(self):
        target = self.copy_batch()
        contexts = self.contexts(target)
        contexts[0]['relation'] = sorted(contexts[0]['relation'] + [[3, 0]])
        self.write_contexts(target, contexts)
        with self.assertRaisesRegex(ValueError, 'Registered batch relation differs'):
            check_batch(target)

    def test_schedules_must_match_registered_random_streams(self):
        for field, message in (('schedule', 'Registered batch schedules differ'),
                               ('training', 'Supplied-batch identity differs')):
            with self.subTest(field=field):
                target = self.copy_batch()
                contexts = self.contexts(target)
                if field == 'schedule':
                    proposal = contexts[0]['schedules']['same-demand'][0]
                    proposal[1] = (proposal[1] + 1) % 4
                else:
                    # Python equates bool and int; the saved stream must keep
                    # the registered integer owner, including its JSON type.
                    proposal = contexts[0]['training'][0]
                    proposal[0] = bool(proposal[0])
                self.write_contexts(target, contexts)
                with self.assertRaisesRegex(ValueError, message):
                    check_batch(target)

    def test_off_catalog_guard_terms_are_rejected(self):
        target = self.copy_batch()
        contexts = self.contexts(target)
        contexts[0]['boxes']['mass']['0'].append(['outside.atom'])
        self.write_contexts(target, contexts)
        with self.assertRaisesRegex(ValueError, 'Noncanonical singleton guard'):
            check_batch(target)

    def test_another_safe_rectangle_cannot_replace_fixed_order_greedy(self):
        target = self.copy_batch()
        contexts = self.contexts(target)
        changed = False
        for context in contexts:
            cells = set(map(tuple, context['relation']))
            _, frontier = rectangles(cells, context['initial'])
            old = accepted(context['boxes']['greedy'])
            alternatives = [rectangle for rectangle in frontier if rectangle != old]
            if alternatives:
                self.replace_policy(context, 'greedy', alternatives[0])
                changed = True
                break
        self.assertTrue(changed, 'Fixture lacks a different safe greedy choice')
        self.write_contexts(target, contexts)
        with self.assertRaisesRegex(ValueError, 'Fixed-order greedy choice differs'):
            check_batch(target)

    def test_mass_optimum_must_follow_the_registered_tie_rule(self):
        target = self.copy_batch()
        contexts = self.contexts(target)
        changed = False
        for context in contexts:
            cells = set(map(tuple, context['relation']))
            _, frontier = rectangles(cells, context['initial'])
            old = accepted(context['boxes']['mass'])
            old_mass = len(old[0]) * len(old[1])
            alternatives = [rectangle for rectangle in frontier if rectangle != old and
                            len(rectangle[0]) * len(rectangle[1]) == old_mass]
            if alternatives:
                self.replace_policy(context, 'mass', alternatives[0])
                changed = True
                break
        self.assertTrue(changed, 'Fixture lacks a tied mass choice')
        self.write_contexts(target, contexts)
        with self.assertRaisesRegex(ValueError, 'Mass tie rule differs'):
            check_batch(target)

    def test_training_optimum_must_follow_the_batch_tie_rule(self):
        target = self.copy_batch()
        contexts = self.contexts(target)
        context = next(row for row in contexts if (row['family'], row['seed']) == ('cycle', 6009))
        cells = set(map(tuple, context['relation']))
        _, frontier = rectangles(cells, context['initial'])
        old = accepted(context['boxes']['batch'])
        count = replay(cells, context['initial'], old, context['training'])['installed']
        alternative = next(rectangle for rectangle in frontier if rectangle != old and
                           replay(cells, context['initial'], rectangle, context['training'])['installed'] == count)
        self.replace_policy(context, 'batch', alternative)
        self.write_contexts(target, contexts)
        with self.assertRaisesRegex(ValueError, 'Batch tie rule differs'):
            check_batch(target)

    def test_csv_cannot_differ_from_detailed_batch_events(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / 'batch'
            shutil.copytree(self.batch_directory, target)
            path = target / 'observations.csv'
            with path.open(newline='', encoding='utf-8') as stream:
                reader = csv.DictReader(stream)
                fields, rows = reader.fieldnames, list(reader)
            rows[0]['batch_installed'] = str(int(rows[0]['batch_installed']) + 1)
            with path.open('w', newline='', encoding='utf-8') as stream:
                writer = csv.DictWriter(stream, fieldnames=fields)
                writer.writeheader()
                writer.writerows(rows)
            with self.assertRaisesRegex(ValueError, 'CSV rows differ'):
                check_batch(target)

    def test_per_event_output_cannot_override_literal_transition(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / 'batch'
            shutil.copytree(self.batch_directory, target)
            path = target / 'contexts.jsonl'
            contexts = [json.loads(line) for line in path.read_text().splitlines()]
            statuses = contexts[0]['observations']['supplied']['batch']['statuses']
            statuses[0] = 'installed' if statuses[0] != 'installed' else 'blocked'
            path.write_text(''.join(json.dumps(row) + '\n' for row in contexts), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'per-event observations differ'):
                check_batch(target)

    def test_updated_hash_cannot_hide_missing_application_fence(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / 'effects'
            shutil.copytree(self.effects_directory, target)
            archive_path = target / 'databases.zip'
            with zipfile.ZipFile(archive_path) as archive:
                saved = {name: archive.read(name) for name in archive.namelist()}
            name = 'case-0/effects.sqlite'
            database = Path(temporary) / 'changed.sqlite'
            database.write_bytes(saved[name])
            connection = sqlite3.connect(database)
            connection.execute("UPDATE leases SET phase='open'")
            connection.commit()
            connection.close()
            saved[name] = database.read_bytes()
            identities_path = target / 'database-identities.json'
            identities = json.loads(identities_path.read_text())
            identities[name] = dict(size=len(saved[name]), sha256=hashlib.sha256(saved[name]).hexdigest())
            identities_path.write_text(json.dumps(identities), encoding='utf-8')
            with zipfile.ZipFile(archive_path, 'w', zipfile.ZIP_DEFLATED) as archive:
                for filename, raw in saved.items():
                    archive.writestr(filename, raw)
            with self.assertRaisesRegex(ValueError, 'Lease fence missing'):
                check_effects(target)


if __name__ == '__main__':
    unittest.main()
