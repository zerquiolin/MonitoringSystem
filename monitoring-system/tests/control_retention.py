from acceptance import ROOT,host,wait
import subprocess,json,time
operator=(ROOT/'secrets/operator-token').read_text().strip();before={i['id'] for i in host('/control/incidents',operator)};marker='retention-fixture-'+str(int(time.time()))
code='''import sqlite3,time
c=sqlite3.connect('/data/control/control.sqlite');old=time.time()-91*86400;marker=MARKER
c.execute('INSERT INTO observations VALUES(?,?,?,?,?,?,?,?)',(marker,marker,'fixture','health',old,old,0,'retention_fixture'))
c.execute('INSERT INTO service_samples VALUES(?,?,?,?,?)',(marker,old,'DOWN','retention_fixture',old+15))
c.execute('INSERT INTO job_runs VALUES(?,?,?,?,?,?,?)',(marker,marker,'fixture','completed',old-1,old,'retention_fixture'));c.commit()
'''.replace('MARKER',repr(marker))
subprocess.run(['docker','exec','portable-observability-monitoring-1','python','-c',code],check=True,capture_output=True)
def removed():
 code="import sqlite3;c=sqlite3.connect('/data/control/control.sqlite');print(sum(c.execute('SELECT count(*) FROM '+t+' WHERE '+k+'=?',("+repr(marker)+",)).fetchone()[0] for t,k in [('observations','check_id'),('service_samples','service_id'),('job_runs','run_id')]))"
 return subprocess.check_output(['docker','exec','portable-observability-monitoring-1','python','-c',code],text=True).strip()=='0'
wait(removed,30);assert before<={i['id'] for i in host('/control/incidents',operator)}
(ROOT/'artifacts/control-retention.json').write_text(json.dumps({'status':'PASS','expiredObservationTimelineJobRowsRemoved':True,'existingIncidentSummariesPreserved':True},indent=2));print('PASS actual control pruning preserves incident summaries')
