"""
Extract face crops from ONE manipulation type only.
Used to run Face2Face, FaceSwap, NeuralTextures in parallel
while Deepfakes is being processed by the main script.

Usage:
  python scripts/extract_one_type.py Face2Face
  python scripts/extract_one_type.py FaceSwap
  python scripts/extract_one_type.py NeuralTextures
"""
import sys
import time
import numpy as np
import cv2
import torch
from pathlib import Path
from PIL import Image
from tqdm import tqdm

MANIP_TYPE   = sys.argv[1] if len(sys.argv) > 1 else "Face2Face"
DATA_DIR     = Path("E:/faceforensics_data")
OUT_DIR      = Path("C:/Users/gabot/OneDrive/Desktop/PROYECTO TITULO FINAL/data/ff++_faces")
COMPRESSION  = "c23"
FRAMES_PER   = 30
FACE_SIZE    = 224

def init_mtcnn():
    from facenet_pytorch import MTCNN
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    return MTCNN(
        keep_all=False, device=device,
        min_face_size=48, thresholds=[0.6, 0.7, 0.7],
        post_process=False, select_largest=True,
    ), device

def extract(video_path, out_dir, detector, n_frames=30):
    cap = cv2.VideoCapture(str(video_path))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if total == 0:
        cap.release()
        return 0
    indices = np.linspace(0, total-1, min(n_frames, total), dtype=int)
    frames_rgb = []
    for idx in indices:
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(idx))
        ok, frame = cap.read()
        if ok:
            frames_rgb.append(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    cap.release()
    if not frames_rgb:
        return 0
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = video_path.stem
    pil_frames = [Image.fromarray(f) for f in frames_rgb]
    try:
        boxes_list, probs_list = detector.detect(pil_frames)
    except Exception:
        boxes_list = [None]*len(pil_frames)
        probs_list = [None]*len(pil_frames)
    count = 0
    for fi, (pil, boxes, probs) in enumerate(zip(pil_frames, boxes_list, probs_list)):
        if boxes is None or len(boxes) == 0:
            continue
        best = int(np.argmax([p if p is not None else 0 for p in probs])) if probs is not None else 0
        box = boxes[best]
        prob = probs[best] if probs is not None else 1.0
        if prob is None or prob < 0.85:
            continue
        w_i, h_i = pil.size
        x1,y1,x2,y2 = [int(max(0,b)) for b in box]
        mx=int((x2-x1)*0.15); my=int((y2-y1)*0.15)
        x1=max(0,x1-mx); y1=max(0,y1-my)
        x2=min(w_i,x2+mx); y2=min(h_i,y2+my)
        if x2<=x1 or y2<=y1:
            continue
        face = pil.crop((x1,y1,x2,y2)).resize((FACE_SIZE,FACE_SIZE), Image.LANCZOS)
        face.save(out_dir / f"{stem}_{fi:03d}.jpg", "JPEG", quality=95)
        count += 1
    return count

def main():
    print(f"\n{'='*50}")
    print(f"  Extracting: {MANIP_TYPE}")
    print(f"{'='*50}")

    vid_dir = DATA_DIR / "manipulated_sequences" / MANIP_TYPE / COMPRESSION / "videos"
    out_base = OUT_DIR / "fake" / MANIP_TYPE

    if not vid_dir.exists():
        print(f"ERROR: Not found: {vid_dir}")
        sys.exit(1)

    vids = sorted(vid_dir.glob("*.mp4"))
    print(f"  Videos: {len(vids)}")

    # Skip already extracted
    already_done = set(p.parent.name for p in out_base.rglob("*.jpg")) if out_base.exists() else set()
    remaining = [v for v in vids if v.stem not in already_done]
    print(f"  Already done: {len(already_done)} | Remaining: {len(remaining)}")

    detector, device = init_mtcnn()
    print(f"  MTCNN on: {device}")

    total_crops = 0
    t0 = time.time()
    for vid in tqdm(remaining, desc=MANIP_TYPE):
        n = extract(vid, out_base / vid.stem, detector, FRAMES_PER)
        total_crops += n

    elapsed = time.time() - t0
    print(f"\n  Done! {total_crops} crops in {elapsed/60:.1f} min")
    print(f"  Saved to: {out_base}")

if __name__ == "__main__":
    main()
