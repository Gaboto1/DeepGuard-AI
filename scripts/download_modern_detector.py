"""
Advanced GenAI Detector v3 — CLIP ViT-L/14 + Linear Probe
===========================================================
Entrena el probe en el benchmark MASIVO (512 imágenes) y evalúa
en el Golden Set (20 imágenes completamente independientes).
Esto garantiza que el F1 reportado es de generalización real.

Metodología: UniversalFakeDetect (Ojha et al. 2023)
  - Backbone: CLIP ViT-L/14 (openai/clip-vit-large-patch14, ~900MB)
  - Clasificador: LogisticRegression calibrada con Temperature Scaling
  - Split: Train=massive benchmark, Eval=golden set (sin solapamiento)

Output:
  models/advanced_detector/best_model_config.json
  models/advanced_detector/clip_probe.joblib
"""
import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import torch
from PIL import Image
from loguru import logger

ROOT   = Path(__file__).parent.parent
MODELS = ROOT / "models" / "advanced_detector"
MODELS.mkdir(parents=True, exist_ok=True)

os.environ["TRANSFORMERS_CACHE"]              = str(ROOT / "models")
os.environ["HF_HOME"]                         = str(ROOT / "models")
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
CLIP_ID = "openai/clip-vit-large-patch14"


# ─── Data loaders ─────────────────────────────────────────────────────────────

def load_manifest(json_path: Path) -> tuple[list, list]:
    """Load labeled images from any manifest, fixing the 0==falsy bug."""
    if not json_path.exists():
        return [], []
    with open(json_path) as f:
        manifest = json.load(f)
    paths, labels = [], []
    for e in manifest:
        lbl = e.get("expected_label")
        if lbl is None:
            lbl = e.get("label")
        if lbl is None:
            continue
        p = ROOT / e["path"]
        if p.exists():
            paths.append(p)
            labels.append(int(lbl))
    return paths, labels


def load_train_data():
    """Benchmark masivo para training (512 imgs)."""
    p, l = load_manifest(ROOT / "tests" / "benchmark_massive" / "manifest.json")
    logger.info(f"Train (massive): {len(p)} imgs ({l.count(0)} real, {l.count(1)} IA)")
    return p, l


def load_eval_data():
    """Golden set para evaluación (20 imgs independientes)."""
    p, l = load_manifest(ROOT / "tests" / "golden_set" / "manifest.json")
    logger.info(f"Eval (golden):   {len(p)} imgs ({l.count(0)} real, {l.count(1)} IA)")
    return p, l


# ─── CLIP feature extraction ──────────────────────────────────────────────────

def load_clip():
    from transformers import CLIPModel, CLIPProcessor
    logger.info(f"Cargando {CLIP_ID}...")
    model = CLIPModel.from_pretrained(
        CLIP_ID, cache_dir=str(ROOT/"models"),
        torch_dtype=torch.float16 if DEVICE.type=="cuda" else torch.float32,
    )
    proc = CLIPProcessor.from_pretrained(CLIP_ID, cache_dir=str(ROOT/"models"))
    model.to(DEVICE).eval()
    logger.success(f"  CLIP ViT-L/14 cargado en {DEVICE}")
    return model, proc


def extract_features(clip_model, clip_proc, paths: list, batch_size: int = 16) -> np.ndarray:
    """Extrae embeddings L2-normalizados usando vision_model.pooler_output."""
    features = []
    n = len(paths)
    t0 = time.time()
    for start in range(0, n, batch_size):
        batch_paths = paths[start:start+batch_size]
        imgs = [Image.open(p).convert("RGB") for p in batch_paths]
        inp  = clip_proc(images=imgs, return_tensors="pt", padding=True)
        px   = inp["pixel_values"].to(DEVICE)
        if DEVICE.type == "cuda":
            px = px.half()
        with torch.no_grad():
            out  = clip_model.vision_model(pixel_values=px)
            feat = out.pooler_output.float()
            feat = feat / feat.norm(dim=-1, keepdim=True)
        features.append(feat.cpu().numpy())
        done = min(start + batch_size, n)
        if done % 64 == 0 or done == n:
            elapsed = time.time() - t0
            logger.info(f"  {done}/{n} imgs | {elapsed:.1f}s")
    return np.vstack(features)


# ─── Métricas ─────────────────────────────────────────────────────────────────

def compute_metrics(y_true, y_score, threshold=0.50):
    from sklearn.metrics import roc_auc_score, f1_score, brier_score_loss
    y_t = np.array(y_true); y_s = np.array(y_score)
    y_p = (y_s >= threshold).astype(int)
    tp  = int(((y_p==1)&(y_t==1)).sum())
    tn  = int(((y_p==0)&(y_t==0)).sum())
    fp  = int(((y_p==1)&(y_t==0)).sum())
    fn  = int(((y_p==0)&(y_t==1)).sum())
    ece = sum(
        (((y_s>=i/10)&(y_s<(i+1)/10)).sum()/len(y_t)) *
        abs(float(y_s[(y_s>=i/10)&(y_s<(i+1)/10)].mean()) -
            float(y_t[(y_s>=i/10)&(y_s<(i+1)/10)].mean()))
        for i in range(10) if ((y_s>=i/10)&(y_s<(i+1)/10)).sum() > 0
    )
    return {
        "f1":      round(float(f1_score(y_t, y_p, zero_division=0)), 4),
        "roc_auc": round(float(roc_auc_score(y_t, y_s)) if len(np.unique(y_t)) > 1 else 0.5, 4),
        "brier":   round(float(brier_score_loss(y_t, y_s)), 4),
        "ece":     round(ece, 4),
        "fpr":     round(fp/max(1,fp+tn), 4),
        "fnr":     round(fn/max(1,fn+tp), 4),
        "tp": tp, "tn": tn, "fp": fp, "fn": fn,
    }


# ─── Train CLIP probe ─────────────────────────────────────────────────────────

def train_probe(X_train: np.ndarray, y_train: np.ndarray) -> tuple:
    """Entrena LogisticRegression con búsqueda de C y Temperature Scaling."""
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import StratifiedKFold, cross_val_score
    from scipy.optimize import minimize_scalar

    best_c, best_cv = 0.1, 0.0
    for c in [0.001, 0.005, 0.01, 0.05, 0.1, 0.5]:
        clf_tmp = LogisticRegression(C=c, max_iter=3000, random_state=42)
        n_splits = min(5, sum(y_train), len(y_train) - sum(y_train))
        if n_splits < 2:
            continue
        cv = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=42)
        s  = cross_val_score(clf_tmp, X_train, y_train, cv=cv, scoring="f1").mean()
        if s > best_cv:
            best_cv, best_c = s, c
    logger.info(f"  Mejor C={best_c} (CV F1={best_cv*100:.1f}%)")

    clf = LogisticRegression(C=best_c, max_iter=3000, random_state=42)
    clf.fit(X_train, y_train)

    # Temperature scaling en train set (mínimo NLL)
    probs_train = clf.predict_proba(X_train)[:, 1]
    eps    = 1e-7
    logits = np.log(np.clip(probs_train, eps, 1-eps) /
                    np.clip(1-probs_train, eps, 1-eps))

    def nll(T):
        p = 1 / (1 + np.exp(-logits / T))
        return -np.mean(y_train * np.log(p+eps) + (1-y_train) * np.log(1-p+eps))

    T_cal = float(minimize_scalar(nll, bounds=(0.1, 10.0), method="bounded").x)
    logger.info(f"  Temperature: T={T_cal:.3f}")
    return clf, T_cal


def apply_probe(clf, T_cal: float, X: np.ndarray) -> np.ndarray:
    probs  = clf.predict_proba(X)[:, 1]
    eps    = 1e-7
    logits = np.log(np.clip(probs, eps, 1-eps) / np.clip(1-probs, eps, 1-eps))
    return 1 / (1 + np.exp(-logits / T_cal))


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    import joblib

    print()
    print("=" * 65)
    print("  CLIP ViT-L/14 GenAI Detector — Train/Eval split correcto")
    print("=" * 65)
    print()
    logger.info(f"Device: {DEVICE}")
    if DEVICE.type == "cuda":
        logger.info(f"GPU: {torch.cuda.get_device_name(0)} | "
                    f"VRAM: {torch.cuda.get_device_properties(0).total_memory/1e9:.1f}GB")

    # Cargar splits
    train_paths, train_labels = load_train_data()
    eval_paths,  eval_labels  = load_eval_data()

    if not train_paths:
        logger.error("Benchmark masivo no encontrado. Ejecuta scripts/build_massive_benchmark.py")
        sys.exit(1)
    if not eval_paths:
        logger.error("Golden set no encontrado. Ejecuta tests/create_golden_set.py")
        sys.exit(1)

    # Cargar CLIP
    clip_model, clip_proc = load_clip()

    # Extraer features de training
    print(f"\n[1/4] Extrayendo features del benchmark masivo ({len(train_paths)} imgs)...")
    X_train = extract_features(clip_model, clip_proc, train_paths, batch_size=16)
    y_train = np.array(train_labels)
    logger.info(f"  X_train: {X_train.shape}")

    # Extraer features de evaluación
    print(f"\n[2/4] Extrayendo features del golden set ({len(eval_paths)} imgs)...")
    X_eval  = extract_features(clip_model, clip_proc, eval_paths, batch_size=16)
    y_eval  = np.array(eval_labels)

    del clip_model; torch.cuda.empty_cache()

    # Entrenar probe
    print("\n[3/4] Entrenando Linear Probe...")
    clf, T_cal = train_probe(X_train, y_train)

    # Evaluar en golden set (datos NO vistos en entrenamiento)
    print("\n[4/4] Evaluando en Golden Set (out-of-distribution)...")
    train_scores = apply_probe(clf, T_cal, X_train)
    eval_scores  = apply_probe(clf, T_cal, X_eval)

    m_train = compute_metrics(y_train, train_scores)
    m_eval  = compute_metrics(y_eval,  eval_scores)

    print()
    print("  RESULTADOS:")
    print(f"  Train (massive):  F1={m_train['f1']*100:.1f}%  AUC={m_train['roc_auc']:.3f}  ECE={m_train['ece']:.4f}")
    print(f"  Eval  (golden):   F1={m_eval['f1']*100:.1f}%  AUC={m_eval['roc_auc']:.3f}  ECE={m_eval['ece']:.4f}  "
          f"FPR={m_eval['fpr']*100:.1f}%  FNR={m_eval['fnr']*100:.1f}%")
    print(f"  Golden confusion: TN={m_eval['tn']} FP={m_eval['fp']} FN={m_eval['fn']} TP={m_eval['tp']}")

    # Comparar vs EfficientNet-B0 (a reemplazar)
    EFFNET_B0_F1 = 0.133  # F1=13.3% del modelo que reemplazamos
    improvement  = m_eval["f1"] - EFFNET_B0_F1
    print()
    print(f"  Vs EfficientNet-B0 (a reemplazar): F1=13.3%")
    print(f"  Mejora: {improvement*100:+.1f} pp")
    print(f"  Justifica reemplazo: {'SI' if m_eval['f1'] > EFFNET_B0_F1 else 'NO'}")

    # Test foto real comprimida
    print()
    logger.info("Verificando foto real comprimida JPEG Q=40...")
    from io import BytesIO
    import PIL.ImageFilter as IF
    from transformers import CLIPModel, CLIPProcessor

    clip_model2 = CLIPModel.from_pretrained(CLIP_ID, cache_dir=str(ROOT/"models"),
                                             torch_dtype=torch.float16 if DEVICE.type=="cuda" else torch.float32)
    clip_proc2  = CLIPProcessor.from_pretrained(CLIP_ID, cache_dir=str(ROOT/"models"))
    clip_model2.to(DEVICE).eval()

    img = Image.new("RGB", (640, 480)); px_img = img.load()
    rng = np.random.default_rng(42)
    for yy in range(480):
        for xx in range(640):
            n = int(rng.integers(-6, 7))
            if yy > 288: px_img[xx, yy] = (55+n, 95+n, 38+n)
            else: px_img[xx, yy] = (max(0,min(255,int(120-30*(yy/480))+n)),
                                     max(0,min(255,int(160-20*(yy/480))+n)),
                                     max(0,min(255,int(210-10*(yy/480))+n)))
    buf = BytesIO()
    img.filter(IF.GaussianBlur(0.5)).save(buf, "JPEG", quality=40)
    buf.seek(0)
    comp_img = Image.open(buf).copy()

    inp_comp = clip_proc2(images=comp_img, return_tensors="pt")
    px_comp  = inp_comp["pixel_values"].to(DEVICE)
    if DEVICE.type=="cuda": px_comp = px_comp.half()
    with torch.no_grad():
        out  = clip_model2.vision_model(pixel_values=px_comp)
        feat = out.pooler_output.float()
        feat = feat / feat.norm(dim=-1, keepdim=True)
    comp_score = float(apply_probe(clf, T_cal, feat.cpu().numpy())[0])
    del clip_model2; torch.cuda.empty_cache()

    logger.info(f"  Foto real JPEG Q=40: {comp_score*100:.1f}% — "
                f"{'OK <50%' if comp_score < 0.50 else 'ALERTA: FP potencial'}")

    # Guardar
    probe_path = MODELS / "clip_probe.joblib"
    joblib.dump({
        "clf": clf, "temperature": T_cal,
        "n_features": X_train.shape[1],
        "model_id":   CLIP_ID,
        "train_metrics": m_train,
        "eval_metrics":  m_eval,
    }, str(probe_path))

    config = {
        "model_c_type":          "clip_probe",
        "model_c_id":            CLIP_ID,
        "model_c_name":          "CLIP ViT-L/14 + LogisticRegression Probe",
        "model_c_description":   "UniversalFakeDetect: embeddings CLIP + probe lineal calibrado",
        "probe_path":            str(probe_path),
        "temperature":           T_cal,
        "train_metrics":         m_train,
        "eval_metrics":          m_eval,
        "compressed_real_score": round(comp_score, 4),
        "vs_efficientnet_b0":    {"effnet_f1": EFFNET_B0_F1, "clip_f1": m_eval["f1"],
                                   "improvement": round(improvement, 4)},
    }
    out_path = MODELS / "best_model_config.json"
    with open(out_path, "w") as f:
        json.dump(config, f, indent=2)

    print()
    print("=" * 65)
    print("  RESULTADO FINAL")
    print("=" * 65)
    print(f"  Modelo: CLIP ViT-L/14 + Linear Probe")
    print(f"  Eval F1:  {m_eval['f1']*100:.1f}%  "
          f"AUC: {m_eval['roc_auc']:.3f}  "
          f"ECE: {m_eval['ece']:.4f}")
    print(f"  FPR: {m_eval['fpr']*100:.1f}%  "
          f"FNR: {m_eval['fnr']*100:.1f}%")
    print(f"  Foto real comprimida: {comp_score*100:.1f}%")
    print(f"  Mejora vs EfficientNet-B0: {improvement*100:+.1f} pp F1")
    print(f"  Config guardada: {out_path}")
    print("=" * 65)
    print()
    print("  Siguiente paso automático:")
    print("    python scripts/integrate_model_c.py")


if __name__ == "__main__":
    main()
