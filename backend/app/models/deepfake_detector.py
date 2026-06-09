"""
5-Model Ensemble Deepfake Detector — v4.0

Models (all validated on golden set + extended benchmark):
  A — prithivMLmods/Deep-Fake-Detector-v2-Model (ViT, 92% F1)
      Specialization: face deepfakes (swaps, reenactment)
      Labels: {0: Realism, 1: Deepfake}

  B — Organika/sdxl-detector (Swin Transformer, 85.7% F1 on golden set)
      Specialization: SDXL vs real photos — strongest for general AI images
      Labels: {0: artificial, 1: human}

  C — Xicor9/efficientnet-b0-ffpp-c23 (EfficientNet-B0, AUC=0.94)
      Specialization: FaceForensics++ face-swap videos (old technique)
      Labels: {0: real, 1: fake} — limited generalization

  D — haywoodsloan/ai-image-detector-deploy (Swin v2, 98.15% accuracy)
      Specialization: modern AI art (MidJourney, FLUX, SDXL, DALL-E, Ideogram)
      Trained on 100K+ images from AI art platforms
      Labels: {0: artificial, 1: real}

  E — prithivMLmods/Deepfake-Detect-Siglip2 (SigLIP, 92.9M params)
      Specialization: general deepfake/real binary classification
      Labels: {0: Fake, 1: Real}

Ensemble weights (validated by grid search on golden set):
  No face:  B×0.45 + D×0.35 + A×0.10 + E×0.05 + C×0.05
  Face:     A×0.30 + B×0.25 + D×0.25 + E×0.15 + C×0.05

Weights are configurable and updated after each benchmark run.
"""
import json
import os
import time
import base64
from io import BytesIO
from pathlib import Path
from typing import Optional

import numpy as np
import torch
import torch.nn as nn
from PIL import Image
from loguru import logger
from transformers import AutoImageProcessor, AutoModelForImageClassification
from torchvision import transforms

from app.config import settings


FAKE_LABELS = {
    "fake", "deepfake", "forged", "manipulated",
    "ai-generated", "artificial", "synthetic", "generated", "1",
}
REAL_LABELS = {
    "real", "authentic", "genuine", "original", "realism",
    "nature", "natural", "human", "photograph", "0",
}

# Model identifiers
MODEL_A_CANDIDATES = [
    "prithivMLmods/Deep-Fake-Detector-v2-Model",
    "dima806/deepfake_vs_real_image_detection",
]
MODEL_B_CANDIDATES = [
    "Organika/sdxl-detector",
    "dima806/deepfake_vs_real_image_detection",
]
MODEL_D_CANDIDATES = [
    "haywoodsloan/ai-image-detector-deploy",
]
MODEL_E_CANDIDATES = [
    "prithivMLmods/Deepfake-Detect-Siglip2",
]
# Modelo F — AI-Human Detector (umm-maybe, ViT-Base 86M)
# Entrenado en distribución diferente a A-E: imágenes de plataformas reales de IA
# Labels: {0: artificial, 1: human} → artificial = fake
MODEL_F_CANDIDATES = [
    "umm-maybe/AI-image-detector",
]
MODEL_C_REPO = "Xicor9/efficientnet-b0-ffpp-c23"
MODEL_C_FILE = "efficientnet_b0_ffpp_c23.pth"

_IMAGENET_MEAN = [0.485, 0.456, 0.406]
_IMAGENET_STD  = [0.229, 0.224, 0.225]

# ─── Ensemble weights (v3 — 8 modelos) ───────────────────────────────────────
# Order: [A, B, C, D, E, F, freq, SRM]
#   A    = Face-Deepfake ViT       (face-swap specialist)
#   B    = SDXL Detector           (strongest general AI, F1=85.7%)
#   C    = CLIP ViT-L/14 + Probe   (EfficientNet-FF++ reemplazado)
#   D    = AI Art Detector         (Midjourney, DALL-E, Firefly)
#   E    = SigLIP Deepfake         (deepfake general)
#   F    = AI-Human Detector       (umm-maybe, distribución diferente a A-E)
#   freq = Frequency Spectral      (dominio frecuencias FFT, 0 VRAM)
#   SRM  = Noise Residual SRM      (residuos espaciales, ortogonal a freq, 0 VRAM)
#
# Pesos: suma = 1.0 exacto en ambos modos.
# No-face: B domina; F y SRM aportan perspectiva ortogonal.
# Face:    A lidera; B y D aportan; F, freq y SRM como soporte.
# freq y SRM reciben peso conservador (0.03) — señales auxiliares validadas parcialmente.
_W_NO_FACE = [0.10, 0.44, 0.03, 0.11, 0.03, 0.21, 0.03, 0.05]
_W_FACE    = [0.29, 0.20, 0.03, 0.17, 0.05, 0.19, 0.03, 0.04]


# ─── HuggingFace model wrapper ────────────────────────────────────────────────

class _HFModel:
    def __init__(self, candidates: list[str], label: str) -> None:
        self._candidates = candidates
        self._label      = label
        self.model_name: Optional[str] = None
        self.processor   = None
        self.model       = None
        self.device      = torch.device(
            "cuda" if settings.DEVICE == "cuda" and torch.cuda.is_available() else "cpu"
        )
        self._loaded     = False

    def load(self) -> None:
        if self._loaded:
            return
        os.environ["TRANSFORMERS_CACHE"] = str(settings.MODELS_DIR)
        os.environ["HF_HOME"]            = str(settings.MODELS_DIR)
        os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
        for name in self._candidates:
            try:
                logger.info(f"Loading [{self._label}]: {name}")
                proc  = AutoImageProcessor.from_pretrained(name, cache_dir=str(settings.MODELS_DIR))
                model = AutoModelForImageClassification.from_pretrained(
                    name, cache_dir=str(settings.MODELS_DIR), torch_dtype=torch.float32
                )
                model.to(self.device).eval()
                self.processor  = proc
                self.model      = model
                self.model_name = name
                self._loaded    = True
                logger.success(f"[{self._label}] {name} | labels={model.config.id2label}")
                return
            except Exception as e:
                logger.warning(f"[{self._label}] {name} failed: {e}")
        logger.error(f"No model loaded for [{self._label}]")

    def _parse(self, logits: torch.Tensor) -> tuple[float, float]:
        probs    = torch.softmax(logits, dim=-1).cpu().float().numpy()[0]
        id2label = self.model.config.id2label
        fake_p   = real_p = 0.0
        for idx, p in enumerate(probs):
            lbl = id2label.get(idx, str(idx)).lower().strip()
            if any(fl in lbl for fl in FAKE_LABELS):
                fake_p += float(p)
            elif any(rl in lbl for rl in REAL_LABELS):
                real_p += float(p)
            else:
                if idx == 0: real_p += float(p)
                else:        fake_p += float(p)
        total = fake_p + real_p
        if total:
            return fake_p / total, real_p / total
        return 0.5, 0.5

    def predict(self, image: Image.Image) -> Optional[dict]:
        if not self._loaded:
            return None
        try:
            inp = self.processor(images=image, return_tensors="pt")
            inp = {k: v.to(self.device) for k, v in inp.items()}
            with torch.no_grad():
                out = self.model(**inp)
            f, r = self._parse(out.logits)
            return {"fake_probability": f, "real_probability": r}
        except Exception as e:
            logger.debug(f"[{self._label}] predict failed: {e}")
            return None

    def predict_batch(self, images: list[Image.Image]) -> list[Optional[dict]]:
        if not self._loaded:
            return [None] * len(images)
        try:
            pv = torch.cat(
                [self.processor(images=img, return_tensors="pt")["pixel_values"] for img in images]
            ).to(self.device)
            with torch.no_grad():
                out = self.model(pixel_values=pv)
            results = []
            for i in range(len(images)):
                f, r = self._parse(out.logits[i:i+1])
                results.append({"fake_probability": f, "real_probability": r})
            return results
        except Exception as e:
            logger.debug(f"[{self._label}] batch failed: {e}")
            return [None] * len(images)

    def grad_cam(self, image: Image.Image, target_class: int = 1) -> Optional[str]:
        if not self._loaded:
            return None
        try:
            from pytorch_grad_cam import GradCAMPlusPlus
            from pytorch_grad_cam.utils.model_targets import ClassifierOutputTarget
            from pytorch_grad_cam.utils.image import show_cam_on_image
            if not hasattr(self.model, "vit"):
                return None
            target_layers = [self.model.vit.encoder.layer[-1].layernorm_before]

            def reshape(t: torch.Tensor) -> torch.Tensor:
                r = t[:, 1:, :]
                h = w = int(r.shape[1] ** 0.5)
                return r.reshape(t.size(0), h, w, t.size(2)).transpose(2, 3).transpose(1, 2)

            cam  = GradCAMPlusPlus(model=self.model, target_layers=target_layers, reshape_transform=reshape)
            px   = self.processor(images=image, return_tensors="pt")["pixel_values"].to(self.device)
            px.requires_grad_(True)
            gray = cam(input_tensor=px, targets=[ClassifierOutputTarget(target_class)])[0]
            rgb  = np.array(image.resize((224, 224))).astype(np.float32) / 255.0
            hmap = show_cam_on_image(rgb, gray, use_rgb=True)
            buf  = BytesIO()
            Image.fromarray(hmap).save(buf, format="PNG")
            return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
        except Exception as e:
            logger.debug(f"GradCAM failed: {e}")
            return None


# ─── CLIP ViT-L/14 + Linear Probe (Model C — Advanced GenAI Detector) ──────────
# Reemplaza EfficientNet-B0 (F1=13.3%) por CLIP probe (F1=94.7% golden set)
# Metodología: UniversalFakeDetect (Ojha et al. 2023)

class _EfficientNetFF:  # alias mantenido para compatibilidad con meta-ensemble
    """
    CLIP ViT-L/14 + Linear Probe calibrado.
    Entrenado en benchmark masivo (512 imgs), evaluado en golden set independiente.
    Especializado en artefactos de FLUX.1, MidJourney v6, SDXL, Ideogram.
    """
    def __init__(self) -> None:
        self.device    = torch.device(
            "cuda" if settings.DEVICE == "cuda" and torch.cuda.is_available() else "cpu"
        )
        self.model     = None
        self._loaded   = False
        self._available= True
        self.model_name= MODEL_C_REPO
        self._preprocess = transforms.Compose([
            transforms.Resize(256), transforms.CenterCrop(224),
            transforms.ToTensor(), transforms.Normalize(_IMAGENET_MEAN, _IMAGENET_STD),
        ])

    def load(self) -> None:
        if self._loaded or not self._available:
            return
        try:
            import joblib
            from transformers import CLIPModel, CLIPProcessor
            os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

            probe_config_path = settings.MODELS_DIR / "advanced_detector" / "best_model_config.json"
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


    def _embed(self, images) -> "np.ndarray":
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
        return 1 / (1 + np.exp(-logits / self._temperature))

    def predict(self, image: Image.Image) -> Optional[dict]:
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
        return [{"fake_probability": float(p), "real_probability": float(1 - p)} for p in probs]


# ─── Singleton model instances ────────────────────────────────────────────────
_model_a = _HFModel(MODEL_A_CANDIDATES, "face-deepfake-vit")
_model_b = _HFModel(MODEL_B_CANDIDATES, "sdxl-detector")
_model_c = _EfficientNetFF()
_model_d = _HFModel(MODEL_D_CANDIDATES, "ai-art-detector")
_model_e = _HFModel(MODEL_E_CANDIDATES, "siglip-deepfake")
_model_f = _HFModel(MODEL_F_CANDIDATES, "ai-human-detector")   # Nuevo: distribución diferente


# ─── Ensemble combination ─────────────────────────────────────────────────────

def _get_score(result: Optional[dict]) -> Optional[float]:
    return result["fake_probability"] if result is not None else None


def _calibrated_combine(
    score_a: float,
    score_b: float,
    score_c: Optional[float],
    face: bool,
    score_d: Optional[float] = None,
    score_e: Optional[float] = None,
    score_f: Optional[float] = None,     # AI-Human Detector (umm-maybe)
    score_freq: Optional[float] = None,  # Frequency Spectral Detector (FFT)
    score_srm: Optional[float] = None,   # SRM Noise Residual Detector
    score_ela: Optional[float] = None,   # ELA Detector (Error Level Analysis)
) -> tuple[float, dict]:
    """
    Meta-ensemble v3 — 8 modelos GPU + 3 señales CPU auxiliares.
    El XGBoost usa los 3 features más confiables (sdxl, aiart, clip).
    F, freq, SRM y ELA aportan señales ortogonales como correcciones post-meta.
    """
    from app.models.meta_ensemble import MetaEnsemble
    meta = MetaEnsemble.get_instance()
    meta.load()

    scores_dict = {
        "face_deepfake_vit":   score_a,
        "sdxl_detector":       score_b,
        "efficientnet_ffpp":   score_c,
        "ai_art_detector":     score_d,
        "siglip_deepfake":     score_e,
        "ai_human_detector":   score_f,
        "frequency_spectral":  score_freq,
        "srm_noise_detector":  score_srm,
        "ela_detector":        score_ela,
    }

    # XGBoost meta-model (usa solo los 3 features confiables — no se retrenó)
    combined, meta_info = meta.predict(scores_dict, face=face)

    # ── Corrección post-meta: señales auxiliares ortogonales ─────────────────
    # Modelo F + freq — umbral reducido a 0.20 (antes 0.35) para capturar más
    # casos de divergencia real. Peso proporcional al desacuerdo, cap 0.18.
    if score_f is not None:
        freq_w  = 0.15 if score_freq is not None else 0.0
        new_sig = (1 - freq_w) * score_f + freq_w * (score_freq or score_f)
        disc_f  = abs(new_sig - combined)
        if disc_f > 0.20:
            alpha_f  = min(0.18, disc_f * 0.35)
            combined = combined * (1.0 - alpha_f) + new_sig * alpha_f

    # SRM Noise Residual — umbral reducido a 0.25 (antes 0.40).
    # Peso proporcional, cap 0.10. Señal espacial ortogonal al FFT global.
    if score_srm is not None:
        disc_srm = abs(score_srm - combined)
        if disc_srm > 0.25:
            alpha_srm = min(0.10, disc_srm * 0.20)
            combined  = combined * (1.0 - alpha_srm) + score_srm * alpha_srm

    # Señal conjunta F+SRM — cuando ambas señales auxiliares coinciden con fuerza
    # alta (F > 0.72, SRM > 0.65) y el ensemble está por debajo de 0.50,
    # el acuerdo entre residuos espaciales (SRM) y la firma de distribución (F)
    # justifica una corrección adicional. Peso cap 0.20.
    if score_f is not None and score_srm is not None:
        if score_f > 0.72 and score_srm > 0.65:
            joint_ai   = 0.55 * score_f + 0.45 * score_srm
            disc_joint = abs(joint_ai - combined)
            if disc_joint > 0.18:
                alpha_joint = min(0.20, disc_joint * 0.40)
                combined    = combined * (1.0 - alpha_joint) + joint_ai * alpha_joint

    # ELA (Error Level Analysis) — señal de historial de compresión.
    # Umbral 0.22: solo corrige cuando la uniformidad ELA discrepa notablemente.
    # Peso proporcional, cap 0.08 — señal nueva con calibración conservadora.
    if score_ela is not None:
        disc_ela = abs(score_ela - combined)
        if disc_ela > 0.22:
            alpha_ela = min(0.08, disc_ela * 0.15)
            combined  = combined * (1.0 - alpha_ela) + score_ela * alpha_ela

    combined = float(np.clip(combined, 0.0, 1.0))

    per_model = {
        **{k: round(v, 4) if v is not None else None for k, v in scores_dict.items()},
        "face_detected":    face,
        "ensemble_method":  meta_info.get("method", "unknown"),
        "std":              meta_info.get("std"),
        "entropy":          meta_info.get("entropy"),
        "ood_signal":       meta_info.get("ood_signal", False),
    }
    return float(np.clip(combined, 0, 1)), per_model


# ─── Public API ───────────────────────────────────────────────────────────────

class DeepfakeDetector:
    _instance: Optional["DeepfakeDetector"] = None

    @classmethod
    def get_instance(cls) -> "DeepfakeDetector":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def load(self) -> None:
        _model_a.load()
        _model_b.load()
        _model_c.load()
        _model_d.load()
        _model_e.load()
        _model_f.load()   # Nuevo: AI-Human Detector

    @property
    def _loaded(self) -> bool:
        return _model_a._loaded

    @property
    def model_name(self) -> str:
        parts = [m.model_name or "?" for m in [_model_a, _model_b] if m._loaded]
        if _model_c._loaded: parts.append(_model_c.model_name)
        if _model_d._loaded: parts.append(_model_d.model_name or "?")
        if _model_e._loaded: parts.append(_model_e.model_name or "?")
        return " | ".join(parts) if parts else "not loaded"

    @property
    def device_name(self) -> str:
        return torch.cuda.get_device_name(0) if _model_a.device.type == "cuda" else "CPU"

    @property
    def device(self):
        return _model_a.device

    def predict(self, image: Image.Image, face_detected: bool = False) -> dict:
        start = time.time()
        ra = _model_a.predict(image)
        rb = _model_b.predict(image)
        rc = _model_c.predict(image)
        rd = _model_d.predict(image)
        re = _model_e.predict(image)

        fake, per_model = _calibrated_combine(
            ra["fake_probability"] if ra else 0.5,
            rb["fake_probability"] if rb else 0.5,
            rc["fake_probability"] if rc else None,
            face=face_detected,
            score_d=rd["fake_probability"] if rd else None,
            score_e=re["fake_probability"] if re else None,
        )
        return {
            "fake_probability": fake,
            "real_probability": 1.0 - fake,
            "inference_time":   time.time() - start,
            "per_model":        per_model,
        }

    def predict_batch(
        self,
        images: list[Image.Image],
        face_flags: Optional[list[bool]] = None,
    ) -> list[dict]:
        if not images:
            return []
        if face_flags is None:
            face_flags = [False] * len(images)

        ra_list = _model_a.predict_batch(images)
        rb_list = _model_b.predict_batch(images)
        rc_list = _model_c.predict_batch(images)
        rd_list = _model_d.predict_batch(images)
        re_list = _model_e.predict_batch(images)
        rf_list = _model_f.predict_batch(images)   # Model F incluido en batch

        out = []
        for ra, rb, rc, rd, re, rf, face in zip(
            ra_list, rb_list, rc_list, rd_list, re_list, rf_list, face_flags
        ):
            fake, _ = _calibrated_combine(
                ra["fake_probability"] if ra else 0.5,
                rb["fake_probability"] if rb else 0.5,
                rc["fake_probability"] if rc else None,
                face=face,
                score_d=rd["fake_probability"] if rd else None,
                score_e=re["fake_probability"] if re else None,
                score_f=rf["fake_probability"] if rf else None,
                # freq y SRM se añaden en el llamador (video_service) por frame
            )
            out.append({"fake_probability": fake, "real_probability": 1.0 - fake})
        return out

    def generate_heatmap(self, image: Image.Image, target_class: int = 1) -> Optional[str]:
        return _model_a.grad_cam(image, target_class)
