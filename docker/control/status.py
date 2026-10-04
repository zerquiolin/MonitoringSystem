"""Three-valued quorum logic: known failures and successes are never averaged."""
def aggregate(instances,quorum):
 active=[(i,v) for i,v in instances if not i.get('draining')]
 if not active:return 'DRAINING',0
 values=[v for _,v in active];healthy=sum(v is True for v in values)
 if any(i.get('required',False) and v is False for i,v in active):return 'DOWN',healthy
 if any(i.get('required',False) and v is None for i,v in active):return 'UNKNOWN',healthy
 if healthy>=quorum:return ('UP' if all(v is True for v in values) else 'DEGRADED'),healthy
 if healthy+sum(v is None for v in values)<quorum:return 'DOWN',healthy
 return 'UNKNOWN',healthy

def project_state(values):
 if not values:return 'UNKNOWN'
 if 'DOWN' in values:return 'DOWN'
 if 'UNKNOWN' in values:return 'UNKNOWN'
 if all(v=='UP' for v in values):return 'UP'
 if all(v=='MAINTENANCE' for v in values):return 'MAINTENANCE'
 if all(v=='DRAINING' for v in values):return 'DRAINING'
 return 'DEGRADED'
