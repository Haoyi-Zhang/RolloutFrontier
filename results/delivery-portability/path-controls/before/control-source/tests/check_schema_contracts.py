"""Independent standard-library replay of schema probes and topology planning.

No protobuf, planner, codec, or producer module is imported. The checker decodes
retained descriptor fields, reconstructs documented JSON contracts, enumerates
literal safe phase products, and independently rebuilds all fixed-priority
paths and their minimum partitions. Topologies are registered finite cases,
not sampled deployment observations.
"""
from __future__ import annotations
import argparse
from collections import deque
from copy import deepcopy
from functools import lru_cache
import gzip
import hashlib
import itertools
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FAMILIES = {
 'enum-alias': (('legacy','accepting','emitting','current'),('old-name','new-name'),(0,0,1,1)),
 'field-key': (('legacy','accepting','emitting','current'),('old-key','new-key'),(0,0,1,1)),
 'field-addition': (('legacy','accepting','emitting'),('base','extended'),(0,0,1)),
 'integer-widening': (('legacy','accepting','emitting'),('narrow','wide'),(0,0,1)),
}
KEYS=('alpha','κλειδί','中文','emoji-λ','boundary')
NARROW=(-(1<<31),-1,0,1,(1<<31)-1)
WIDE=(-(1<<63),-(1<<40),*NARROW,1<<40,(1<<63)-1)
EDGES=tuple(itertools.permutations(range(3),2))
ORDERS=tuple(itertools.permutations(range(3)))
SOURCES={'src/schema_contracts.py','src/factored_planner.py','src/envelope.py',
         'src/controller.py','src/checker.py','src/goal_planner.py','tests/schema_contract_study.py'}


def require(condition,message):
 if not condition:raise ValueError(message)


def read(path):return json.loads(path.read_text())
def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def canonical(value):return json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'))
def equal(actual,expected,message):require(canonical(actual)==canonical(expected),message)


def protobuf_fields(data):
 """Read protobuf wire fields without importing the implementation under test."""
 result={};position=0
 def varint():
  nonlocal position
  value=0
  for shift in range(0,70,7):
   require(position<len(data),'truncated descriptor varint');byte=data[position];position+=1
   value|=(byte&127)<<shift
   if byte<128:return value
  raise ValueError('oversized descriptor varint')
 while position<len(data):
  key=varint();field,wire=key>>3,key&7;require(field>0,'descriptor field number')
  if wire==0:value=varint()
  elif wire==2:
   size=varint();require(position+size<=len(data),'truncated descriptor bytes')
   value=data[position:position+size];position+=size
  else:raise ValueError('unexpected descriptor wire type')
  result.setdefault(field,[]).append(value)
 return result


def text_field(fields,number,default=None):
 values=fields.get(number,[])
 require(len(values)<=1,'duplicate descriptor scalar')
 return values[0].decode('utf-8') if values else default


def descriptor_check(record,family,rank):
 require(record['rank']==rank,'descriptor rank')
 data=protobuf_fields(bytes.fromhex(record['serialized_hex']))
 equal((text_field(data,1),text_field(data,2),text_field(data,12)),
       ('contract.proto','schema','proto3'),'descriptor header')
 require(len(data.get(4,[]))==1,'descriptor message count')
 message=protobuf_fields(data[4][0]);equal(text_field(message,1),'Record','descriptor message')
 fields=[]
 for raw in message.get(2,[]):
  f=protobuf_fields(raw)
  fields.append((text_field(f,1),f.get(3),f.get(4),f.get(5),text_field(f,6),text_field(f,10)))
 expected=[('key',[1],[1],[9],None,None)]
 if family=='field-key':
  expected.append(('quantity' if rank==3 else 'count',[2],[1],[3],None,'count' if rank==0 else 'quantity'))
 else:expected.append(('value',[2],[1],[5 if family=='integer-widening' and rank==0 else 3],None,None))
 if family=='enum-alias':expected.append(('status',[3],[1],[14],'.schema.Status',None))
 if family=='field-addition' and rank>=1:expected.append(('tag',[3],[1],[9],None,None))
 equal(fields,expected,'descriptor fields differ from registered schema')
 if family=='enum-alias':
  require(len(data.get(5,[]))==1,'enum descriptor inventory')
  enum=protobuf_fields(data[5][0]);equal(text_field(enum,1),'Status','enum name')
  entries=[]
  for raw in enum[2]:
   value=protobuf_fields(raw);entries.append((text_field(value,1),value.get(2)))
  names=(('ACTIVE',),('ACTIVE','ENABLED'),('ENABLED','ACTIVE'),('ENABLED',))[rank]
  equal(entries,[('UNSPECIFIED',[0])]+[(name,[1])for name in names],'enum alias order')
  options=protobuf_fields(enum[3][0]);equal(options.get(2),[int(len(names)>1)],'enum alias option')
 else:require(not data.get(5),'unexpected enum')


def expected_payloads(family,rank):
 values=WIDE if family=='integer-widening' and rank==2 else NARROW
 result=[]
 for index,value in enumerate(values):
  payload={'key':KEYS[index%len(KEYS)],'value':value}
  if family=='enum-alias':payload['status']=1
  if family=='field-addition':payload['tag']='migrated-δ' if rank==2 else ''
  result.append(payload)
 return result


def expected_wire(family,rank,payload):
 wire={'key':payload['key']}
 if family=='field-key':wire['count' if rank<2 else 'quantity']=str(payload['value'])
 else:wire['value']=payload['value'] if family=='integer-widening' and rank==0 else str(payload['value'])
 if family=='enum-alias':wire['status']='ACTIVE' if rank<2 else 'ENABLED'
 if family=='field-addition' and rank==2:wire['tag']='migrated-δ'
 return canonical(wire)


def check_probes(families):
 equal([f['family']for f in families],list(FAMILIES),'schema family inventory')
 outputs={};wire_count=parse_count=failures=0
 for family in families:
  name=family['family'];programs,classes,emits=FAMILIES[name];size=len(programs)
  equal(family['programs'],programs,'program inventory');equal(family['classes'],classes,'wire classes')
  equal(family['emitted_classes'],[classes[i]for i in emits],'program emissions')
  equal(len(family['descriptors']),size,'descriptor inventory')
  for rank,record in enumerate(family['descriptors']):descriptor_check(record,name,rank)
  expected=[]
  for rank,program in enumerate(programs):
   for sample,payload in enumerate(expected_payloads(name,rank)):
    expected.append({'id':str(rank)+':'+str(sample),'rank':rank,'program':program,'class':classes[emits[rank]],
                     'input':payload,'wire':expected_wire(name,rank,payload)})
  equal(family['wires'],expected,'actual emitted wires differ from independently reconstructed format')
  require(len(family['parses'])==size*len(expected),'parser invocation inventory')
  accepted_classes=[];cursor=iter(family['parses'])
  for consumer in range(size):
   accepted={cls:True for cls in classes}
   for wire in expected:
    record=next(cursor);equal((record['consumer_rank'],record['consumer_program'],record['wire_id']),
                            (consumer,programs[consumer],wire['id']),'parser invocation identity')
    require(type(record['accepted'])is bool,'parser success type')
    if name in ('enum-alias','field-key'):
     good=(wire['class']==classes[0] and consumer<3)or(wire['class']==classes[1] and consumer>0)
    elif name=='field-addition':good=wire['class']==classes[0]or consumer>0
    else:good=consumer>0 or -(1<<31)<=wire['input']['value']<(1<<31)
    equal(record['accepted'],good,'parse outcome differs from registered contract')
    if good:equal(record['output'],wire['input'],'parsed semantic value differs')
    else:
     require(record['error_type']=='ParseError' and isinstance(record['error'],str)and record['error'],
             'missing actual parser failure');accepted[wire['class']]=False;failures+=1
    parse_count+=1
   accepted_classes.append([cls for cls in classes if accepted[cls]])
  profiles=[sorted(['program:'+name+':'+programs[i],'emit:'+classes[emits[i]],
                    *('accept:'+cls for cls in accepted_classes[i])])for i in range(size)]
  relation=[[int(classes[emits[u]]in accepted_classes[v])for v in range(size)]for u in range(size)]
  equal(family['accepted_classes'],accepted_classes,'accepted class summary')
  equal(family['profiles'],profiles,'profile contract differs from parse observations')
  equal(family['relation'],relation,'measured factor relation')
  outputs[name]=family;wire_count+=len(expected)
 return outputs,{'families':len(outputs),'encoded_wires':wire_count,'parser_invocations':parse_count,
                 'rejected_parser_invocations':failures,'distinct_relation_shapes':len({canonical(f['relation'])for f in families})}


def expected_context(family,mask):
 edges=[list(edge)for bit,edge in enumerate(EDGES)if mask>>bit&1];profiles=family['profiles']
 factors=[{'id':f'link-{u}-{v}','branches':[{str(u):['emit:'+cls],str(v):['accept:'+cls]}
                                         for cls in family['classes']]}for u,v in edges]
 used={x for edge in edges for x in edge}
 factors.extend({'id':'isolated-'+str(i),'branches':[{str(i):[]}]}for i in range(3)if i not in used)
 return {'id':family['family']+'-graph-'+str(mask),'family':family['family'],'graph_mask':mask,'edges':edges,
         'candidates':{str(i):profiles for i in range(3)},
         'transitions':{str(i):[{'source':a,'target':b}for a,b in zip(profiles,profiles[1:])]for i in range(3)},
         'factors':factors}


def check_contexts(contexts,families):
 expected=[expected_context(families[name],mask)for name in FAMILIES for mask in range(1,64)]
 equal(contexts,expected,'complete graph/context inventory')
 return {c['id']:c for c in contexts}


def truth(branches,state):return any(all(set(req)<=set(state[node])for node,req in b.items())for b in branches)
def antichain(terms):
 unique=sorted(set(tuple(sorted(set(t)))for t in terms))
 return [list(t)for t in unique if not any(set(s)<set(t)for s in unique)]


def recognition_check(certificate,ctx):
 require(certificate['recognized']is True and certificate['global_catalog_enumerated']is False,'recognition route')
 require(certificate['owners']==3,'recognized owner count')
 records=[];total=pair_total=0
 for factor in sorted(ctx['factors'],key=lambda f:f['id']):
  owners=sorted(factor['branches'][0]);shape=[len(ctx['candidates'][n])for n in owners]
  relation=[state for state in itertools.product(*(range(s)for s in shape))
            if truth(factor['branches'],{n:ctx['candidates'][n][r]for n,r in zip(owners,state)})]
  allowed=set(relation)
  for a in relation:
   for b in relation:require(tuple(max(x,y)for x,y in zip(a,b))in allowed,'factor not max-closed')
  axes=[]
  for state in relation:
   upper=[]
   for i,size in enumerate(shape):
    last=state[i]
    while last+1<size and state[:i]+(last+1,)+state[i+1:]in allowed:last+=1
    upper.append(last)
   axes.append({'source':list(state),'upper':upper})
  count=1
  for s in shape:count*=s
  pairs=len(relation)*(len(relation)+1)//2;total+=count;pair_total+=pairs
  records.append({'id':factor['id'],'owners':owners,'shape':shape,'catalog_placements':count,
                  'compatible_placements':len(relation),'checked_join_pairs':pairs,
                  'relation':[list(s)for s in relation],'axis_limits':axes})
 equal(certificate['factors'],records,'recognition certificate relation or axes differ')
 equal((certificate['checked_factor_placements'],certificate['checked_join_pairs']),(total,pair_total),'recognition counts')


@lru_cache(maxsize=128)
def literal_graph(relation,edges):
 size=len(relation)
 allowed=tuple(x for x in itertools.product(range(size),repeat=3)if all(relation[x[u]][x[v]]for u,v in edges))
 membership=set(allowed)
 @lru_cache(maxsize=None)
 def rectangle(a,b):
  return all(p in membership for p in itertools.product(*(range(x,y+1)for x,y in zip(a,b))))
 adjacency={a:[b for b in allowed if a!=b and all(x<=y for x,y in zip(a,b))and rectangle(a,b)]for a in allowed}
 costs={}
 for source in allowed:
  queue=deque([source]);distances={source:0}
  while queue:
   a=queue.popleft()
   for b in adjacency[a]:
    if b not in distances:distances[b]=distances[a]+1;queue.append(b)
  costs[source]=distances
 return allowed,membership,costs,rectangle


def ranked(state,profiles):
 require(isinstance(state,dict)and set(state)=={'0','1','2'},'physical state placement')
 try:return tuple(profiles.index(state[str(i)])for i in range(3))
 except ValueError:raise ValueError('physical profile absent from measured catalog')


def check_plan(answer,source,target,ctx,family,optimum,allowed):
 profiles=family['profiles']
 equal(ranked(answer['initial'],profiles),source,'plan initial differs')
 equal(ranked(answer['target'],profiles),target,'plan target differs')
 equal(answer['objective'],['fewest guard phases','fewest installations'],'plan objective')
 require(answer['status']in ('planned','unreachable'),'unexpected planning status')
 if optimum is None:
  require(answer['status']=='unreachable' and answer['cost']is None and answer['phases']==[],
          'false reachability answer');return
 require(answer['status']=='planned','false unreachable answer')
 expected={'phases':optimum,'installations':sum(b-a for a,b in zip(source,target)),'handoffs':max(0,optimum-1)}
 equal(answer['cost'],expected,'nonoptimal or inconsistent phase cost')
 require(all(type(v)is int for v in answer['cost'].values()),'integer plan costs')
 require(len(answer['phases'])==optimum,'phase inventory differs')
 state=source
 for phase in answer['phases']:
  equal(ranked(phase['source'],profiles),state,'disconnected phase')
  endpoint=ranked(phase['target'],profiles)
  require(any(a<b for a,b in zip(state,endpoint))and all(a<=b for a,b in zip(state,endpoint)),'empty or backward phase')
  require(all(x in allowed for x in itertools.product(*(range(a,b+1)for a,b in zip(state,endpoint)))),
          'unsafe literal product')
  require(set(phase['box'])==set(phase['local_paths'])=={'0','1','2'},'phase owner inventory')
  for i in range(3):
   node=str(i);terms=phase['box'][node]
   equal(terms,antichain(terms),'noncanonical positive guard')
   require(terms,'empty positive guard')
   equal(phase['local_paths'][node],profiles[state[i]:endpoint[i]+1],'invalid local path')
   require(all(any(set(term)<=set(p)for term in terms)for p in phase['local_paths'][node]),
           'guard excludes a visited physical profile')
  checks=[]
  for factor in sorted(ctx['factors'],key=lambda f:f['id']):
   owners=sorted(factor['branches'][0]);options={}
   for n in owners:
    relevant={a for b in factor['branches']for a in b[n]}
    options[n]=antichain([set(t)&relevant for t in phase['box'][n]])
   count=0
   for terms in itertools.product(*(options[n]for n in owners)):
    require(truth(factor['branches'],dict(zip(owners,terms))),'unsafe positive guard corner');count+=1
   checks.append({'id':factor['id'],'corners':count})
  if 'factor_checks'in phase:equal(phase['factor_checks'],checks,'factor checking counts')
  point=list(state)
  for step in phase['steps']:
   require(set(step)=={'node','support'} and step['node']in ('0','1','2'),'step schema')
   node=int(step['node']);new=profiles.index(step['support'])
   require(new==point[node]+1 and new<=endpoint[node],'step does not follow permitted local edge')
   point[node]=new;require(tuple(point)in allowed,'incompatible installation step')
  equal(point,endpoint,'phase endpoint not reached');state=endpoint
 equal(state,target,'target not reached')


def priority_path(source,target,order,allowed):
 if any(a>b for a,b in zip(source,target)):return None
 path=[source];point=source
 while point!=target:
  for i in order:
   if point[i]>=target[i]:continue
   next_point=point[:i]+(point[i]+1,)+point[i+1:]
   if next_point in allowed:path.append(next_point);point=next_point;break
  else:return None
 return path


def check_routes(routes,source,target,allowed,rectangle):
 require(len(routes)==6,'priority order inventory')
 costs=[]
 for order,route in zip(ORDERS,routes):
  equal(route['order'],order,'fixed owner priority')
  path=priority_path(source,target,order,allowed)
  if path is None:
   require(route['path']is None and route['phases']is None and route['cuts']is None,'unreachable priority path');costs.append(None);continue
  equal(route['path'],path,'priority shortest path differs')
  best=[0]
  for end in range(1,len(path)):
   best.append(1+min(best[begin]for begin in range(end)if rectangle(path[begin],path[end])))
  equal(route['phases'],best[-1],'partition is not optimal for fixed path')
  require(type(route['phases'])is int,'phase count type')
  cuts=route['cuts'];require(isinstance(cuts,list)and cuts and cuts[0]==0 and cuts[-1]==len(path)-1,'partition endpoints')
  require(all(type(v)is int for v in cuts)and all(a<b for a,b in zip(cuts,cuts[1:])),'partition cuts')
  require(len(cuts)-1==best[-1]and all(rectangle(path[a],path[b])for a,b in zip(cuts,cuts[1:])),'partition witness')
  costs.append(best[-1])
 return costs


def check_query(row,ctx,family,source,target,costs,allowed,rectangle):
 equal((row['context'],row['source'],row['target']),(ctx['id'],source,target),'complete ordered query inventory')
 optimum=costs[source].get(target)
 equal(row['answer']['schema'],'factored-chain-plan','factored result schema')
 check_plan(row['answer'],source,target,ctx,family,optimum,allowed)
 iterates=row['answer']['search']['rank_iterates']
 require(isinstance(iterates,list)and iterates,'missing ranked search trace')
 equal(iterates[0],source,'ranked search source')
 if optimum is not None:
  equal(iterates,[list(source)]+[list(ranked(p['target'],family['profiles']))
                                for p in row['answer']['phases']],'ranked search trace differs from phases')
 routes=check_routes(row['routes'],source,target,allowed,rectangle)
 require(all((v is None)==(optimum is None)for v in routes),'reachability differs across controls')
 return optimum,routes


def check(directory,corruption_controls=False):
 families,probes=check_probes(read(directory/'probes.json'))
 contexts=read(directory/'contexts.json');by_context=check_contexts(contexts,families)
 environment=read(directory/'environment.json')
 require(environment['owners']==3 and environment['protobuf']=='7.36.2','recorded runtime contract')
 equal(sorted(environment['source_sha256']),sorted(SOURCES),'measured source inventory')
 for name,expected in environment['source_sha256'].items():
  rel=Path(name);require(not rel.is_absolute()and '..'not in rel.parts,'unsafe source identity')
  require(digest(ROOT/rel)==expected and digest(directory/'sources'/rel)==expected,'measured source changed: '+name)
 groups={};full_goals=[];witness=None;total=0
 for name,family in families.items():
  group={'contexts':63,'queries':0,'no_op':0,'reachable_nontrivial':0,'unreachable':0,
         'exact_phases':0,'best_priority_phases':0,'best_priority_gap_goals':0,
         'priority_gaps':[0]*6,'priority_phases':[0]*6}
  with gzip.open(directory/(name+'.jsonl.gz'),'rt',encoding='utf-8')as stream:
   for ctx in [c for c in contexts if c['family']==name]:
    recognition_check(read(directory/'recognition'/(ctx['id']+'.json')),ctx)
    listed,allowed,costs,rectangle=literal_graph(tuple(tuple(r)for r in family['relation']),tuple(tuple(e)for e in ctx['edges']))
    for source in listed:
     for target in listed:
      line=stream.readline();require(bool(line),'missing query record')
      row=json.loads(line);optimum,routes=check_query(row,ctx,family,source,target,costs,allowed,rectangle)
      group['queries']+=1
      if optimum is None:group['unreachable']+=1
      elif source==target:group['no_op']+=1
      else:
       group['reachable_nontrivial']+=1;group['exact_phases']+=optimum
       group['best_priority_phases']+=min(routes)
       group['best_priority_gap_goals']+=min(routes)>optimum
       for i,value in enumerate(routes):group['priority_phases'][i]+=value;group['priority_gaps'][i]+=value>optimum
      if source==(0,0,0)and target==(len(family['profiles'])-1,)*3:
       full_goals.append({'context':ctx['id'],'family':name,'graph_mask':ctx['graph_mask'],'edges':ctx['edges'],
                          'exact_phases':optimum,'best_priority_phases':min(routes),'priority_phases':routes})
       if ctx['id']=='enum-alias-graph-25':witness=(row,ctx,family,source,target,costs,allowed,rectangle)
   require(not stream.readline(),'unexpected extra query record')
  groups[name]=group;total+=group['queries']
 inventory={'families':4,'contexts':252,'queries':total,'priority_orders':[list(o)for o in ORDERS]}
 equal(read(directory/'inventory.json'),inventory,'query inventory summary')
 require(total==186174,'registered complete query count')
 controls=read(directory/'frontier-cycle-controls.json')
 equal([c['context']for c in controls],['enum-alias-graph-25','field-key-graph-25'],'old frontier controls')
 for control in controls:
  ctx=by_context[control['context']];family=families[ctx['family']]
  listed,allowed,costs,rectangle=literal_graph(tuple(tuple(r)for r in family['relation']),tuple(tuple(e)for e in ctx['edges']))
  answer=control['answer'];source=(0,0,0);target=(3,3,3)
  equal({n:sorted(v)for n,v in answer['catalog'].items()},
        {n:sorted(v)for n,v in ctx['candidates'].items()},'frontier control catalog')
  equal({n:sorted(v,key=canonical)for n,v in answer['transitions'].items()},
        {n:sorted(v,key=canonical)for n,v in ctx['transitions'].items()},'frontier control transitions')
  check_plan(answer,source,target,ctx,family,3,allowed)
  require(len(answer['branches'])==8,'frontier control DNF expansion')
  for state in itertools.product(range(4),repeat=3):
   support={str(i):family['profiles'][state[i]]for i in range(3)}
   equal(truth(answer['branches'],support),state in allowed,'frontier control manifest differs')
 result={'status':'pass','probes':probes,'contexts':252,'queries':total,'groups':groups,
         'full_migrations':full_goals,'full_migration_gap_counts':{name:sum(r['family']==name and r['best_priority_phases']>r['exact_phases']for r in full_goals)for name in FAMILIES},
         'frontier_cycle_controls':len(controls),'independent_oracle_disagreements':0,
         'scope':'actual library probes; complete registered three-owner graph/goal census, not deployment prevalence'}
 if corruption_controls:result['corruption_controls']=negative_controls(directory,families,contexts,witness)
 return result


def negative_controls(directory,families,contexts,witness):
 reports=[]
 def rejects(name,operation):
  try:operation()
  except (ValueError,KeyError,IndexError,TypeError):reports.append({'name':name,'rejected':True})
  else:raise ValueError('negative control accepted: '+name)
 probes=read(directory/'probes.json');mutated=deepcopy(probes)
 successful=next(p for p in mutated[0]['parses']if p['accepted']);successful['output']['value']+=1
 rejects('changed parser output',lambda:check_probes(mutated))
 changed=deepcopy(probes);changed[0]['relation'][0][3]=1
 rejects('changed factor relation',lambda:check_probes(changed))
 rejects('missing graph context',lambda:check_contexts(contexts[:-1],families))
 row,ctx,family,source,target,costs,allowed,rectangle=witness
 for name,mutate in [
   ('wrong optimal phase cost',lambda r:r['answer']['cost'].__setitem__('phases',2)),
   ('changed ranked search trace',lambda r:r['answer']['search']['rank_iterates'].__setitem__(1,[3,3,3])),
   ('guard excludes phase source',lambda r:r['answer']['phases'][0]['box'].__setitem__('0',[['absent-contract']])),
   ('changed priority path',lambda r:r['routes'][0]['path'].__setitem__(1,[3,3,3])),
   ('missing partition boundary',lambda r:r['routes'][0]['cuts'].pop())]:
  sample=deepcopy(row);mutate(sample)
  rejects(name,lambda sample=sample:check_query(sample,ctx,family,source,target,costs,allowed,rectangle))
 return reports


if __name__=='__main__':
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--results',type=Path,required=True)
 parser.add_argument('--corruption-controls',action='store_true');args=parser.parse_args()
 print(json.dumps(check(args.results.resolve(),args.corruption_controls),sort_keys=True,indent=2))
