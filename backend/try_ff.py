import urllib.request, ssl, time

url = "https://kaldir.vc.in.tum.de/faceforensics_download_v4.py"
dest = r"C:\Users\gabot\OneDrive\Desktop\PROYECTO TITULO FINAL\scripts\faceforensics_download_v4.py"

ctx = ssl._create_unverified_context()
print("Connecting...", flush=True)
try:
    with urllib.request.urlopen(url, timeout=45, context=ctx) as r:
        data = r.read()
    with open(dest, 'wb') as f:
        f.write(data)
    print(f"SUCCESS: Downloaded {len(data)//1024}KB to {dest}")
    # Show key parts
    lines = data.decode('utf-8','ignore').splitlines()
    for i,l in enumerate(lines[:30]): print(f"{i+1:3}: {l}")
except Exception as e:
    print(f"FAILED: {e}")
    print("The TUM server may be temporarily unavailable.")
    print("Try: 1) Check your VPN  2) Try again later  3) Contact ff@ondyari.de")
