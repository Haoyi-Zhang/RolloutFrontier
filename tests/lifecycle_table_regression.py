"""Explicit CI regression, separate from the retained five-test smoke denominator."""
import json
import copy
import contextlib
import hashlib
import io
from pathlib import Path
import runpy
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
import lifecycle_table as receiver
from lifecycle_table import ROOT,derive,verify_sources

def literal_fixture_counts(policy,padding,mismatch):
    """Independent static guards; never import/run a planner or a preimage.

    The four branch cells are (a0,b0/b1/b2) and (a1,b0). Greedy
    expands a first; mass prefers the three-cell b rectangle; training
    alternates a1/a0, so batch chooses the same rectangle as greedy.
    """
    guards={
        'fixed':{'0':({'a0'},),'1':({'b0'},)},
        'greedy':{'0':({'a0'},{'a1'}),'1':({'b0'},)},
        'mass':{'0':({'a0'},),'1':({'b0'},{'b1'},{'b2'})},
        'batch':{'0':({'a0'},{'a1'}),'1':({'b0'},)},
    }[policy]
    extra={f'unused{i:05d}' for i in range(padding)}
    current={'0':extra|{'a0'},'1':extra|{'b0'}}
    node,prefix=('1','b') if mismatch else ('0','a')
    counts=dict(installed=0,blocked=0,unchanged=0)
    for _ in range(12):
        for value in (1,0):
            target=extra|{prefix+str(value)}
            status=('unchanged' if current[node]==target else 'installed'
                    if any(term<=target for term in guards[node]) else 'blocked')
            counts[status]+=1
            if status=='installed':current[node]=target
    return counts

def synthetic_measurements():
    """Owned counts and invented timings, not a copy of measured results."""
    stages=('acquisition_ns','external_check_ns','origin_reopen_ns','owner_reopen_ns',
            'planning_ns','retirement_ns','shutdown_ns','startup_ns','updates_ns','use_ns')
    rows,groups=[],[]
    for padding in (0,11999):
        for mismatch in (False,True):
            for policy in ('fixed','greedy','mass','batch'):
                key=dict(padding_atoms=padding,mismatch=mismatch,policy=policy)
                counts=literal_fixture_counts(policy,padding,mismatch)
                times=[]
                for repeat in range(3):
                    timings={stage:100+repeat for stage in stages}
                    total=(len(groups)+1)*1_000_000+repeat*100_000+sum(timings.values())
                    times.append(total)
                    rows.append(dict(**key,**counts,repeat=repeat,proposals=24,
                                     safety_violations=0,refused_admissions=0,
                                     full_lifecycle_ns=total,timings_ns=timings))
                groups.append(dict(**key,**counts,full_lifecycle_median_ms=sorted(times)[1]/1e6))
    return dict(status='completed',repeats=3,trials=48,proposals_total=1152,rows=rows,groups=groups)

def coherent_mutations(original):
    data=copy.deepcopy(original)
    for collection in (data['rows'],data['groups']):
        for row in collection:
            if row['policy']=='fixed' and not row['mismatch']:
                row.update(installed=24,blocked=0,unchanged=0)
    yield 'fixed_both_payloads',data
    for schedule in (False,None):
        data=copy.deepcopy(original)
        for collection in (data['rows'],data['groups']):
            for row in collection:
                if row['policy'] in ('fixed','greedy') and (schedule is None or row['mismatch']==schedule):
                    row['policy']={'fixed':'greedy','greedy':'fixed'}[row['policy']]
        yield 'swapped_labels_'+str(schedule),data

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
        for padding in (0,11999):
            for mismatch in (False,True):
                for policy in ('fixed','greedy','mass','batch'):
                    data=copy.deepcopy(self.data)
                    group=next(g for g in data['groups'] if
                               (g['padding_atoms'],g['mismatch'],g['policy'])==(padding,mismatch,policy))
                    installed=(group['installed']+1)%25
                    outcomes=dict(installed=installed,blocked=24-installed,unchanged=0)
                    group.update(outcomes)
                    for row in data['rows']:
                        if (row['padding_atoms'],row['mismatch'],row['policy'])==(padding,mismatch,policy):
                            row.update(outcomes)
                    with self.subTest(payload=padding,mismatch=mismatch,policy=policy):
                        reject(data)
        # Match the generator's table-before-write expression without making
        # the standalone artifact depend on the sibling paper directory.
        data=copy.deepcopy(self.data);data['rows'][0]['installed']=False
        with patch.object(receiver,'table',side_effect=lambda:derive(data)), \
                patch.object(Path,'write_text') as write, self.assertRaises(ValueError):
            Path('owned-output.tex').write_text(receiver.table(),encoding='utf-8')
        write.assert_not_called()

class FixtureSemantics(unittest.TestCase):
    def test_literal_counts_for_every_policy_schedule_and_payload(self):
        expected={'fixed':((0,12,12),(0,12,12)),
                  'greedy':((24,0,0),(0,12,12)),
                  'mass':((0,12,12),(24,0,0)),
                  'batch':((24,0,0),(0,12,12))}
        for padding in (0,11999):
            for mismatch in (False,True):
                for policy in expected:
                    with self.subTest(padding=padding,mismatch=mismatch,policy=policy):
                        counts=literal_fixture_counts(policy,padding,mismatch)
                        self.assertEqual(tuple(counts.values()),expected[policy][mismatch])
        data=synthetic_measurements();before=copy.deepcopy(data)
        self.assertEqual(len(derive(data).splitlines()),5)
        self.assertEqual(data,before)

    def test_dual_payload_forgery_and_label_swaps(self):
        retained=json.loads((ROOT/'results/durable-state-costs/measurements.json').read_text(encoding='utf-8'))
        for name,original in (('retained',retained),('synthetic',synthetic_measurements())):
            for mutation,data in coherent_mutations(original):
                with self.subTest(dataset=name,mutation=mutation):
                    if mutation=='fixed_both_payloads':
                        self.assertEqual(sum(a!=b for a,b in zip(original['rows'],data['rows'])),6)
                        self.assertEqual(sum(a!=b for a,b in zip(original['groups'],data['groups'])),2)
                    with self.assertRaisesRegex(ValueError,'fixture outcome mismatch'):
                        derive(data)

    def test_all_policy_schedule_coherent_outcome_rewrites(self):
        original=synthetic_measurements()
        for mismatch in (False,True):
            for policy in ('fixed','greedy','mass','batch'):
                expected=tuple(literal_fixture_counts(policy,0,mismatch).values())
                for outcomes in ((0,12,12),(24,0,0),(0,0,24),(12,12,0)):
                    if outcomes==expected:continue
                    data=copy.deepcopy(original)
                    for collection in (data['rows'],data['groups']):
                        for row in collection:
                            if (row['mismatch'],row['policy'])==(mismatch,policy):
                                row.update(zip(('installed','blocked','unchanged'),outcomes))
                    with self.subTest(mismatch=mismatch,policy=policy,outcomes=outcomes), \
                            self.assertRaisesRegex(ValueError,'fixture outcome mismatch'):
                        derive(data)

    def test_consistent_synthetic_times_are_not_authenticated(self):
        # Count semantics and raw/summary consistency are not timing provenance.
        data=synthetic_measurements();before=derive(data)
        for row in data['rows']:row['full_lifecycle_ns']*=2
        for group in data['groups']:group['full_lifecycle_median_ms']*=2
        self.assertNotEqual(derive(data),before)


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
