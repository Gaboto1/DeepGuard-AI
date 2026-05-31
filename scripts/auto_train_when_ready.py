import sys, time, subprocess
from pathlib import Path

OUT_DIR = Path(r"C:\Users\gabot\OneDrive\Desktop\PROYECTO TITULO FINAL\data\ff++_faces")
PYTHON  = r"C:\Users\gabot\OneDrive\Desktop\PROYECTO TITULO FINAL\backend\venv\Scripts\python.exe"
TRAIN_SCRIPT = r"C:\Users\gabot\OneDrive\Desktop\PROYECTO TITULO FINAL\scripts\train_efficientnet_b4.py"
INTEGRATE    = r"C:\Users\gabot\OneDrive\Desktop\PROYECTO TITULO FINAL\scripts\integrate_trained_model.py"

print("Waiting for face extraction to complete...")
while not (OUT_DIR / "train.csv").exists():
    real  = len(list((OUT_DIR / "real").rglob("*.jpg")))
    fake  = len(list((OUT_DIR / "fake").rglob("*.jpg")))
    print(f"\r  Real: {real} | Fake: {fake} | Total: {real+fake}  ", end="", flush=True)
    time.sleep(30)

print("\nExtraction done! Starting training...")
result = subprocess.run([PYTHON, TRAIN_SCRIPT], check=False)

if result.returncode == 0:
    best = Path(r"C:\Users\gabot\OneDrive\Desktop\PROYECTO TITULO FINAL\models\trained\efficientnet_b4_ffpp\efficientnet_b4_ffpp_best.pth")
    if best.exists():
        print("Training done! Integrating model...")
        subprocess.run([PYTHON, INTEGRATE, "--weights", str(best)], check=False)
        print("Integration complete. Restart backend to use the new model.")
    else:
        print("Training finished but no best model found.")
else:
    print("Training failed.")
