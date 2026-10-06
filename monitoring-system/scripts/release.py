"""Create a portable source archive and checksum manifest; fail on private credential leaks."""
from pathlib import Path
import hashlib,json,zipfile,tarfile
ROOT=Path(__file__).resolve().parents[2];SYSTEM=ROOT/'monitoring-system';ART=SYSTEM/'artifacts'
private=[p.read_bytes().strip() for p in (SYSTEM/'secrets').iterdir() if p.is_file() and len(p.read_bytes().strip())>=16]
excluded={'.venv','node_modules','dist','secrets','generated','__pycache__','.git','.DS_Store'}
files=[]
for p in sorted(ROOT.rglob('*')):
 if not p.is_file() or any(part in excluded for part in p.relative_to(ROOT).parts):continue
 rel=p.relative_to(ROOT)
 if rel.parts[:2]==('monitoring-system','artifacts') and (p.name in ('delivery-manifest.json','monitoring-project-source.zip') or p.suffix not in ('.json','.log','.png','.tgz')):continue
 if p.suffix in ('.pyc','.sqlite','.db','.tar','.gz'):continue
 data=p.read_bytes()
 if any(secret in data for secret in private):raise SystemExit('Private credential detected in '+str(rel))
 files.append(p)
archive=ART/'monitoring-project-source.zip'
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as out:
 for p in files:out.write(p,Path('MonitoringSystem')/p.relative_to(ROOT))
def info(path):
 h=hashlib.sha256()
 with path.open('rb') as f:
  for block in iter(lambda:f.read(8*1024*1024),b''):h.update(block)
 return {'name':path.name,'bytes':path.stat().st_size,'sha256':h.hexdigest()}
sdk=ART/'portable-observability-sdk-1.0.0.tgz'
with tarfile.open(sdk) as tar:
 for member in tar:
  if member.isfile():
   data=tar.extractfile(member).read()
   if any(secret in data for secret in private):raise SystemExit('Private credential detected in SDK')
manifest={'scope':'Portable implementation and executed local fixtures; see monitoring-system/docs/acceptance.md for external deployment prerequisites.','sourceArchive':{**info(archive),'files':len(files),'privateCredentialScan':'passed'},'images':info(ART/'monitoring-images.tar.gz') if (ART/'monitoring-images.tar.gz').exists() else None,'sdk':info(sdk)}
(ART/'delivery-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n');print('Distributable archives and private credential scan passed.')
