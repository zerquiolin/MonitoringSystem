from acceptance import ROOT,host,wait
import json,time
operator=(ROOT/'secrets/operator-token').read_text().strip();before={n['id'] for n in host('/control/notifications',operator)}
host('/',operator,'POST',{'role':'catalog','action':'fault','values':{'dependency':True}},port=4199)
try:
 opened=wait(lambda:next((r for r in host('/control/incidents',operator) if r['service']=='catalog-api' and r['recovered'] is None),None),60)
 firing=wait(lambda:next((n for n in host('/control/notifications',operator) if n['id'] not in before and n['status']=='firing'),None),90)
 host('/control/incidents/'+opened['id']+'/acknowledge',operator,'POST',{})
 host('/control/incidents/'+opened['id']+'/annotations',operator,'POST',{'note':'Automated local lifecycle verification'})
finally:host('/',operator,'POST',{'role':'catalog','action':'fault','values':{'dependency':False}},port=4199)
resolved=wait(lambda:next((n for n in host('/control/notifications',operator) if n['id'] not in before and n['status']=='resolved'),None),120)
incident=wait(lambda:next((r for r in host('/control/incidents',operator) if r['id']==opened['id'] and r['recovered']),None),60)
assert incident['acknowledged'] and incident['recoverySeconds']>0
(ROOT/'artifacts/alert-lifecycle.json').write_text(json.dumps({'status':'PASS','firingNotification':firing['id'],'resolvedNotification':resolved['id'],'incidentId':incident['id'],'acknowledgmentSeconds':incident['acknowledgmentSeconds'],'recoverySeconds':incident['recoverySeconds']},indent=2));print('PASS native Grafana firing/resolved delivery with separate acknowledged incident evidence')
