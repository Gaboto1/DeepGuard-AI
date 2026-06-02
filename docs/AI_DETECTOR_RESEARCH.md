# AI_DETECTOR_RESEARCH.md
## Investigación: Detectores de Imágenes IA Modernas
**Fecha:** 2026-05-29  |  **Target:** SDXL, FLUX, MidJourney, GPT Image, Ideogram

---

## Modelos Investigados y Verificados

### 1. haywoodsloan/ai-image-detector-deploy ✅ INTEGRADO
| Campo | Valor |
|-------|-------|
| Fuente | HuggingFace Hub |
| Arquitectura | Swin v2 (Microsoft) |
| Parámetros | 195.2M |
| VRAM | ~800MB |
| Dataset | 100,000+ imágenes de plataformas de arte IA |
| Labels | {0: artificial, 1: real} |
| Accuracy | 98.15% (publicado) |
| Licencia | No especificada |
| AutoModel | Sí (AutoModelForImageClassification) |
| Estado | **INTEGRADO como Model D** |
| Ventajas | Entrenado en MidJourney, FLUX, SDXL, DALL-E, Ideogram — cobertura máxima |
| Limitaciones | No especificadas en el repo |

### 2. Organika/sdxl-detector ✅ INTEGRADO (anterior)
| Campo | Valor |
|-------|-------|
| Fuente | HuggingFace Hub |
| Arquitectura | Swin Transformer |
| Parámetros | 86.8M |
| VRAM | ~350MB |
| Dataset | Pares Wikimedia-SDXL |
| Labels | {0: artificial, 1: human} |
| F1 (Golden Set) | 85.7% |
| AUC | 0.998 (publicado) |
| Licencia | CC-BY-NC-3.0 |
| Ventajas | Muy bajo FPR en fotos reales, fuerte para SDXL |
| Limitaciones | Entrenado principalmente en SDXL — puede fallar en otros generadores |

### 3. prithivMLmods/Deepfake-Detect-Siglip2 ✅ INTEGRADO
| Campo | Valor |
|-------|-------|
| Fuente | HuggingFace Hub |
| Arquitectura | SigLIP (Google) |
| Parámetros | 92.9M |
| VRAM | ~381MB |
| Dataset | Custom deepfake/real pairs |
| Labels | {0: Fake, 1: Real} |
| Licencia | Apache 2.0 |
| AutoModel | Sí |
| Estado | **INTEGRADO como Model E** |
| Ventajas | Arquitectura reciente SigLIP, buena generalización |
| Limitaciones | No datos detallados del training set |

### 4. prithivMLmods/Deep-Fake-Detector-v2-Model ✅ YA TENIDO
| Campo | Valor |
|-------|-------|
| Arquitectura | ViT-base (Google/ViT-base-patch16-224) |
| Parámetros | 85.8M |
| F1 (Golden Set) | 64.3% (FPR alto sin cara) |
| Estado | Integrado como Model A |
| Limitaciones | Alta FPR (90%) en imágenes sin cara |

### 5. Xicor9/efficientnet-b0-ffpp-c23 ⚠️ REEMPLAZABLE
| Campo | Valor |
|-------|-------|
| Arquitectura | EfficientNet-B0 |
| Dataset | FaceForensics++ c23 (face-swaps 2019-2022) |
| F1 (Golden Set) | 13.3% |
| Limitaciones | **FNR=90%** — casi no detecta IA moderna. Solo face-swaps viejos |
| Estado | Mantenido con peso mínimo (0.05). Candidato a reemplazo |

---

## Modelos Investigados — No Disponibles / No Compatibles

| Modelo | Razón |
|--------|-------|
| Falconsai/deepfake-image-detection | No existe en HuggingFace |
| umm-maybe/AI-image-detector | Desactualizado (2022), no detecta MJ5/SDXL/FLUX |
| haywoodsloan/ai-image-detector | Versión sin -deploy, pesos incompletos |
| Universal Fake Detect (Ojha 2023) | No en HuggingFace — repo GitHub requiere setup manual |
| DIRE | No en HuggingFace — requiere reconstrucción de difusión |
| CNNDetection (Wang et al.) | Solo ResNet50 para ProGAN — no para diffusion |

---

## Modelos para Categorías Específicas No Cubiertas

### Anime / Arte Digital
No se encontró modelo especializado disponible en HuggingFace con buena cobertura y carga AutoModel.
**Alternativa implementada:** Generación sintética con características conocidas + peso aumentado del ensemble para imágenes sin cara.

### GAN clásico (ProGAN, StyleGAN)
**CNNDetection** (Wang et al.) existe pero requiere setup manual. Las imágenes GAN antiguas son difíciles de detectar con modelos entrenados en diffusion.

---

## Recomendación de Integración

```
Ensemble actual v4.0:
  D (haywoodsloan): 35% sin cara, 25% con cara  ← Nueva incorporación
  B (Organika):     45% sin cara, 25% con cara  ← Ya teníamos
  A (ViT):          10% sin cara, 30% con cara  ← Ya teníamos
  E (SigLIP):        5% sin cara, 15% con cara  ← Nueva incorporación  
  C (EfficientNet):  5% sin cara,  5% con cara  ← Candidato a retiro
```

**Siguiente paso crítico:** Ejecutar `run_full_evaluation.py --set massive` y usar los pesos óptimos encontrados.
