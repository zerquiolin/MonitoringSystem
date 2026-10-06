"""Bounded HTTP assertions with the same authentication, verified CA and IP policy as probes."""
import asyncio,json,socket,ssl,urllib.parse,ipaddress
from pathlib import Path
import httpx
from configuration import validate_target
async def assertion(url,c,checks,secrets):
 headers=checks.get('headers',{}).copy()
 for name,ref in checks.get('headerSecretRefs',{}).items():headers[name]=(Path(secrets)/ref).read_text().strip()
 context=ssl.create_default_context(cafile=str(Path(secrets)/checks['caRef']) if checks.get('caRef') else None)
 async with asyncio.timeout(checks.get('timeoutSeconds',5)):
  async with httpx.AsyncClient(verify=context,trust_env=False,follow_redirects=False) as client:
   for n in range(6):
    await asyncio.to_thread(validate_target,url,c,True)
    original=urllib.parse.urlsplit(url)
    addresses=await asyncio.to_thread(socket.getaddrinfo,original.hostname,original.port or (443 if original.scheme=='https' else 80),socket.AF_INET,socket.SOCK_STREAM)
    nets=[ipaddress.ip_network(x) for x in c.get('network',{}).get('allowedCidrs',[])]
    for address in addresses:
     ip=ipaddress.ip_address(address[4][0])
     if str(ip) in ('169.254.169.254','100.100.100.200') or (ip.is_private or ip.is_loopback or ip.is_link_local) and not any(ip in net for net in nets):raise ValueError('Pinned destination IP not approved')
    pinned=urllib.parse.urlunsplit((original.scheme,addresses[0][4][0]+(':'+str(original.port) if original.port else ''),original.path,original.query,''))
    request=client.build_request('GET',pinned,headers={**headers,'Host':original.netloc});request.extensions['sni_hostname']=original.hostname
    response=await client.send(request,stream=True)
    try:
     if response.is_redirect:
      if not checks.get('followRedirects') or n==5:return False,'redirect_rejected'
      redirected=urllib.parse.urljoin(url,response.headers['location']);next_origin=urllib.parse.urlsplit(redirected)
      if (next_origin.scheme,next_origin.hostname,next_origin.port)!=(original.scheme,original.hostname,original.port):headers={}
      url=redirected;continue
     if response.status_code!=checks.get('expectedStatus',200):return False,'status_failed'
     data=bytearray()
     async for chunk in response.aiter_bytes():
      data.extend(chunk)
      if len(data)>262144:return False,'assertion_body_limit'
     contract=checks.get('bodyAssertion',{})
     if contract.get('mode')=='json-field':
      value=json.loads(data)
      for part in contract.get('field','status').split('.'):value=value[int(part)] if isinstance(value,list) else value[part]
      if value!=contract.get('equals','ok'):return False,'body_assertion_failed'
     elif contract.get('mode')=='regex':
      import re
      if not re.search(contract['pattern'],data.decode('utf-8',errors='replace')):return False,'body_assertion_failed'
     return True,'ok'
    finally:await response.aclose()
 return False,'redirect_limit'
