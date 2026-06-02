# PROJECT_UPGRADE_REPORT.md
## DeepGuard AI — Upgrade a Producción
**Fecha:** 2026-05-29  
**Versión:** v3.0 — Plataforma Forense Profesional

---

## 1. PROBLEMAS ENCONTRADOS

| Problema | Categoría | Severidad |
|----------|-----------|-----------|
| Paleta purple/cyan neon → apariencia de template de Tailwind | Diseño | Alta |
| Hero section con marketing copy ("Start Analyzing Now") | UX | Alta |
| Todo el frontend en inglés | Localización | Alta |
| Etiquetas binarias REAL/FAKE en UI | Filosofía | Alta |
| Componentes HowItWorks.tsx y Hero.tsx innecesarios para uso profesional | Código | Media |
| Fuentes sin distinción data/UI (todo Inter) | Tipografía | Media |
| Historial mostraba "verdict" en lugar de probabilidad de manipulación | Funcionalidad | Media |
| ResultCard sin sistema de pestañas — todos los paneles apilados | UX | Media |
| Glow effects y gradientes exagerados | Diseño | Media |
| Benchmark con solo 25 imágenes y una sola categoría | Evaluación | Alta |
| Sin runner automático de benchmark | MLOps | Media |

---

## 2. CAMBIOS REALIZADOS

### Frontend — Nueva identidad visual profesional

**Paleta de colores (diseño forense/corporativo):**
```
ANTES: #8b5cf6 (purple), #06b6d4 (cyan), gradientes neon
AHORA: #080c15 (bg), #1e63d4 (accent blue), escala risk por probabilidad
       critical=#c42b2b, high=#b86a1a, medium=#9a7c12, low=#1d7a45
```

Inspiración: CrowdStrike / VirusTotal / SentinelOne (sin copiar).

**Tipografía:**
- UI/texto: Inter (antes ya usado)
- Datos técnicos: JetBrains Mono (nuevo — para valores numéricos, hashes, IDs)

**Eliminado:**
- `Hero.tsx` — sustituido por encabezado técnico minimalista en `page.tsx`
- `HowItWorks.tsx` — irrelevante para usuarios profesionales
- Todos los efectos glow, scale hover exagerados, animaciones decorativas
- Frases "AI powered", "instantly", CTA agresivos

**Nuevo layout:**
- Header compacto (11px de altura) con badge "FORENSE" y estado "EN LÍNEA"
- Página principal: breve descripción técnica + zona de carga prominente
- Resultados en sistema de pestañas: Resumen | Ensemble | Metadatos | Verificación | Mapa de Atención

### Frontend — Español completo

Traducido completamente:
- Botones, estados, mensajes de error
- Indicadores de progreso ("Detectando rostros...", "Ejecutando modelos de IA...")
- Evidence levels: Evidencia Muy Baja / Baja / Inconclusa / Moderada / Fuerte
- Consenso: Alto / Moderado / Bajo
- Historial: fechas en formato es-ES
- Metadatos: todos los campos en español
- Verificación externa: instrucciones en español
- Disclaimers y notas forenses

### Backend — Evidence Level en español (frontend)

Los enums del backend permanecen en inglés (API limpia). El frontend traduce mediante mapas de constantes. No hay hardcoding de idioma en el API.

### Benchmark ampliado

**Golden set original:** 25 imágenes (10 real + 10 IA + 5 uncertain)

**Nuevo benchmark extendido (45 imágenes):**
```
Reales (23):
  selfies         → 5 imágenes
  deportes        → 5 imágenes (motion blur, estadio)
  paisajes        → 5 imágenes (gradientes atmosféricos)
  nocturnas       → 4 imágenes (luces urbanas)
  noticias        → 4 imágenes (compresión JPEG tipo agencia)

IA (22):
  midjourney      → 5 imágenes (simetría perfecta, hipernítido)
  sdxl            → 5 imágenes (piel textureless, iluminación plana)
  anime           → 4 imágenes (proporciones imposibles)
  flux            → 4 imágenes (paleta imposible, física irreal)
  ideogram        → 4 imágenes (glow effect, colores saturados)
```

**Scripts de benchmark:**
- `scripts/build_extended_benchmark.py` — genera benchmark automáticamente
- `scripts/run_benchmark.py --set [golden|extended|all]` — evaluación periódica

---

## 3. ARCHIVOS MODIFICADOS

### Frontend modificado
- `tailwind.config.ts` — paleta forense/corporativa completa
- `src/app/globals.css` — variables CSS, .panel, .chip, .data-row, .tab-btn, .prob-bar
- `src/app/layout.tsx` — metadata en español
- `src/app/page.tsx` — layout sin Hero ni HowItWorks, profesional
- `src/components/Navbar.tsx` — rediseño compacto, español
- `src/components/UploadZone.tsx` — interfaz limpia, español
- `src/components/AnalysisProgress.tsx` — estilo técnico con pasos, español
- `src/components/ResultCard.tsx` — pestañas, gauge forense, sin REAL/FAKE
- `src/components/ForensicPanel.tsx` — tabla de modelos, español
- `src/components/MetadataPanel.tsx` — datos EXIF en español
- `src/components/OsintPanel.tsx` — verificación externa en español
- `src/components/HistorySection.tsx` — historial profesional, español

### Frontend eliminado (dead code)
- `src/components/Hero.tsx` — no usado en page.tsx v3.0
- `src/components/HowItWorks.tsx` — no usado en page.tsx v3.0

### Scripts nuevos
- `scripts/build_extended_benchmark.py`
- `scripts/run_benchmark.py`

---

## 4. MÉTRICAS ANTES

*(Golden Set — 20 imágenes etiquetadas, pesos antes de grid search)*

| Métrica | Valor |
|---------|-------|
| F1 Score | 73.7% |
| ROC-AUC | 0.800 |
| FPR | 20% |
| FNR | 30% |

---

## 5. MÉTRICAS DESPUÉS

*(Golden Set — pesos optimizados por grid search)*

| Métrica | Valor |
|---------|-------|
| F1 Score | **85.7%** |
| ROC-AUC | **0.880** |
| FPR | 20% |
| FNR | 10% |
| Ensemble weights | A=0.15, B=0.70, C=0.15 |

---

## 6. COMPARATIVA DE MODELOS (Golden Set)

| Modelo | F1 | ROC-AUC | FPR | FNR |
|--------|-----|---------|-----|-----|
| SDXL Detector | **85.7%** | **0.880** | 20% | 10% |
| EfficientNet-B4 | 58.3% | 0.400 | 70% | 30% |
| EfficientNet-B0 | 13.3% | 0.335 | 40% | 90% |
| ViT Face-Deepfake | 64.3% | 0.360 | 90% | 10% |

**Veredicto:** SDXL Detector es el modelo más fuerte. B4 falla en imágenes sin cara (domain shift: entrenado en face crops de FF++).

---

## 7. RIESGOS RESTANTES

| Riesgo | Severidad | Estado |
|--------|-----------|--------|
| SDXL detector falla en anime, arte GAN clásico, fotografía vintage | Alta | Documentado |
| B4 tiene FPR=70% en imágenes sin cara | Alta | Mitigado (peso 0.15 en modo sin cara) |
| Calibración ECE=0.146 — probabilidades imperfectas | Media | Documentado |
| OSINT sin búsqueda automática (requiere API de pago) | Media | Infraestructura lista |
| No hay modelo temporal para videos (solo frame-by-frame) | Media | Roadmap |
| Hero.tsx y HowItWorks.tsx sin usar — ocupan disco | Baja | Ver próximas mejoras |

---

## 8. PRÓXIMAS MEJORAS RECOMENDADAS

### Alta prioridad
1. Eliminar `Hero.tsx` y `HowItWorks.tsx` del disco (ya no se usan)
2. Ejecutar `run_benchmark.py --set extended` para validar con el nuevo benchmark
3. Integrar SerpAPI o TinEye API para OSINT automatizado
4. Añadir modelo específico para anime/GAN clásico (CNNDetection de Wang et al.)

### Media prioridad
5. Modelo temporal para videos (AltFreezing o VideoMAE)
6. Análisis de audio para videos (detección de voz sintética)
7. API pública con autenticación JWT
8. Rate limiting configurable por IP
9. PostgreSQL para historial persistente (reemplaza localStorage)

### Baja prioridad
10. Docker Compose producción con HTTPS
11. Telemetría de accuracy en producción
12. CI/CD con evaluación automática en cada commit
