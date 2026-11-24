"""Negative evidence mutations for the independent physical execution checker."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
from tests.check_factored_execution import check_directory, canonical


def write(path,value): path.write_text(canonical(value)+'\n')


def mutate_database(path,table,function):
    with sqlite3.connect(path) as db:
        function(db)


def physical_identity(root):
    with sqlite3.connect(root/'owner-0000.sqlite') as db:
        value = json.loads(db.execute('SELECT identity FROM physical_identity').fetchone()[0])
        value['owner'] = 'another-physical-owner'
        db.execute('UPDATE physical_identity SET identity=?',(canonical(value),))


def effect_value(root):
    with sqlite3.connect(root/'owner-0000.sqlite') as db:
        rowid,raw = db.execute('SELECT rowid,output FROM schema_results LIMIT 1').fetchone()
        value = json.loads(raw); value['record']['value'] += 1
        db.execute('UPDATE schema_results SET output=? WHERE rowid=?',(canonical(value),rowid))


def missing_hop(root):
    with sqlite3.connect(root/'owner-0001.sqlite') as db:
        rowid = db.execute('SELECT rowid FROM schema_results LIMIT 1').fetchone()[0]
        db.execute('DELETE FROM schema_results WHERE rowid=?',(rowid,))


def missing_admission(root):
    path = root/'transport.jsonl'
    values = [json.loads(line) for line in path.read_text().splitlines()]
    removed = False
    kept = []
    for value in values:
        response = value.get('response') or {}
        if (not removed and value['event']=='rpc-result' and value['owner']=='owner-000' and
                response.get('status')=='held' and response['receipt']['origin']==0):
            removed = True
        else: kept.append(value)
    if not removed: raise ValueError('mutation needs a phase admission receipt')
    path.write_text(''.join(canonical(v)+'\n' for v in kept))


def conditional_source(root):
    with sqlite3.connect(root/'owner-0000.sqlite') as db:
        for ordinal,raw,response in db.execute('SELECT ordinal,request,response FROM schema_audit'):
            request = json.loads(raw)
            if request['op']=='install_if_current' and json.loads(response)['status']=='installed':
                request['expected_generation'] += 1
                db.execute('UPDATE schema_audit SET request=? WHERE ordinal=?',(canonical(request),ordinal))
                return
    raise ValueError('mutation needs an installed conditional request')


def historical_admission(root):
    session = json.loads((root/'requests.jsonl').read_text().splitlines()[0])['session']
    with sqlite3.connect(root/session) as db:
        value = json.loads(db.execute('SELECT payload FROM state').fetchone()[0])
        value['admission_certificates']['owner-000']['sequences']['0'] += 1
        db.execute('UPDATE state SET payload=?',(canonical(value),))


def target_generation(root):
    path = root/'result.json'; value = json.loads(path.read_text())
    value['rollout']['target_observation']['first']['owner-000']['generation'] += 1
    write(path,value)


def change_session(root, field):
    session = json.loads((root/'requests.jsonl').read_text().splitlines()[0])['session']
    with sqlite3.connect(root/session) as db:
        value = json.loads(db.execute('SELECT payload FROM state').fetchone()[0])
        if field == 'birth_token':
            value[field] = ('0' if value[field][0] != '0' else '1') + value[field][1:]
        elif field == 'manifest':
            value[field] += '-other'
        elif field == 'workflow':
            # Changing a hop name does not alter its owner or codec obligations.
            old = value[field][0]['id']
            value[field][0]['id'] = 'different-hop'
            for step in value[field]:
                step['parents'] = ['different-hop' if p == old else p for p in step['parents']]
        else:
            raise ValueError('unregistered session corruption')
        db.execute('UPDATE state SET payload=?',(canonical(value),))


def controls(source):
    source = Path(source)
    baseline = check_directory(source)
    mutations = [('physical identity substitution',physical_identity),
                 ('changed semantic effect value',effect_value),('missing finite-traversal hop',missing_hop),
                 ('missing all-owner admission receipt',missing_admission),
                 ('changed conditional source generation',conditional_source),
                 ('changed historical admission sequence',historical_admission),
                 ('mismatched target generation collections',target_generation),
                 ('changed session birth identity',lambda root:change_session(root,'birth_token')),
                 ('changed readable session label',lambda root:change_session(root,'manifest')),
                 ('changed workflow with equal codec obligations',lambda root:change_session(root,'workflow'))]
    rows = []
    for name,mutate in mutations:
        with tempfile.TemporaryDirectory(prefix='factored-checker-mutation-') as temporary:
            root = Path(temporary)/'case'; shutil.copytree(source,root)
            mutate(root)
            try: check_directory(root)
            except (ValueError,KeyError,IndexError,TypeError) as error:
                rows.append({'control':name,'rejected':True,'reason':str(error),'error_type':type(error).__name__})
            else: raise AssertionError('checker accepted altered evidence: '+name)
    return {'baseline':baseline,'controls':rows,'all_rejected':all(r['rejected'] for r in rows)}


if __name__=='__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('source',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args = parser.parse_args()
    result = controls(args.source)
    write(args.output,result)
    print(canonical({'all_rejected':result['all_rejected'],'controls':len(result['controls'])}))
