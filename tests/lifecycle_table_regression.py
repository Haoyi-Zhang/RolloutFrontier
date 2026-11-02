"""Explicit CI regression, separate from the retained five-test smoke denominator."""
import json
import copy
import hashlib
from pathlib import Path
import unittest
from unittest.mock import patch
import lifecycle_table as receiver
from lifecycle_table import ROOT,derive,verify_sources

class LifecycleTable(unittest.TestCase):
    def setUp(self):
        self.data=json.loads((ROOT/'results/durable-state-costs/measurements.json').read_text())
    def test_exact_current_table(self):
        result=derive(self.data)
        self.assertIn('582.5/609.2',result)
        self.assertIn('1213.7/1025.9',result)
        self.assertEqual(len(result.splitlines()),5)
    def test_old_summary_is_not_current(self):
        old=json.loads((ROOT/'results/repair-full-path-summary.json').read_text())
        self.data['groups']=old['groups']
        with self.assertRaises(ValueError):derive(self.data)
    def test_missing_repetition(self):
        self.data['rows'][0]['repeat']=1
        with self.assertRaises(ValueError):derive(self.data)
    def test_timing_tamper(self):
        self.data['groups'][0]['full_lifecycle_median_ms']+=1
        with self.assertRaises(ValueError):derive(self.data)
    def test_omitted_trial(self):
        self.data['rows'].pop()
        with self.assertRaises(ValueError):derive(self.data)

    def test_count_aliases_and_balanced_impossible_outcomes_reject_before_output(self):
        original_read=Path.read_text
        measurements=ROOT/'results/durable-state-costs/measurements.json'
        def reject(data):
            def read(path,*args,**kwargs):
                return json.dumps(data) if path==measurements else original_read(path,*args,**kwargs)
            with patch.object(Path,'read_text',new=read), self.assertRaises(ValueError):
                receiver.table()
        for field in ('repeats','trials','proposals_total'):
            for value in (float(self.data[field]),True,None):
                data=copy.deepcopy(self.data);data[field]=value
                with self.subTest(top_count=field,value=value):reject(data)
        for field in ('installed','blocked','unchanged','proposals','safety_violations','refused_admissions'):
            for value in (bool(self.data['rows'][0][field]),float(self.data['rows'][0][field]),-1,25):
                data=copy.deepcopy(self.data);data['rows'][0][field]=value
                with self.subTest(row_count=field,value=value):reject(data)
        for outcomes in ((-1,13,12),(25,-13,12)):
            data=copy.deepcopy(self.data)
            for row in data['rows']:
                if (row['padding_atoms'],row['mismatch'],row['policy'])==(0,False,'fixed'):
                    row.update(zip(('installed','blocked','unchanged'),outcomes))
            data['groups'][0].update(zip(('installed','blocked','unchanged'),outcomes))
            with self.subTest(balanced_outcomes=outcomes):reject(data)
        for field in ('installed','blocked','unchanged'):
            for value in (False,float(self.data['groups'][0][field]),-1,25):
                data=copy.deepcopy(self.data);data['groups'][0][field]=value
                with self.subTest(summary_count=field,value=value):reject(data)
        data=copy.deepcopy(self.data)
        data['groups'][0].update(blocked=11,unchanged=13)
        reject(data)
        # Match the generator's table-before-write expression without making
        # the standalone artifact depend on the sibling paper directory.
        data=copy.deepcopy(self.data);data['rows'][0]['installed']=False
        with patch.object(receiver,'table',side_effect=lambda:derive(data)), \
                patch.object(Path,'write_text') as write, self.assertRaises(ValueError):
            Path('owned-output.tex').write_text(receiver.table(),encoding='utf-8')
        write.assert_not_called()

class RecordedSources(unittest.TestCase):
    def test_entire_inventory_and_existing_table_consumer(self):
        resolved=verify_sources()
        self.assertEqual(len(resolved),44)
        self.assertEqual(sum(rel==path for rel,path in resolved.items()),35)
        self.assertEqual(sum(path.startswith('results/durable-state-costs/source-preimage/')
                             for path in resolved.values()),7)
        self.assertEqual(sum(path.startswith('results/effect-drain/source-preimage/')
                             for path in resolved.values()),2)
        self.assertEqual(receiver.table(),derive(json.loads(
            (ROOT/'results/durable-state-costs/measurements.json').read_text(encoding='utf-8'))))

    def test_each_resolved_source_rejects_missing_tamper_and_current_substitution(self):
        original=Path.read_bytes
        for rel,path in verify_sources().items():
            capture=ROOT/path
            replacements=[None,original(capture)+b'\n']
            if path!=rel:
                replacements.append(original(ROOT/rel))
            for replacement in replacements:
                def read(candidate):
                    if candidate==capture:
                        if replacement is None:raise FileNotFoundError('owned missing source')
                        return replacement
                    return original(candidate)
                with self.subTest(source=rel,missing=replacement is None), \
                        patch.object(Path,'read_bytes',new=read), \
                        self.assertRaisesRegex(ValueError,'measured source missing or differs '+rel):
                    verify_sources()

    def test_missing_live_files_still_resolve_exact_preserved_bytes(self):
        expected=verify_sources()
        replaced={ROOT/rel for rel,path in expected.items() if rel!=path}
        original=Path.read_bytes
        def read(candidate):
            if candidate in replaced:raise FileNotFoundError('owned absent live source')
            return original(candidate)
        with patch.object(Path,'read_bytes',new=read):
            self.assertEqual(verify_sources(),expected)

    def test_schema_and_paths_reject_before_reading_any_source(self):
        good=dict(path='src/batch.py',sha256='0'*64)
        bad=[None,[],{},dict(sources=None),dict(sources=[]),dict(sources={}),
             dict(sources=[None]),dict(sources=[{}]),dict(sources=[{**good,'extra':1}]),
             dict(sources=[good,good])]
        for rel in (None,1,'../src/batch.py','/src/batch.py','src/../batch.py',
                    'src//batch.py','src/./batch.py','src\\batch.py','C:/src/batch.py',
                    'src/batch.py:stream','src/Batch.py','other/batch.py'):
            bad.append(dict(sources=[{**good,'path':rel}]))
        for digest in (None,1,'','0'*63,'g'*64,'A'*64):
            bad.append(dict(sources=[{**good,'sha256':digest}]))
        for environment in bad:
            with self.subTest(environment=environment), \
                    patch.object(Path,'read_text',return_value=json.dumps(environment)), \
                    patch.object(Path,'read_bytes',side_effect=AssertionError('source read before validation')), \
                    self.assertRaises(ValueError):
                verify_sources()

    def test_table_cannot_bypass_source_failure(self):
        with patch.object(receiver,'verify_sources',side_effect=ValueError('owned missing source')), \
                patch.object(receiver,'derive') as derive_table, \
                self.assertRaisesRegex(ValueError,'owned missing source'):
            receiver.table()
        derive_table.assert_not_called()

    def test_original_inventory_rejects_omission_rebinding_or_extra_entries(self):
        environment_path=ROOT/'results/durable-state-costs/environment.json'
        environment=json.loads(environment_path.read_text(encoding='utf-8'))
        original_read=Path.read_text
        bad=[]
        for index in range(len(environment['sources'])):
            value=copy.deepcopy(environment);value['sources'].pop(index);bad.append(value)
        value=copy.deepcopy(environment);value['sources']=[environment['sources'][0]];bad.append(value)
        value=copy.deepcopy(environment);value['sources'][0]['sha256']='0'*64;bad.append(value)
        value=copy.deepcopy(environment);value['sources'][0]['path']='tests/other.py';bad.append(value)
        value=copy.deepcopy(environment);value['sources'].append(dict(path='tests/other.py',sha256='0'*64));bad.append(value)
        # Same cardinality and a new digest matching changed live bytes is not
        # the original cohort inventory either.
        value=copy.deepcopy(environment)
        binding=next(e for e in value['sources'] if e['path']=='src/batch.py')
        changed=(ROOT/binding['path']).read_bytes()+b'\n# changed source\n'
        binding['sha256']=hashlib.sha256(changed).hexdigest();bad.append(value)
        for value in bad:
            def read(path,*args,**kwargs):
                return json.dumps(value) if path==environment_path else original_read(path,*args,**kwargs)
            with self.subTest(entries=len(value['sources'])), patch.object(Path,'read_text',new=read), \
                    patch.object(Path,'read_bytes',side_effect=AssertionError('source read before original inventory gate')), \
                    self.assertRaisesRegex(ValueError,'original source inventory differs'):
                receiver.table()
        # Entry order is not part of the path/hash mapping identity.
        reversed_environment=copy.deepcopy(environment)
        reversed_environment['sources'].reverse()
        with patch.object(Path,'read_text',new=lambda path,*a,**k:json.dumps(reversed_environment)
                          if path==environment_path else original_read(path,*a,**k)):
            self.assertEqual(receiver.table(),derive(json.loads((ROOT/'results/durable-state-costs/measurements.json').read_text(encoding='utf-8'))))
        with patch.object(receiver,'verify_sources',side_effect=ValueError('original source inventory differs')), \
                patch.object(Path,'write_text') as write, self.assertRaises(ValueError):
            Path('owned-output.tex').write_text(receiver.table(),encoding='utf-8')
        write.assert_not_called()

if __name__=='__main__':unittest.main()
