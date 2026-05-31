"""
Integra CLIP ViT-L/14 + Linear Probe como nuevo Modelo C
=========================================================
Reemplaza EfficientNet-B0 (F1=13.3%) por CLIP probe (F1=94.7%).
Actualiza el vector de features del meta-ensemble XGBoost.
Ejecuta mini-benchmark de verificación.
"""
import json
import os
import sys
from pathlib import Path

ROOT    = Path(__file__).parent.parent
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))
os.environ["TRANSFORMERS_CACHE"]              = str(ROOT / "models")
os.environ["HF_HOME"]                         = str(ROOT / "models")
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
os.chdir(BACKEND)

from loguru import logger

CONFIG_PATH = ROOT / "models" / "advanced_detector" / "best_model_config.json"
DETECTOR    = BACKEND / "app" / "models" / "deepfake_detector.py"
META_SCRIPT = ROOT / "scripts" / "train_meta_ensemble.py"


def patch_detector():
    """Añade la clase _CLIPProbeDetector y actualiza _model_c."""
    logger.info("Actualizando deepfake_detector.py...")

    code = DETECTOR.read_text(encoding="utf-8")

    # Reemplazar la clase _EfficientNetFF por _CLIPProbeDetector
    old_class = '''# ─── EfficientNet-B0/B4 wrapper ───────────────────────────────────────────────

class _EfficientNetFF:'''

    new_class = '''# ─── CLIP ViT-L/14 + Linear Probe (Model C — Advanced GenAI Detector) ──────────
# Reemplaza EfficientNet-B0 (F1=13.3%) por CLIP probe (F1=94.7% golden set)
# Metodología: UniversalFakeDetect (Ojha et al. 2023)

class _EfficientNetFF:  # alias mantenido para compatibilidad con meta-ensemble
    """
    CLIP ViT-L/14 + Linear Probe calibrado.
    Entrenado en benchmark masivo (512 imgs), evaluado en golden set independiente.
    Especializado en artefactos de FLUX.1, MidJourney v6, SDXL, Ideogram.
    """'''

    if old_class in code:
        code = code.replace(old_class, new_class, 1)
        logger.info("  Docstring de clase actualizado")

    # Reemplazar el método load() de _EfficientNetFF
    old_load_start = "    def load(self) -> None:\n        if self._loaded or not self._available:\n            return\n        try:\n            os.environ[\"HF_HUB_DISABLE_SYMLINKS_WARNING\"] = \"1\"\n            local_b4"

    if old_load_start in code:
        # Find full method end and replace
        load_start_idx = code.find("    def load(self) -> None:\n        if self._loaded or not self._available:\n            return\n        try:\n            os.environ")
        # Find next method def after load
        next_def_idx = code.find("\n    def _t(", load_start_idx)
        if load_start_idx > -1 and next_def_idx > -1:
            old_load_block = code[load_start_idx:next_def_idx]
            new_load_block = '''    def load(self) -> None:
        if self._loaded or not self._available:
            return
        try:
            import joblib
            from transformers import CLIPModel, CLIPProcessor
            os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

            probe_config_path = settings.MODELS_DIR.parent / "advanced_detector" / "best_model_config.json"
            if not probe_config_path.exists():
                logger.warning("[CLIP-C] Config no encontrada. Ejecuta scripts/download_modern_detector.py")
                self._available = False
                return

            with open(probe_config_path) as f:
                cfg = json.load(f)

            probe_path = Path(cfg["probe_path"])
            if not probe_path.exists():
                logger.warning(f"[CLIP-C] Probe no encontrado: {probe_path}")
                self._available = False
                return

            probe_data = joblib.load(str(probe_path))
            self._clf         = probe_data["clf"]
            self._temperature = float(probe_data.get("temperature", 1.0))
            self.model_name   = "CLIP ViT-L/14 + LR Probe (Advanced GenAI)"

            clip_id = cfg.get("model_c_id", "openai/clip-vit-large-patch14")
            self._clip_model = CLIPModel.from_pretrained(
                clip_id, cache_dir=str(settings.MODELS_DIR),
                torch_dtype=torch.float16 if self.device.type == "cuda" else torch.float32,
            )
            self._clip_proc  = CLIPProcessor.from_pretrained(clip_id, cache_dir=str(settings.MODELS_DIR))
            self._clip_model.to(self.device).eval()
            self.model        = self._clip_model  # alias para compatibilidad
            self._loaded      = True
            logger.success(f"[CLIP-C] {self.model_name} | T={self._temperature:.3f}")
        except Exception as e:
            logger.warning(f"[CLIP-C] Carga fallida: {e}")
            self._available = False

'''
            code = code[:load_start_idx] + new_load_block + code[next_def_idx:]
            logger.info("  Método load() actualizado")

    # Reemplazar _t (tensor creation) y predict/predict_batch
    old_tensor = "    def _t(self, img: Image.Image) -> torch.Tensor:\n        return self._preprocess(img.convert(\"RGB\")).unsqueeze(0)"
    new_tensor = '''    def _embed(self, images) -> "np.ndarray":
        """Extrae embeddings CLIP L2-normalizados."""
        if not isinstance(images, list):
            images = [images]
        inp = self._clip_proc(images=[img.convert("RGB") for img in images], return_tensors="pt", padding=True)
        px  = inp["pixel_values"].to(self.device)
        if self.device.type == "cuda": px = px.half()
        with torch.no_grad():
            out  = self._clip_model.vision_model(pixel_values=px)
            feat = out.pooler_output.float()
            feat = feat / feat.norm(dim=-1, keepdim=True)
        return feat.cpu().numpy()

    def _apply_temperature(self, probs: "np.ndarray") -> "np.ndarray":
        eps    = 1e-7
        logits = np.log(np.clip(probs, eps, 1-eps) / np.clip(1-probs, eps, 1-eps))
        return 1 / (1 + np.exp(-logits / self._temperature))'''

    if old_tensor in code:
        code = code.replace(old_tensor, new_tensor)
        logger.info("  _t() reemplazado por _embed()")

    # Reemplazar predict() en _EfficientNetFF
    old_predict = '''    def predict(self, image: Image.Image) -> Optional[dict]:
        if not self._loaded:
            return None
        t = self._t(image).to(self.device)
        with torch.no_grad():
            out = self.model(t)
        p = torch.softmax(out, dim=-1)[0].cpu().float().numpy()
        return {"fake_probability": float(p[1]), "real_probability": float(p[0])}

    def predict_batch(self, images: list[Image.Image]) -> list[Optional[dict]]:
        if not self._loaded:
            return [None] * len(images)
        batch = torch.cat([self._t(img) for img in images]).to(self.device)
        with torch.no_grad():
            out = self.model(batch)
        probs = torch.softmax(out, dim=-1).cpu().float().numpy()
        return [{"fake_probability": float(p[1]), "real_probability": float(p[0])} for p in probs]'''

    new_predict = '''    def predict(self, image: Image.Image) -> Optional[dict]:
        if not self._loaded:
            return None
        feats = self._embed(image)
        probs = self._apply_temperature(self._clf.predict_proba(feats)[:, 1])
        return {"fake_probability": float(probs[0]), "real_probability": float(1 - probs[0])}

    def predict_batch(self, images: list[Image.Image]) -> list[Optional[dict]]:
        if not self._loaded:
            return [None] * len(images)
        feats = self._embed(images)
        probs = self._apply_temperature(self._clf.predict_proba(feats)[:, 1])
        return [{"fake_probability": float(p), "real_probability": float(1 - p)} for p in probs]'''

    if old_predict in code:
        code = code.replace(old_predict, new_predict)
        logger.info("  predict() y predict_batch() actualizados")

    # Asegurar que json y Path se importan
    if "import json" not in code:
        code = code.replace("import os\n", "import json\nimport os\n", 1)
    if "from pathlib import Path" not in code:
        code = code.replace("import numpy as np\n", "import numpy as np\nfrom pathlib import Path\n", 1)

    DETECTOR.write_text(code, encoding="utf-8")
    logger.success("deepfake_detector.py actualizado")


def retrain_meta_ensemble():
    """Reentrena el meta-ensemble XGBoost con el nuevo vector de features (sin EffNet)."""
    logger.info("Reentrenando meta-ensemble con nuevo Modelo C...")
    import subprocess, sys
    result = subprocess.run(
        [sys.executable, str(META_SCRIPT)],
        capture_output=True, text=True, cwd=str(ROOT),
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    for line in result.stdout.split("\n"):
        if any(k in line for k in ["F1=", "AUC=", "ECE=", "Mejor", "guardado", "===", "---"]):
            print("  " + line)
    if result.returncode != 0:
        logger.warning(f"Meta-ensemble: {result.stderr[-500:]}")


def run_mini_benchmark():
    """Mini-benchmark de verificación en Golden Set."""
    logger.info("Mini-benchmark de verificación...")

    import numpy as np
    from app.models.deepfake_detector import _model_a, _model_b, _model_c, _model_d, _model_e, _calibrated_combine
    from app.models.meta_ensemble import MetaEnsemble
    from PIL import Image

    _model_a.load(); _model_b.load(); _model_c.load(); _model_d.load(); _model_e.load()
    MetaEnsemble._instance = None
    meta = MetaEnsemble.get_instance(); meta.load()

    with open(ROOT / "tests" / "golden_set" / "manifest.json") as f:
        manifest = json.load(f)
    labeled = [(e, int(e["expected_label"])) for e in manifest if e.get("expected_label") is not None]

    y_true, y_ens = [], []
    for entry, label in labeled:
        img = Image.open(ROOT / entry["path"]).convert("RGB")
        ra = _model_a.predict(img); rb = _model_b.predict(img)
        rc = _model_c.predict(img); rd = _model_d.predict(img); re = _model_e.predict(img)
        ens, _ = _calibrated_combine(
            ra["fake_probability"] if ra else 0.5,
            rb["fake_probability"] if rb else 0.5,
            rc["fake_probability"] if rc else None, face=False,
            score_d=rd["fake_probability"] if rd else None,
            score_e=re["fake_probability"] if re else None,
        )
        y_true.append(label); y_ens.append(ens)

    y_t=np.array(y_true); y_s=np.array(y_ens); y_p=(y_s>=0.5).astype(int)
    tp=int(((y_p==1)&(y_t==1)).sum()); tn=int(((y_p==0)&(y_t==0)).sum())
    fp=int(((y_p==1)&(y_t==0)).sum()); fn=int(((y_p==0)&(y_t==1)).sum())
    prec=tp/max(1,tp+fp); rec=tp/max(1,tp+fn); f1=2*prec*rec/max(1e-9,prec+rec)
    from sklearn.metrics import roc_auc_score
    ece=0.0
    for i in range(10):
        mask=(y_s>=i/10)&(y_s<(i+1)/10)
        if mask.sum(): ece+=(mask.sum()/len(y_t))*abs(float(y_s[mask].mean())-float(y_t[mask].mean()))

    print()
    print("=" * 55)
    print("  MINI-BENCHMARK POST-INTEGRACIÓN")
    print("=" * 55)
    print(f"  F1:   {f1*100:.1f}%  (target: >90%)")
    print(f"  AUC:  {roc_auc_score(y_t,y_s):.3f}")
    print(f"  ECE:  {ece:.4f}  (target: <0.20)")
    print(f"  FPR:  {fp/max(1,fp+tn)*100:.1f}%")
    print(f"  FNR:  {fn/max(1,fn+tp)*100:.1f}%")
    print(f"  TN={tn} FP={fp} FN={fn} TP={tp}")
    print(f"  {'OBJETIVO CUMPLIDO' if f1>=0.90 and ece<0.20 else 'REVISAR METRICAS'}")
    print("=" * 55)


if __name__ == "__main__":
    import json
    print()
    print("=" * 55)
    print("  INTEGRACION: CLIP Probe como Modelo C")
    print("=" * 55)

    if not CONFIG_PATH.exists():
        logger.error(f"Config no encontrada: {CONFIG_PATH}")
        logger.error("Ejecuta primero: python scripts/download_modern_detector.py")
        sys.exit(1)

    with open(CONFIG_PATH) as f:
        cfg = json.load(f)
    logger.info(f"Modelo seleccionado: {cfg['model_c_name']}")
    logger.info(f"F1 golden set: {cfg['eval_metrics']['f1']*100:.1f}%")

    print("\n[1/3] Actualizando deepfake_detector.py...")
    patch_detector()

    print("\n[2/3] Reentrenando meta-ensemble con nuevas features...")
    retrain_meta_ensemble()

    print("\n[3/3] Mini-benchmark de verificación...")
    run_mini_benchmark()

    print()
    print("  Reinicia el backend para activar el nuevo Modelo C:")
    print("  START DEEPGUARD.bat")
