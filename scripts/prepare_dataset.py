"""
FaceForensics++ Dataset Preparation — Optimized
=================================================
Extracts face crops from all videos for training.
MTCNN initialized ONCE (not per video) for maximum speed.

Usage:
  python scripts/prepare_dataset.py
  python scripts/prepare_dataset.py --data_dir E:/faceforensics_data --out_dir data/ff++_faces
"""
import argparse
import csv
import os
import time
from pathlib import Path

import cv2
import numpy as np
import torch
from PIL import Image
from tqdm import tqdm

# ─── Config ──────────────────────────────────────────────────────────────────
DATA_DIR    = Path("E:/faceforensics_data")
OUT_DIR     = Path("C:/Users/gabot/OneDrive/Desktop/PROYECTO TITULO FINAL/data/ff++_faces")
COMPRESSION = "c23"
FRAMES_PER_VIDEO = 30
FACE_SIZE   = 224

MANIPULATIONS = ["Deepfakes", "Face2Face", "FaceSwap", "NeuralTextures"]


# ─── Initialize MTCNN once globally ──────────────────────────────────────────

def init_detector():
    from facenet_pytorch import MTCNN
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Face detector: MTCNN on {device}")
    return MTCNN(
        keep_all=False, device=device,
        min_face_size=48,
        thresholds=[0.6, 0.7, 0.7],
        post_process=False,
        select_largest=True,
    )


# ─── Extract faces from one video ────────────────────────────────────────────

def extract_faces(video_path: Path, out_dir: Path, detector, n_frames: int = 30) -> list[str]:
    cap = cv2.VideoCapture(str(video_path))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if total == 0:
        cap.release()
        return []

    indices = np.linspace(0, total - 1, min(n_frames, total), dtype=int)
    frames_rgb = []
    for idx in indices:
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(idx))
        ok, frame = cap.read()
        if ok:
            frames_rgb.append(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    cap.release()

    if not frames_rgb:
        return []

    out_dir.mkdir(parents=True, exist_ok=True)
    stem = video_path.stem
    saved = []

    # Run MTCNN on all frames at once (batch mode)
    pil_frames = [Image.fromarray(f) for f in frames_rgb]
    try:
        boxes_list, probs_list = detector.detect(pil_frames)
    except Exception:
        boxes_list = [None] * len(pil_frames)
        probs_list = [None] * len(pil_frames)

    for frame_i, (pil_img, boxes, probs) in enumerate(zip(pil_frames, boxes_list, probs_list)):
        if boxes is None or len(boxes) == 0:
            continue
        # Select best (most confident or largest) face
        best_idx = 0
        if probs is not None and len(probs) > 0:
            best_idx = int(np.argmax([p if p is not None else 0 for p in probs]))

        box = boxes[best_idx]
        prob = probs[best_idx] if probs is not None else 1.0
        if prob is None or prob < 0.85:
            continue

        w_img, h_img = pil_img.size
        x1, y1, x2, y2 = [int(max(0, b)) for b in box]
        # Add 15% margin
        mx = int((x2 - x1) * 0.15)
        my = int((y2 - y1) * 0.15)
        x1 = max(0, x1 - mx); y1 = max(0, y1 - my)
        x2 = min(w_img, x2 + mx); y2 = min(h_img, y2 + my)
        if x2 <= x1 or y2 <= y1:
            continue

        face = pil_img.crop((x1, y1, x2, y2)).resize((FACE_SIZE, FACE_SIZE), Image.LANCZOS)
        fname = out_dir / f"{stem}_{frame_i:03d}.jpg"
        face.save(fname, "JPEG", quality=95)
        saved.append(str(fname))

    return saved


# ─── Main ─────────────────────────────────────────────────────────────────────

def main(data_dir: Path, out_dir: Path) -> None:
    t0 = time.time()
    out_dir.mkdir(parents=True, exist_ok=True)

    detector = init_detector()
    entries: list[tuple[str, int]] = []

    # ── Real videos ──────────────────────────────────────────────────────────
    real_dir = data_dir / "original_sequences" / "youtube" / COMPRESSION / "videos"
    real_vids = sorted(real_dir.glob("*.mp4")) if real_dir.exists() else []
    print(f"\nReal videos: {len(real_vids)}")

    real_out = out_dir / "real"
    for vid in tqdm(real_vids, desc="Real", unit="vid"):
        crops = extract_faces(vid, real_out / vid.stem, detector, FRAMES_PER_VIDEO)
        entries += [(c, 0) for c in crops]

    real_count = sum(1 for _, l in entries if l == 0)
    print(f"  Real face crops extracted: {real_count}")

    # ── Fake videos ──────────────────────────────────────────────────────────
    fake_out = out_dir / "fake"
    for manip in MANIPULATIONS:
        manip_dir = data_dir / "manipulated_sequences" / manip / COMPRESSION / "videos"
        vids = sorted(manip_dir.glob("*.mp4")) if manip_dir.exists() else []
        if not vids:
            print(f"\nSkipping {manip}: no videos found")
            continue

        print(f"\n{manip} videos: {len(vids)}")
        for vid in tqdm(vids, desc=manip, unit="vid"):
            crops = extract_faces(vid, fake_out / manip / vid.stem, detector, FRAMES_PER_VIDEO)
            entries += [(c, 1) for c in crops]

    fake_count = sum(1 for _, l in entries if l == 1)
    print(f"\n  Fake face crops extracted: {fake_count}")

    # ── Shuffle and split ─────────────────────────────────────────────────────
    rng = np.random.default_rng(42)
    idx = rng.permutation(len(entries)).tolist()
    entries = [entries[i] for i in idx]

    n = len(entries)
    t_end = int(n * 0.80)
    v_end = int(n * 0.90)

    splits = {
        "train": entries[:t_end],
        "val":   entries[t_end:v_end],
        "test":  entries[v_end:],
    }

    for split, rows in splits.items():
        path = out_dir / f"{split}.csv"
        with open(path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["path", "label"])
            w.writerows(rows)
        rc = sum(1 for _, l in rows if l == 0)
        fc = sum(1 for _, l in rows if l == 1)
        print(f"  {split}: {len(rows)} samples ({rc} real, {fc} fake)")

    elapsed = time.time() - t0
    print(f"\nDataset ready: {out_dir}")
    print(f"Total crops: {n} | Time: {elapsed/60:.1f} min")
    print("\nNext: python scripts\\train_efficientnet_b4.py")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data_dir", default=str(DATA_DIR))
    parser.add_argument("--out_dir",  default=str(OUT_DIR))
    args = parser.parse_args()
    main(Path(args.data_dir), Path(args.out_dir))
