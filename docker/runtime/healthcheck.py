import urllib.request,sys
try:
 with urllib.request.urlopen('http://127.0.0.1:8000/ready',timeout=3) as response:sys.exit(0 if response.status==200 else 1)
except Exception:sys.exit(1)
