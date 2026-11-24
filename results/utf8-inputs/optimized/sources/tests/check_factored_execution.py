"""Independent replay of factored physical execution and real schema effects.

This checker imports no controller, transport, session, planner, or application
implementation. Small factor corners and durable lifecycle transitions are
reconstructed directly. Saved protobuf descriptors execute the independent
wire-to-semantic checks. The planning oracle is a separate standard-library
implementation and is used only for finite local recognition certificates.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from itertools import product
import json
import hashlib
from pathlib import Path
import re
import sqlite3

from google.protobuf import descriptor_pool, message_factory, json_format
from tests.factored_planning_oracle import Oracle, canonical_terms


def canonical(value): return json.dumps(value,ensure_ascii=True,sort_keys=True,separators=(',',':'))


def require(value, reason):
    if not value: raise ValueError(reason)


def load(path): return json.loads(Path(path).read_text())


def records(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line]


def read_state(path):
    with sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True) as db:
        rows = db.execute('SELECT id,payload FROM state').fetchall()
    require(len(rows) == 1 and rows[0][0] == 1,'singleton durable state')
    return json.loads(rows[0][1])


def session_manifest(session):
    """Reconstruct the admission identity without importing the session runtime."""
    require(isinstance(session.get('birth_token'), str) and
            re.fullmatch(r'[0-9a-f]{32}', session['birth_token']) is not None,
            'missing or invalid session birth identity')
    require(isinstance(session.get('manifest'), str) and 1 <= len(session['manifest']) <= 128,
            'invalid readable session manifest')
    binding = {name: session[name] for name in
               ('birth_token', 'manifest', 'registry', 'window', 'workflow', 'family', 'codecs')}
    return session['manifest'] + ':session:' + hashlib.sha256(canonical(binding).encode()).hexdigest()


def check_plan(plan):
    oracle = Oracle(plan['factors'],plan['catalog'],plan['transitions'])
    oracle.check_recognition(plan['recognition'])
    require(plan['status'] == 'planned','execution needs a feasible plan')
    current, steps, corners = deepcopy(plan['initial']), 0, 0
    require(oracle.safe(oracle.state(current)),'unsafe initial physical placement')
    for phase in plan['phases']:
        require(phase['source'] == current,'phase source continuity')
        box, checks = phase['box'], []
        require(set(box) == set(current),'global guard owner inventory')
        for owner in current:
            require(canonical_terms(box[owner]) == box[owner],'nonminimal physical guard')
            path = phase['local_paths'][owner]
            require(path[0] == current[owner] and path[-1] == phase['target'][owner],'local path endpoints')
            edge_set = {(canonical(e['source']),canonical(e['target'])) for e in plan['transitions'][owner]}
            require(all((canonical(a),canonical(b)) in edge_set for a,b in zip(path,path[1:])),'local physical edge')
            require(all(any(set(term) <= set(p) for term in box[owner]) for p in path),'unguarded local path')
        for factor in plan['factors']:
            scope = sorted(factor['branches'][0])
            terms = {}
            for owner in scope:
                relevant = {a for b in factor['branches'] for a in b[owner]}
                terms[owner] = canonical_terms([list(set(term)&relevant) for term in box[owner]])
            count = 0
            for corner in product(*(terms[n] for n in scope)):
                placement = dict(zip(scope,map(set,corner)))
                require(any(all(set(req) <= placement[n] for n,req in branch.items())
                            for branch in factor['branches']),'unsafe factor corner')
                count += 1
            checks.append({'id':factor['id'],'corners':count}); corners += count
        require(phase['factor_checks'] == checks,'factor corner count')
        for step in phase['steps']:
            owner = step['node']
            require({'source':current[owner],'target':step['support']} in plan['transitions'][owner],
                    'step skips its directed edge')
            current[owner] = deepcopy(step['support'])
            require(oracle.safe(oracle.state(current)),'unsafe concrete physical prefix')
            steps += 1
        require(current == phase['target'],'phase endpoint not reached')
    require(current == plan['target'] and steps == plan['cost']['installations'],'incomplete physical witness')
    require(len(plan['phases']) == plan['cost']['phases'],'phase count')
    return {'owners':len(current),'factors':len(plan['factors']),'phases':len(plan['phases']),
            'installations':steps,'factor_corners':corners}


class WireOracle:
    def __init__(self, probe):
        self.family, self.probe = probe['family'],probe
        self.classes = {}
        for descriptor in probe['descriptors']:
            pool = descriptor_pool.DescriptorPool()
            pool.AddSerializedFile(bytes.fromhex(descriptor['serialized_hex']))
            self.classes[descriptor['rank']] = message_factory.GetMessageClass(pool.FindMessageTypeByName('schema.Record'))

    def decode(self, rank, wire, cls):
        raw = json.loads(wire)
        family = self.family
        if family == 'enum-alias': require(raw['status'] == {'old-name':'ACTIVE','new-name':'ENABLED'}[cls],'wire alias class')
        elif family == 'field-key':
            key = {'old-key':'count','new-key':'quantity'}[cls]
            require(key in raw and ('quantity' if key == 'count' else 'count') not in raw,'wire key class')
        elif family == 'field-addition':
            require(('tag' in raw) == (cls == 'extended'),'wire addition class')
            if cls == 'extended': require(raw['tag'] == 'migrated-δ','wire metadata policy')
        elif family == 'integer-widening':
            require(cls in {'narrow','wide'},'integer wire class')
            bound = 31 if cls == 'narrow' else 63
            require(-(1<<bound) <= int(raw['value']) < (1<<bound),'wire integer domain')
        message = self.classes[rank]()
        json_format.Parse(wire,message)
        field = 'quantity' if family == 'field-key' and rank == 3 else 'count' if family == 'field-key' else 'value'
        result = {'key':message.key,'value':getattr(message,field)}
        if family == 'enum-alias': result['status'] = message.status
        if family == 'field-addition': result['tag'] = message.tag if rank >= 1 else ''
        return result

    def effect(self, row):
        value,output,rank = row['input'],row['output'],row['rank']
        require(value['emit_class'] == self.probe['emitted_classes'][rank],'effect serializer binding')
        require(len(value['inputs']) == len(value['input_classes']),'effect fan-in')
        decoded = [self.decode(rank,w,c) for w,c in zip(value['inputs'],value['input_classes'])]
        if decoded:
            require(value['seed'] is None,'non-source seed')
            expected = decoded[0]
            def comparable(record):
                return {k:v for k,v in record.items() if k != 'tag'} if self.family == 'field-addition' else record
            require(all(comparable(v) == comparable(expected) for v in decoded),'join semantic disagreement')
        else: expected = deepcopy(value['seed'])
        if self.family == 'field-addition': expected['tag'] = 'migrated-δ' if rank == 2 else ''
        if self.family == 'integer-widening' and rank < 2:
            require(-(1<<31) <= expected['value'] < (1<<31),'narrow producer domain')
        require(output['record'] == expected,'effect semantic result')
        require(self.decode(rank,output['wire'],value['emit_class']) == expected,'effect wire round trip')
        return len(decoded)


def satisfies(hold,support):
    return any(set(term) <= set(support) for term in hold.get('options',[hold['requires']]))


def check_owner(path, owner, registry, probe):
    registered = registry['owners'][owner]
    with sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True) as db:
        actual = json.loads(db.execute('SELECT payload FROM state').fetchone()[0])
        identity_rows = db.execute('SELECT identity FROM physical_identity').fetchall()
        expected_identity = {'deployment':registry['deployment'],'owner':owner,'family':registered['family'],
                             'initial':registered['initial'],'catalog':registered['catalog'],'window':8,'policy':'predicate'}
        require(identity_rows == [(canonical(expected_identity),)],'physical owner identity/catalog')
        effects = {(origin,sequence,manifest,rid):{'input':json.loads(raw),'output':json.loads(out),'generation':generation,'rank':rank}
                   for origin,sequence,manifest,rid,raw,out,generation,rank in db.execute('SELECT * FROM schema_results')}
        audit = [(ordinal,json.loads(req),json.loads(ans),json.loads(profile))
                 for ordinal,req,ans,profile in db.execute('SELECT * FROM schema_audit ORDER BY ordinal')]
    wire = WireOracle(probe)
    parses = sum(wire.effect(row) for row in effects.values())
    state = {'node':0,'window':8,'policy':'predicate','generation':0,'support':deepcopy(registered['initial']),
             'floor':[0]*6,'slots':{},'catalog':{'0':{'node':0,'generation':0,'support':deepcopy(registered['initial'])}}}
    installed, concurrent, maximum, duplicate, history = [],0,0,0,{}
    def profile(): return {'node':0,'generation':state['generation'],'support':deepcopy(state['support'])}
    for index,(ordinal,request,response,observed) in enumerate(audit,1):
        require(ordinal == index,'owner audit gap')
        op = request['op']; before = profile(); status = response['status']
        if op in {'prepare','close'}:
            origin,sequence = request['origin'],request['sequence']
            key = str(origin)+':'+str(sequence)
            floor = state['floor'][origin]
            if sequence <= floor: expected = {'status':'closed'}
            elif sequence > floor+8: expected = {'status':'window'}
            elif op == 'close':
                state['slots'][key] = {'status':'closed'}
                while state['slots'].get(str(origin)+':'+str(floor+1)) == {'status':'closed'}:
                    del state['slots'][str(origin)+':'+str(floor+1)]; floor += 1
                state['floor'][origin] = floor
                expected = {'status':'closed','floor':floor}
            else:
                old = state['slots'].get(key)
                if old is not None:
                    if old['status'] == 'closed': expected = {'status':'closed'}
                    elif (old['manifest'] != request['manifest'] or old['requires'] != request['requires'] or
                          old.get('options') != request.get('options')): expected = {'status':'binding-conflict'}
                    else: expected = {'status':'held','receipt':old}
                elif not satisfies(request,state['support']):
                    expected = {'status':'missing','missing':sorted(set(request['requires'])-set(state['support'])),
                                'observed':profile()}
                else:
                    hold = {'status':'held','node':0,'origin':origin,'sequence':sequence,
                            'manifest':request['manifest'],'requires':request['requires'],
                            'observed_generation':state['generation']}
                    if 'options' in request: hold['options'] = request['options']
                    state['slots'][key] = deepcopy(hold)
                    expected = {'status':'held','receipt':hold}
            require(response == expected,'owner admission/retirement replay')
        elif op in {'install','install_if_current'}:
            support = request['support']
            require(support in registered['catalog'],'unregistered installed program')
            if op == 'install_if_current' and (request['expected_generation'] != state['generation'] or
                    request['expected_support'] != state['support']): expected = {'status':'stale','observed':profile()}
            elif support == state['support']: expected = {'status':'unchanged','observed':profile()}
            else:
                blocked = sorted(key for key,hold in state['slots'].items()
                                 if hold['status'] == 'held' and not satisfies(hold,support))
                if blocked: expected = {'status':'blocked','holds':blocked}
                else:
                    if any(h.get('origin') == 2 for h in state['slots'].values()): concurrent += 1
                    installed.append({'owner':owner,'ordinal':ordinal,'request':request,'before':before})
                    state['generation'] += 1; state['support'] = deepcopy(support)
                    state['catalog']['0'] = profile()
                    expected = {'status':'installed','observed':profile()}
            require(response == expected,'conditional installation replay')
        elif op == 'read': require(response == {'status':'observed','observed':profile()},'read replay')
        elif op == 'inspect': require(response == {'status':'state','state':state},'inspect replay')
        elif op == 'schema':
            key = str(request['origin'])+':'+str(request['sequence'])
            hold = state['slots'].get(key,{})
            required = {'emit:'+request['emit_class'],*('accept:'+v for v in request['input_classes'])}
            if status == 'applied':
                require(hold.get('status') == 'held' and hold['manifest'] == request['manifest'],'unretained application effect')
                require(all(required <= set(term) for term in hold.get('options',[hold['requires']])),'effect exceeds retained codec')
                require(required <= set(state['support']),'effect unsupported at serialization point')
                effect = effects[request['origin'],request['sequence'],request['manifest'],request['request_id']]
                expected_input = {name:request[name] for name in ('input_classes','emit_class','inputs','seed')}
                require(effect['input'] == expected_input and effect['output'] == response['output'],'deduplication binding')
                require(effect['generation'] == response['applied_generation'] and effect['rank'] == response['applied_rank'],
                        'effect receipt binding')
                if response['duplicate']:
                    duplicate += 1
                else:
                    require(effect['generation'] == state['generation'] and
                            registered['catalog'][effect['rank']] == state['support'],'effect applied under another program')
            else: require(status in {'not-authorized','codec-not-retained','unsupported-codec','request-conflict','invalid'},'schema outcome')
        else: raise ValueError('unrecognized owner operation in evidence: '+op)
        require(observed == profile(),'owner audit profile differs from replay')
        require(all(satisfies(h,state['support']) for h in state['slots'].values() if h['status']=='held'),
                'held owner obligation was invalidated')
        maximum = max(maximum,len(state['slots']))
        require(maximum <= 48,'physical owner slot bound')
        history[ordinal] = {'request':request,'response':response,'profile':observed}
    require(canonical(actual) == canonical(state),'durable physical state differs from audit replay')
    return {'state':actual,'effects':effects,'history':history,'installed':installed,'max_slots':maximum,
            'installations_with_application_holds':concurrent,'duplicate_receipts':duplicate,
            'parser_calls':parses,'audit_rows':len(audit)}


def check_directory(directory):
    directory = Path(directory)
    case, result, probe = load(directory/'case.json'),load(directory/'result.json'),load(directory/'schema-probe.json')
    registry,plan = case['registry'],case['plan']
    assurance = check_plan(plan)
    owners = sorted(registry['owners'])
    states = {owner:check_owner(directory/f'owner-{i:04d}.sqlite',owner,registry,probe) for i,owner in enumerate(owners)}
    all_events = []
    for name in ('transport.jsonl','coordinator-transport.jsonl'):
        if (directory/name).exists(): all_events.extend(records(directory/name))
    all_events.sort(key=lambda e:e['time_ns'])
    issued = {(e['pid'],e['call']):e for e in all_events if e['event']=='rpc-issued'}
    replies = [e for e in all_events if e['event']=='rpc-result']
    receipts, closes = {},{}
    for event in all_events:
        if event['event'] == 'rpc-result' and event.get('response',{}):
            response = event['response']; owner = event['owner']
            if response['status'] == 'held':
                receipt = response['receipt']
                key = (owner,receipt['origin'],receipt['sequence'])
                old = receipts.get(key)
                if old: require(old['receipt'] == receipt,'changed physical receipt binding')
                else: receipts[key] = {'receipt':receipt,'start':event['time_ns']}
        if event['event'] == 'rpc-issued' and event['request']['op'] == 'close':
            request = event['request']; key = (event['owner'],request['origin'],request['sequence'])
            closes[key] = min(closes.get(key,event['time_ns']),event['time_ns'])
    manifest = result['manifest']
    plan_digest = hashlib.sha256(canonical(plan).encode()).hexdigest()
    intervals = []
    for index,phase in enumerate(plan['phases']):
        holds = []
        for owner in owners:
            matching = [(key,value) for key,value in receipts.items() if key[0] == owner and
                        value['receipt']['manifest'] == manifest+':plan:'+plan_digest+':phase:'+str(index) and
                        value['receipt'].get('options') == phase['box'][owner]]
            require(len(matching) == 1,'all-owner phase admission evidence')
            key,value = matching[0]
            holds.append((value['start'],closes.get(key,float('inf'))))
        intervals.append((max(v[0] for v in holds),min(v[1] for v in holds)))
    relay = records(directory/'relay-events.jsonl')
    lost = {(e['owner'],e['response']['owner_order']):e for e in relay if e['event']=='reply-discarded-after-owner'}
    verified_installs = 0
    for owner,state in states.items():
        for installation in state['installed']:
            ordinal,request = installation['ordinal'],installation['request']
            require(request['op'] == 'install_if_current','unexpected uncoordinated mutation')
            matching = [e for e in replies if e['owner']==owner and e.get('owner_order')==ordinal and e['request']==request]
            if not matching and (owner,ordinal) in lost:
                matching = [e for e in replies if e['owner']==owner and e['request']==request and e['response'] is None]
            require(len(matching)==1,'installation transport/audit correlation')
            reply = matching[0]; call = issued[reply['pid'],reply['call']]
            require(any(start <= call['time_ns'] < reply['time_ns'] <= end for start,end in intervals),
                    'installation outside a confirmed global guard interval')
            verified_installs += 1
        require(state['state']['support'] == plan['target'][owner] and not state['state']['slots'],
                'target or owner cleanup incomplete')
    require(verified_installs == plan['cost']['installations'],'actual installation total differs')
    journal = read_state(directory/'rollout.sqlite')
    require(journal['plan_digest']==plan_digest,'global plan binding differs')
    require(journal['stage']=='complete' and journal['certificates']=={},'global job not complete')
    require(journal['acknowledged_installs']+journal['reconciled_steps']==verified_installs,'installation credit differs')
    require(result['rollout']['target_observation']['first']==result['rollout']['target_observation']['second'],
            'target generations were not stable across collections')
    completed = records(directory/'requests.jsonl')
    expected_effects = {owner:set() for owner in owners}
    seen_requests = set()
    checked_sessions = {}
    birth_tokens = set()
    for row in completed:
        rid,seed,output = row['request_id'],row['input'],row['output']
        session_path = directory/row['session']
        session = read_state(session_path)
        admission_manifest = session_manifest(session)
        if row['session'] not in checked_sessions:
            require(session['birth_token'] not in birth_tokens, 'different journals share a session birth identity')
            birth_tokens.add(session['birth_token'])
            require(session['registry'] == registry and session['workflow'] == case['workflow'] and
                    session['family'] == case['family'] and set(session['codecs']) == set(owners),
                    'application session differs from registered dataflow')
            admissions = session['admission_certificates']
            require(set(admissions)==set(owners),'historical all-owner session admission')
            bounds = []
            for admitted_owner,certificate in admissions.items():
                require(certificate['origin']==2 and certificate['manifest']==admission_manifest and
                        set(certificate['sequences'])=={'0'} and len(certificate['receipts'])==1,
                        'historical application certificate schema')
                key = (admitted_owner,certificate['origin'],certificate['sequences']['0'])
                retained = receipts[key]
                require(certificate['receipts'][0]==retained['receipt'] and
                        certificate['box']=={'0':retained['receipt']['options']},
                        'historical application receipt differs from transport')
                bounds.append((retained['start'],closes.get(key,float('inf'))))
            interval = (max(v[0] for v in bounds),min(v[1] for v in bounds))
            calls = [e for e in replies if e['request']['op']=='schema' and
                     e['request']['manifest']==admission_manifest and
                     e['request']['origin']==admissions[e['owner']]['origin'] and
                     e['request']['sequence']==admissions[e['owner']]['sequences']['0']]
            for reply in calls:
                call = issued[reply['pid'],reply['call']]
                require(interval[0] <= call['time_ns'] < reply['time_ns'] <= interval[1],
                        'dataflow call outside retained all-owner admission interval')
            checked_sessions[row['session']] = interval
        scoped_id = (canonical(session['admission_certificates']),rid)
        require(scoped_id not in seen_requests,'request ID repeated within its session')
        seen_requests.add(scoped_id)
        require(session['stage']=='retired' and session['certificates']=={},'application session did not drain')
        with sqlite3.connect(session_path.resolve().as_uri()+'?mode=ro',uri=True) as db:
            ledger = db.execute('SELECT input,status,output FROM requests WHERE request_id=?',(rid,)).fetchone()
        require(ledger == (canonical(seed),'complete',canonical(output)),'complete request ledger binding')
        steps = {s['id']:s for s in session['workflow']}
        require(set(output['steps'])==set(steps),'finite traversal lost or gained a hop')
        for step_id,step in steps.items():
            owner = step['owner']
            admission = session['admission_certificates'][owner]
            effect_id = (admission['origin'],admission['sequences']['0'],admission_manifest,rid+':'+step_id)
            require(effect_id not in expected_effects[owner],'duplicate physical hop identity')
            expected_effects[owner].add(effect_id)
            effect = states[owner]['effects'][effect_id]
            expected_input = {'input_classes':[session['codecs'][steps[p]['owner']] for p in step['parents']],
                'emit_class':session['codecs'][owner],
                'inputs':[output['steps'][p]['output']['wire'] for p in step['parents']],
                'seed':None if step['parents'] else seed}
            require(effect['input']==expected_input,'fan-out/join or per-hop request binding')
            require(effect['output']==output['steps'][step_id]['output'],'dataflow result differs from durable effect')
            expected = deepcopy(seed)
            if case['family']=='field-addition': expected['tag']='migrated-δ' if session['codecs'][owner]=='extended' else ''
            require(effect['output']['record']==expected,'end-to-end semantic content changed')
        parent_ids = {p for s in steps.values() for p in s['parents']}
        sinks = set(steps)-parent_ids
        require(set(output['records'])==sinks,'sink inventory')
        require(all(output['records'][s]==output['steps'][s]['output']['record'] for s in sinks),'sink output mismatch')
    for owner in owners:
        require(set(states[owner]['effects'])==expected_effects[owner],'unaccounted or missing physical effect')
    starts = [e for e in all_events if e['event']=='owner-start']
    first_processes = {owner:next(e['pid'] for e in starts if e['owner']==owner) for owner in owners}
    require(len(set(first_processes.values()))==len(owners),'owners did not run as distinct processes')
    isolation_checked = 0
    if result['kind'] == 'fault-cohort':
        isolation = load(directory/'session-isolation.json')
        require(isolation['before'] == isolation['after'], 'foreign journal changed retained owner authority')
        original = read_state(directory/'session-recovery.sqlite')
        require(isolation['pending_session']['birth_token'] == original['birth_token'] and
                isolation['pending_session']['stage'] == 'closing' and
                isolation['pending_requests_before'] == isolation['pending_requests_after'] == 1,
                'session-isolation pending-request denominator')
        active_manifest = session_manifest(isolation['pending_session'])
        for owner, state in isolation['before'].items():
            retained = [hold for hold in state['slots'].values() if hold['origin'] == 2]
            require(len(retained) == 1 and retained[0]['manifest'] == active_manifest and
                    retained[0]['status'] == 'held', 'pending request lost its session authority')
        require(set(isolation['attempts']) == {'fresh', 'precreated'}, 'session isolation control inventory')
        for kind, attempt in isolation['attempts'].items():
            foreign = read_state(directory/attempt['journal'])
            require(foreign['birth_token'] != original['birth_token'] and
                    foreign['manifest'] == original['manifest'] and
                    foreign['workflow'] == original['workflow'] and foreign['codecs'] == original['codecs'] and
                    foreign['stage'] == 'acquiring' and not foreign['certificates'] and
                    not foreign['admission_certificates'], 'foreign session isolation binding')
            require(attempt['rejected_attempts'] == 2 and
                    attempt['error_types'] == ['FactoredExecutionError', 'FactoredExecutionError'],
                    'foreign journal admission was not repeatedly rejected')
            isolation_checked += 1
    assurance.update({'checked':True,'deployment':'separate processes and TCP relays on one host',
        'bound_application_sessions':len(checked_sessions),'session_isolation_controls':isolation_checked,
        'complete_requests':len(completed),'durable_effects':sum(len(s['effects']) for s in states.values()),
        'parser_calls':sum(s['parser_calls'] for s in states.values()),
        'duplicate_receipts':sum(s['duplicate_receipts'] for s in states.values()),
        'installations_with_application_holds':sum(s['installations_with_application_holds'] for s in states.values()),
        'max_owner_slots':max(s['max_slots'] for s in states.values()),
        'owner_audit_rows':sum(s['audit_rows'] for s in states.values()),
        'relay_socket_accepts':sum(e['event']=='socket-accepted' for e in relay),
        'reply_cuts':sum(e['event']=='reply-discarded-after-owner' for e in relay),
        'cut_requests':sum(e['event']=='cut-closed-request' for e in relay)})
    return assurance


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('directory',type=Path)
    parser.add_argument('--output',type=Path)
    args = parser.parse_args()
    answer = check_directory(args.directory)
    if args.output: args.output.write_text(canonical(answer)+'\n')
    print(canonical(answer))
