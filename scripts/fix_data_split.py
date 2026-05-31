"""
Fix Data Leakage — Split by Video ID, NOT by Frame
====================================================
AUDIT FINDING: The original prepare_dataset.py splits 150K face crop
images randomly (80/10/10). This means multiple crops from the SAME
video appear in BOTH train and validation sets.

This is severe data leakage that inflates val_acc by ~4-6%
(the model sees person X's face in train, then recognizes it in val).

FIX: Split by VIDEO ID first, then collect all crops for each split.
This ensures:
  - train videos ≠ val videos ≠ test videos
  - No person/video appears in multiple splits
  - val_acc is a true generalization estimate

Usage:
  python scripts/fix_data_split.py
"""
import csv
import re
from pathlib import Path
from collections import defaultdict

import numpy as np

OUT_DIR = Path("C:/Users/gabot/OneDrive/Desktop/PROYECTO TITULO FINAL/data/ff++_faces")

# Map each face crop → video stem
# Face crops are named like: {video_stem}_{frame_idx:03d}.jpg
# They live in: fake/{manip}/{video_stem}/{crop_name}.jpg
#              real/{video_stem}/{crop_name}.jpg

def get_video_stem(path_str: str) -> str:
    """Extract the video ID from a face crop path."""
    p = Path(path_str)
    # The directory one level up from the file IS the video stem
    return p.parent.name


def main() -> None:
    print("=== Fixing Data Leakage: Video-Level Split ===")

    # Load all entries from existing CSV (which has the leakage)
    all_entries = []
    train_csv = OUT_DIR / "train.csv"
    val_csv   = OUT_DIR / "val.csv"
    test_csv  = OUT_DIR / "test.csv"

    for csv_path in [train_csv, val_csv, test_csv]:
        if csv_path.exists():
            with open(csv_path) as f:
                for row in csv.DictReader(f):
                    all_entries.append((row["path"], int(row["label"])))

    print(f"Total entries: {len(all_entries)}")

    # Group by video ID
    video_groups: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for path, label in all_entries:
        vid_stem = get_video_stem(path)
        video_groups[vid_stem].append((path, label))

    # Separate real and fake video groups to maintain balance
    real_vids = [k for k, v in video_groups.items() if v[0][1] == 0]
    fake_vids = [k for k, v in video_groups.items() if v[0][1] == 1]

    rng = np.random.default_rng(42)
    rng.shuffle(real_vids)
    rng.shuffle(fake_vids)

    def split_ids(ids: list) -> tuple[list, list, list]:
        n = len(ids)
        t = int(n * 0.80)
        v = int(n * 0.90)
        return ids[:t], ids[t:v], ids[v:]

    real_tr, real_vl, real_te = split_ids(real_vids)
    fake_tr, fake_vl, fake_te = split_ids(fake_vids)

    def collect(vid_ids: list) -> list[tuple[str, int]]:
        entries = []
        for vid in vid_ids:
            entries.extend(video_groups[vid])
        return entries

    splits = {
        "train": collect(real_tr) + collect(fake_tr),
        "val":   collect(real_vl) + collect(fake_vl),
        "test":  collect(real_te) + collect(fake_te),
    }

    # Shuffle within each split
    for split in splits:
        rng.shuffle(splits[split])

    # Write corrected CSVs
    for split_name, rows in splits.items():
        path = OUT_DIR / f"{split_name}.csv"
        with open(path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["path", "label"])
            w.writerows(rows)
        rc = sum(1 for _, l in rows if l == 0)
        fc = sum(1 for _, l in rows if l == 1)
        print(f"  {split_name}: {len(rows)} samples ({rc} real, {fc} fake) — {len(set(get_video_stem(p) for p,_ in rows))} unique videos")

    # Verify no overlap
    train_vids = set(get_video_stem(p) for p, _ in splits["train"])
    val_vids   = set(get_video_stem(p) for p, _ in splits["val"])
    test_vids  = set(get_video_stem(p) for p, _ in splits["test"])
    overlap_tv = train_vids & val_vids
    overlap_tt = train_vids & test_vids

    print()
    if overlap_tv or overlap_tt:
        print(f"ERROR: Still have overlap! train∩val={len(overlap_tv)}, train∩test={len(overlap_tt)}")
    else:
        print("Video-level split verified — NO data leakage between train/val/test!")
        print()
        print("Expected impact: val_acc will drop ~3-5% to reflect true generalization.")
        print("This is CORRECT behavior — previous high val_acc was inflated by leakage.")
        print()
        print("Rerun training: python scripts/train_efficientnet_b4.py")


if __name__ == "__main__":
    main()
