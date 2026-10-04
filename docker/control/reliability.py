"""Wall-clock reliability from bounded, durable observations, never extrapolated across gaps."""
from datetime import datetime
import math
from status import aggregate

STATES=('UP','DOWN','DEGRADED','UNKNOWN','MAINTENANCE','DRAINING')
def epoch(value):
 return datetime.fromisoformat(value.replace('Z','+00:00')).timestamp()
def initialize(db):
 db.executescript('''
 CREATE TABLE IF NOT EXISTS service_samples(service_id TEXT,observed REAL,state TEXT,reason TEXT,valid_until REAL,PRIMARY KEY(service_id,observed));
 CREATE INDEX IF NOT EXISTS service_sample_time ON service_samples(service_id,observed);
 CREATE TABLE IF NOT EXISTS instance_state(service_id TEXT,instance TEXT,state TEXT,reason TEXT,updated REAL,PRIMARY KEY(service_id,instance));
 CREATE TABLE IF NOT EXISTS incident_annotations(id TEXT PRIMARY KEY,incident_id TEXT,received REAL,note TEXT);
 CREATE TABLE IF NOT EXISTS maintenance_silences(policy_id TEXT PRIMARY KEY,silence_id TEXT,service_id TEXT);
 CREATE TABLE IF NOT EXISTS token_revocations(digest TEXT PRIMARY KEY,received REAL);
 INSERT OR IGNORE INTO migrations VALUES(2,strftime('%s','now'));
 ''')
 db.commit()
def record(db,identity,state,reason,now,valid_for=15):
 db.execute('INSERT OR IGNORE INTO service_samples VALUES(?,?,?,?,?)',(identity,now,state,reason,now+valid_for))
def segments(db,identity,start,end):
 rows=list(db.execute('SELECT observed,state,valid_until FROM service_samples WHERE service_id=? AND observed>? AND observed<? ORDER BY observed',(identity,start,end)))
 previous=db.execute('SELECT observed,state,valid_until FROM service_samples WHERE service_id=? AND observed<=? ORDER BY observed DESC LIMIT 1',(identity,start)).fetchone()
 if previous:rows.insert(0,previous)
 cursor=start
 for n,row in enumerate(rows):
  t,state,valid=row;left=max(start,t);right=min(end,valid,rows[n+1][0] if n+1<len(rows) else end)
  if left>cursor:yield cursor,left,'UNKNOWN'
  if right>left:yield left,right,state;cursor=right
 if cursor<end:yield cursor,end,'UNKNOWN'
def maintenance(s,start,end):
 boundaries={start,end}
 intervals=[]
 for m in s.get('maintenance',[]):
  a,b=max(start,epoch(m['start'])),min(end,epoch(m['end']))
  if b>a:intervals.append((a,b,m.get('excludeFromSlo',True)));boundaries.update((a,b))
 return intervals,sorted(boundaries)
def duration_report(db,s,identity,start,end):
 totals={state:0.0 for state in STATES};excluded=0.0;maintenance_seconds=0.0
 intervals,bounds=maintenance(s,start,end)
 for a,b,state in segments(db,identity,start,end):
  cuts=[a]+[x for x in bounds if a<x<b]+[b]
  for left,right in zip(cuts,cuts[1:]):
   span=right-left;active=[m for m in intervals if m[0]<=left<m[1]]
   if active:maintenance_seconds+=span
   if any(m[2] for m in active):excluded+=span;continue
   totals[state if state in totals else 'UNKNOWN']+=span
 eligible=max(0,end-start-excluded);known=totals['UP']+totals['DEGRADED']+totals['DOWN']
 availability=(totals['UP']+totals['DEGRADED'])/known if known else None
 target=s.get('objectives',{}).get('probeAvailability',s.get('objectives',{}).get('workerReliability',{})).get('target',.999)
 budget=known*(1-target);burn=totals['DOWN']/budget if budget>0 else None
 incidents=[dict(r) for r in db.execute('SELECT * FROM incidents WHERE service_id=? AND opened<? AND (recovered IS NULL OR recovered>?)',(identity,end,start))]
 incidents=[i for i in incidents if i.get('closed') is None or i['closed']>start]
 recovered=[i for i in incidents if i['recovered'] is not None and start<=i['recovered']<=end]
 ack=[i['acknowledged']-i['opened'] for i in incidents if i['acknowledged'] is not None and start<=i['acknowledged']<=end]
 first=db.execute('SELECT min(observed) FROM service_samples WHERE service_id=?',(identity,)).fetchone()[0]
 coverage=known/eligible if eligible else None
 return {'project':s['project'],'service':s['service'],'environment':s['environment'],
  'from':start,'to':end,'windowSeconds':end-start,'eligibleSeconds':eligible,
  'uptimeSeconds':totals['UP']+totals['DEGRADED'],'downtimeSeconds':totals['DOWN'],
  'degradedSeconds':totals['DEGRADED'],'unknownSeconds':totals['UNKNOWN'],
  'drainingSeconds':totals['DRAINING'],'maintenanceSeconds':maintenance_seconds,'excludedMaintenanceSeconds':excluded,
  'availability':availability,'coverage':coverage,'target':target,'errorBudgetSeconds':budget,
  'errorBudgetRemainingSeconds':None if budget==0 else max(0,budget-totals['DOWN']),
  'errorBudgetConsumed':burn,'incidentCount':len(incidents),'activeIncidents':sum(i['opened']<=end and ((i['recovered'] is None or i['recovered']>end) and (i.get('closed') is None or i['closed']>end)) for i in incidents),
  'mttrSeconds':sum(i['recovered']-i['opened'] for i in recovered)/len(recovered) if recovered else None,
  'meanAcknowledgmentSeconds':sum(ack)/len(ack) if ack else None,
  'compliance':'INSUFFICIENT_DATA' if coverage is None or coverage<s.get('objectives',{}).get('probeAvailability',{}).get('minimumCoverage',.95) or known<10 else 'MET' if availability>=target else 'MISSED',
  'partialWindow':first is None or first>start,
  'definition':'Observed wall-clock estimate; DEGRADED meets service quorum and is available. Stale/missing evidence is UNKNOWN. Configured maintenance exclusion is explicit. MTTR is mean confirmed recovery time from detection for incidents resolved in range.'}
def finite(value):return value if isinstance(value,(int,float)) and math.isfinite(value) else None

def backfill(db,config,identity_fn,now):
 """Reconstruct aggregate historical state only from persisted normalized evidence.
 One-second receipt buckets join health/readiness collected in the same evaluator run.
 This recovers old demo history, preserving stale gaps and whole-instance quorum.
 """
 if db.execute('SELECT 1 FROM migrations WHERE version=3').fetchone():return
 for s in config['services']:
  identity=identity_fn(s);first=db.execute('SELECT min(observed) FROM service_samples WHERE service_id=?',(identity,)).fetchone()[0] or now
  rows=db.execute('SELECT * FROM observations WHERE service_id=? AND received<? ORDER BY received',(identity,first)).fetchall()
  latest={};groups={}
  for row in rows:groups.setdefault(int(row['received']),[]).append(row)
  for received,evidence in groups.items():
   for row in evidence:latest[(row['instance'],row['kind'])]=row
   values=[];required_failed=False;reasons=[]
   for i in s['instances']:
    if i.get('draining'):continue
    keys=[k for k,url in [('health','healthUrl'),('ready','readyUrl'),('tcp','tcpUrl'),('dns','dnsUrl')] if url in i] if s['kind'] in ('http','external') else ['worker']
    checks=[]
    for k in keys:
     row=latest.get((i['id'],k));ttl=s.get('checks',{}).get('intervalSeconds',15)*2+5
     value=None if row is None or row['success'] is None or received-row['observed']>ttl else bool(row['success'])
     checks.append(value)
     if row and value is False:reasons.append(row['reason'])
    value=False if False in checks else None if not checks or None in checks else True;values.append((i,value))
    if i.get('required',False) and value is False:required_failed=True
   state,healthy=aggregate(values,s.get('quorum',1))
   record(db,identity,state,reasons[0] if reasons else 'historical_observations',received,15)
 db.execute('INSERT INTO migrations VALUES(3,?)',(now,));db.commit()

def eligible_ranges(s,start,end):
 """Disjoint, known policy windows excluding maintenance once, including overlaps."""
 intervals,bounds=maintenance(s,start,end)
 return [(a,b) for a,b in zip(bounds,bounds[1:]) if not any(x<=a<y and exclude for x,y,exclude in intervals)]
