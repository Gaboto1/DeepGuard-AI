"""
Wrapper that auto-accepts FaceForensics++ TOS and starts the download.
Run: python scripts/start_download.py
"""
import sys
import os
import subprocess
from pathlib import Path

ROOT      = Path(__file__).parent.parent
PYTHON    = ROOT / "backend" / "venv" / "Scripts" / "python.exe"
FF_SCRIPT = ROOT / "scripts" / "faceforensics_download_v4.py"
DEST      = Path("E:/faceforensics_data")
LOG_FILE  = ROOT / "logs" / "ff++_download.log"

DEST.mkdir(parents=True, exist_ok=True)
LOG_FILE.parent.mkdir(exist_ok=True)

print("=" * 60)
print("  FaceForensics++ Download — DeepGuard AI")
print("=" * 60)
print(f"  Destination : {DEST}")
print(f"  Compression : raw (c0, lossless, ~300GB)")
print(f"  Dataset     : all (original + Deepfakes + Face2Face + FaceSwap + NeuralTextures)")
print(f"  Server      : EU2 (kaldir.vc.in.tum.de)")
print(f"  Log file    : {LOG_FILE}")
print()

args = [
    str(PYTHON), str(FF_SCRIPT),
    str(DEST),
    "-d", "all",
    "-c", "raw",
    "-t", "videos",
    "--server", "EU2",
]

print("Command:", " ".join(args))
print()

# Auto-accept TOS by providing empty input
proc = subprocess.Popen(
    args,
    stdin=subprocess.PIPE,
    stdout=sys.stdout,
    stderr=sys.stderr,
    text=True,
    bufsize=1,
)

# Send Enter to accept TOS
try:
    proc.stdin.write("\n")
    proc.stdin.flush()
    proc.stdin.close()
except Exception:
    pass

print("Download started. Press Ctrl+C to pause (downloads are resumable).")
print()

proc.wait()
print(f"\nDownload finished with return code: {proc.returncode}")
