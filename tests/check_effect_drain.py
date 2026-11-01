"""Check all saved application/protocol states, without repeating the study."""
import gzip
import hashlib
import itertools
import json
from pathlib import Path
import sqlite3
import tempfile
import zipfile
ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'results/effect-drain'
def require(value,message):
    if not value:raise ValueError(message)
def verify():
    read=lambda name:json.loads((DATA/name).read_text(encoding='utf-8'))
    rows=read('rows.json');registration=read('registration.json');provenance=read('execution-provenance.json')
    expected=set(itertools.product(('predicate','epoch'),('commit','cancel'),('none','endpoint','coordinator'),(False,True)))
    require(len(rows)==24,'Incomplete lifecycle design')
    observed={(r['policy'],r['completion'],r['restart'],r['release_partition']) for r in rows}
    require(observed==expected,'Case design differs')
    snapshot=gzip.decompress((DATA/'execution-source.py.gz').read_bytes())
    require(hashlib.sha256(snapshot).hexdigest()==provenance['executed_driver_sha256'],'Historical source differs')
    for rel,digest in registration['source_bindings'].items():
        raw=snapshot if rel=='tests/effect_drain_study.py' else (ROOT/rel).read_bytes()
        require(hashlib.sha256(raw).hexdigest()==digest,'Executed input differs '+rel)
    identities=read('database-identities.json')
    with zipfile.ZipFile(DATA/'databases.zip') as z,tempfile.TemporaryDirectory() as temporary:
        require(len(z.namelist())==len(identities)==96 and set(z.namelist())==set(identities),'Snapshot inventory differs')
        for rel,identity in identities.items():
            raw=z.read(rel);require(len(raw)==identity['size'] and hashlib.sha256(raw).hexdigest()==identity['sha256'],'Snapshot bytes differ')
        for index,row in enumerate(rows):
            require(row['initial_retirement']=='draining' and row['incompatible_install_while_active']=='blocked','Guard did not protect active effect')
            require(row['new_work_rejected'] is True and row['stale_effect_rejected'] is True,'Effect authority not fenced')
            require(row['first_release']==('release-pending' if row['release_partition'] else 'retired') and row['final_release']=='retired','Incorrect release outcome')
            require(row['actual_stored_value']==('committed' if row['completion']=='commit' else None),'Unexpected application value')
            rel='case-'+str(index)+'/effects.sqlite';path=Path(temporary)/'effects.sqlite';path.write_bytes(z.read(rel))
            db=sqlite3.connect('file:'+path.as_posix()+'?mode=ro',uri=True)
            try:
                require(db.execute('SELECT phase FROM leases').fetchall()==[('closed',)],'Final lease is not fenced')
                require(db.execute('SELECT phase FROM operations').fetchall()==[('done' if row['completion']=='commit' else 'cancelled',)],'Recorded application operation differs')
                require(db.execute('SELECT value FROM effects').fetchall()==([('committed',)] if row['completion']=='commit' else []),'Actual database write differs')
            finally:db.close()
            for suffix in ('net/node-0.sqlite','net/node-1.sqlite','net/origin-0.sqlite'):
                path.write_bytes(z.read('case-'+str(index)+'/'+suffix))
                db=sqlite3.connect('file:'+path.as_posix()+'?mode=ro',uri=True)
                try:
                    states=db.execute('SELECT id,payload FROM state').fetchall()
                    require(len(states)==1 and states[0][0]==1,'Malformed final protocol singleton')
                    state=json.loads(states[0][1])
                    if 'origin' in suffix:
                        require(state['attempts']=={},'Origin retains an unfinished release')
                    else:
                        require(state['slots']=={} and state['floor'][0]>=1,'Owner still holds or can resurrect retired admission')
                        require(state['support']==(['b'] if 'node-0' in suffix else ['a','b']),'Final owner support differs')
                finally:db.close()
    return dict(status='PASS',lifecycles=24,database_snapshots=96,independent_performance_comparison_claimed=False)
if __name__=='__main__':print(json.dumps(verify()))
