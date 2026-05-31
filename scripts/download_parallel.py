"""
FaceForensics++ PARALLEL Downloader — 8 simultaneous connections
=================================================================
Downloads 8 videos at once instead of 1 at a time → ~8x faster.
Resumes automatically: already downloaded files are skipped.

Config:
  COMPRESSION = "c23"  → ~60GB, H.264 high quality (same accuracy for training)
  COMPRESSION = "raw"  → ~300GB, lossless (larger files, same result)

Usage:
  python scripts/download_parallel.py
"""
import json
import ssl
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Lock

# ─── Config ──────────────────────────────────────────────────────────────────
DEST        = Path("E:/faceforensics_data")
COMPRESSION = "c23"   # c23=~60GB  |  raw=~300GB
WORKERS     = 8       # parallel connections
BASE_URL    = "http://kaldir.vc.in.tum.de/faceforensics/v3/"
FILELIST    = BASE_URL + "misc/filelist.json"
TIMEOUT     = 120     # seconds per connection

DATASETS = {
    "original":          "original_sequences/youtube",
    "Deepfakes":         "manipulated_sequences/Deepfakes",
    "Face2Face":         "manipulated_sequences/Face2Face",
    "FaceSwap":          "manipulated_sequences/FaceSwap",
    "NeuralTextures":    "manipulated_sequences/NeuralTextures",
    "DeepFakeDetection": "manipulated_sequences/DeepFakeDetection",
}

# ─── Globals ──────────────────────────────────────────────────────────────────
_lock = Lock()
_done = 0
_failed: list[str] = []
_t0 = time.time()


# ─── HTTP helper ──────────────────────────────────────────────────────────────

def _ctx() -> ssl.SSLContext:
    c = ssl._create_unverified_context()
    return c


def _get(url: str, timeout: int = 15) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 DeepGuard/1.0"})
    with urllib.request.urlopen(req, timeout=timeout, context=_ctx()) as r:
        return r.read()


# ─── Download one file ────────────────────────────────────────────────────────

def download_one(url: str, dest: Path) -> tuple[bool, str, int]:
    if dest.exists():
        return True, dest.name, int(dest.stat().st_size)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".tmp")
    try:
        data = _get(url, timeout=TIMEOUT)
        tmp.write_bytes(data)
        tmp.rename(dest)
        return True, dest.name, len(data)
    except Exception as e:
        tmp.unlink(missing_ok=True)
        return False, dest.name, 0


# ─── Progress ─────────────────────────────────────────────────────────────────

def _tick(total: int, size_bytes: int) -> None:
    global _done
    with _lock:
        _done += 1
        done = _done
    elapsed = time.time() - _t0
    rate = done / elapsed if elapsed > 0 else 0
    eta_h = (total - done) / rate / 3600 if rate > 0 else 0
    pct = done / total * 100
    bar = "#" * int(pct / 2) + "." * (50 - int(pct / 2))
    mb = size_bytes / 1e6
    print(
        f"\r[{bar}] {done}/{total}  {pct:.1f}%  "
        f"{rate*60:.1f} files/min  ETA {eta_h:.1f}h  last={mb:.0f}MB  ",
        end="", flush=True,
    )


# ─── Download one dataset ─────────────────────────────────────────────────────

def download_dataset(name: str, path: str, filelist: list[str]) -> None:
    global _done
    _done = 0

    url_base = f"{BASE_URL}{path}/{COMPRESSION}/videos/"
    out_dir  = DEST / path / COMPRESSION / "videos"
    out_dir.mkdir(parents=True, exist_ok=True)

    tasks     = [(url_base + f + ".mp4", out_dir / (f + ".mp4")) for f in filelist]
    remaining = [(u, d) for u, d in tasks if not d.exists()]
    already   = len(tasks) - len(remaining)

    print(f"\n{'='*65}")
    print(f"  Dataset : {name}")
    print(f"  Total   : {len(tasks)} videos  |  Already done: {already}")
    print(f"  To do   : {len(remaining)} files  |  Workers: {WORKERS}")
    print(f"  Output  : {out_dir}")
    print(f"{'='*65}")

    if not remaining:
        print("  All files already downloaded.")
        return

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(download_one, u, d): (u, d) for u, d in remaining}
        for fut in as_completed(futures):
            ok, fname, size = fut.result()
            if ok:
                _tick(len(remaining), size)
            else:
                _failed.append(fname)
                print(f"\n  FAILED: {fname}", flush=True)

    print(f"\n  Completed {len(remaining) - len(_failed)}/{len(remaining)}")


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    size_hint = "~60GB" if COMPRESSION == "c23" else "~300GB"
    print()
    print("=" * 65)
    print("  FaceForensics++ PARALLEL Downloader  (8 simultaneous)")
    print(f"  Compression : {COMPRESSION} ({size_hint})")
    print(f"  Destination : {DEST}")
    print(f"  Server      : kaldir.vc.in.tum.de (EU2)")
    print("=" * 65)
    print()
    print("  By continuing you agree to the FaceForensics Terms of Use:")
    print("  http://kaldir.vc.in.tum.de/faceforensics/webpage/FaceForensics_TOS.pdf")
    print()
    input("  Press Enter to start download, Ctrl+C to cancel...\n")

    # Fetch file list
    print("  Fetching file list from server...")
    try:
        pairs = json.loads(_get(FILELIST).decode("utf-8"))
    except Exception as e:
        print(f"  ERROR fetching file list: {e}")
        sys.exit(1)

    orig_files  = []
    for pair in pairs:
        orig_files += pair                             # forward + backward IDs

    manip_files = []
    for pair in pairs:
        manip_files.append("_".join(pair))
        manip_files.append("_".join(pair[::-1]))

    print(f"  File list: {len(orig_files)} original  |  {len(manip_files)} manipulation pairs")

    # Download datasets
    download_dataset("original",          DATASETS["original"],          orig_files)
    download_dataset("Deepfakes",         DATASETS["Deepfakes"],         manip_files)
    download_dataset("Face2Face",         DATASETS["Face2Face"],         manip_files)
    download_dataset("FaceSwap",          DATASETS["FaceSwap"],          manip_files)
    download_dataset("NeuralTextures",    DATASETS["NeuralTextures"],    manip_files)
    download_dataset("DeepFakeDetection", DATASETS["DeepFakeDetection"], manip_files)

    print()
    print("=" * 65)
    if _failed:
        print(f"  Done with {len(_failed)} failures. Re-run to retry.")
        for f in _failed[:10]:
            print(f"    {f}")
    else:
        print("  ALL FILES DOWNLOADED SUCCESSFULLY!")
    print()
    print("  Next steps:")
    print("    python scripts\\prepare_dataset.py --data_dir E:\\faceforensics_data --compression c23")
    print("    python scripts\\train_efficientnet_b4.py")
    print("=" * 65)


if __name__ == "__main__":
    main()
