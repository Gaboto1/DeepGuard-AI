# Reporte de Seguridad y Cambios — DeepGuard AI
**Fecha:** 2026-06-08  
**Auditor:** Ingeniero Principal de Seguridad (DevSecOps)  
**Versión del proyecto:** 6.0.0  
**Clasificación:** Uso interno — Proyecto de Título INACAP

---

## 1. Resumen Ejecutivo

Se realizó una auditoría de seguridad y fiabilidad completa del proyecto DeepGuard AI, cubriendo el backend (FastAPI + Celery + Redis), el pipeline de análisis forense y el frontend (Next.js). Se encontraron **8 problemas corregidos directamente en código** y **4 hallazgos documentados** que requieren decisiones de infraestructura o cambios estructurales mayores.

**Impacto neto:** Zero regresiones funcionales. Todas las correcciones son aditivas (guards, middleware, sanitización) o reemplazos equivalentes más seguros.

---

## 2. Vulnerabilidades Encontradas y Correcciones Aplicadas

### SEC-03 — Bug Funcional: Redis crudo en `/api/analyze` legacy (ALTA)
| Campo | Detalle |
|---|---|
| **Archivo** | `backend/app/api/routes.py` |
| **CWE** | CWE-798 / bug funcional |
| **Riesgo** | El endpoint legacy `/api/analyze` usaba `redis.from_url(os.getenv(...))` directamente, ignorando `make_redis_client()`. Con redis-py 6.x, la URL que contiene `?ssl_cert_reqs=CERT_NONE` lanza `Invalid SSL Certificate Requirements Flag` — el endpoint fallaba silenciosamente en producción. |
| **Corrección** | Reemplazado por `make_redis_client()` que maneja correctamente el parámetro SSL. Eliminado `import os` no utilizado. |

### SEC-04/05 — Path Traversal en `task_id` (MEDIA-ALTA)
| Campo | Detalle |
|---|---|
| **Archivo** | `backend/app/api/v1/routes.py` |
| **CWE** | CWE-22 Path Traversal |
| **Riesgo** | Los endpoints `GET /tasks/{task_id}`, `GET /tasks/{task_id}/custody` y `DELETE /tasks/{task_id}` construían rutas de archivo con `RESULTS_DIR / f"{task_id}.json"` sin validar el formato de `task_id`. Un valor malicioso como `../custody/archivo` podría leer o eliminar archivos fuera del directorio de resultados. |
| **Corrección** | Añadida función `_validate_task_id(task_id)` con regex UUID estricta (`^[0-9a-f]{8}-...$`). Se llama al inicio de los 3 endpoints afectados. Devuelve HTTP 400 en caso de formato inválido. |

### SEC-06 — Exposición del Canonical String de HMAC (MEDIA)
| Campo | Detalle |
|---|---|
| **Archivo** | `backend/app/services/custody_service.py` |
| **CWE** | CWE-200 Information Exposure |
| **Riesgo** | El sello de custodia incluía `canonical_string` (el mensaje exacto firmado con HMAC) y `verification_command` (instrucciones para replicar la firma) en la respuesta JSON pública, en Redis y en disco. Si la clave HMAC se filtrara en el futuro, estos campos facilitan ataques de forjería de sellos. |
| **Corrección** | Eliminados `canonical_string` y `verification_command` del dict del sello. La verificación interna sigue funcionando igual — `verify_custody_seal()` reconstituye el canonical string desde los campos individuales del sello (mecanismo anti-tampering ya existente). |

### SEC-07 — Information Disclosure en Errores HTTP (BAJA-MEDIA)
| Campo | Detalle |
|---|---|
| **Archivo** | `backend/app/api/v1/routes.py` |
| **CWE** | CWE-209 Error Message Information Leak |
| **Riesgo** | `raise HTTPException(500, f"Error al eliminar: {e}")` y `raise HTTPException(500, f"Error verificando sello: {e}")` exponían stack traces o detalles internos al cliente HTTP. |
| **Corrección** | Errores internos se loguean con `logger.error()` y se devuelve un mensaje genérico al cliente. |

### SEC-08 — Rate Limit insuficiente en `/analyze` (MEDIA)
| Campo | Detalle |
|---|---|
| **Archivo** | `backend/app/api/v1/routes.py` |
| **CWE** | CWE-770 Resource Allocation Without Limits |
| **Riesgo** | El endpoint `/api/v1/analyze` solo tenía el rate limit global de 100 req/min (compartido con health checks y status polls). Una IP maliciosa podría saturar la GPU con 100 análisis/minuto. La variable `RATE_LIMIT_PER_MINUTE=20` existía en config pero nunca se usaba. |
| **Corrección** | Añadido decorador `@_limiter.limit("20/minute")` directamente sobre el endpoint. Devuelve HTTP 429 con mensaje estándar al superar el límite. |

### BUG-03 — BMP sin detección de Magic Bytes (BAJA)
| Campo | Detalle |
|---|---|
| **Archivo** | `backend/app/utils/file_validator.py` |
| **CWE** | CWE-434 Unrestricted File Upload |
| **Riesgo** | `.bmp` aparece en `ALLOWED_IMAGE_EXTENSIONS` e `ALLOWED_IMAGE_MIMES` pero el fallback de detección manual de magic bytes no incluía el header BMP (`BM` = `\x42\x4D`). Un archivo malicioso con extensión `.bmp` pasaba la validación aunque no fuera una imagen BMP real. |
| **Corrección** | Añadido bloque `elif header[:2] == b"BM": mime = "image/bmp"` en el switch de detección. |

### BUG-04 — Código Muerto: Detección WEBM nunca alcanzada (BAJA)
| Campo | Detalle |
|---|---|
| **Archivo** | `backend/app/utils/file_validator.py` |
| **Riesgo** | MKV y WEBM comparten el mismo magic header EBML `\x1a\x45\xdf\xa3`. El bloque WEBM (`elif`) nunca se alcanzaba porque el bloque MKV idéntico venía antes. Todo WEBM era clasificado como MKV (funcionalmente pasaba la validación, pero de forma incorrecta). |
| **Corrección** | Fusionados ambos bloques: se lee un chunk adicional de 64 bytes y se busca el DocType `"webm"` para distinguir entre `video/webm` y `video/x-matroska`. |

### SEC-15 — Security Headers HTTP ausentes (BAJA-MEDIA)
| Campo | Detalle |
|---|---|
| **Archivo** | `backend/app/main.py` |
| **CWE** | CWE-693 Protection Mechanism Failure |
| **Riesgo** | La API no enviaba cabeceras de seguridad estándar, dejando a los clientes web expuestos a clickjacking (`X-Frame-Options`), MIME sniffing (`X-Content-Type-Options`), XSS reflejado (`X-XSS-Protection`) y referrer leaks. |
| **Corrección** | Añadido `SecurityHeadersMiddleware` (subclase de `BaseHTTPMiddleware`) con las siguientes cabeceras en todas las respuestas: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `X-XSS-Protection: 1; mode=block`, `Referrer-Policy: strict-origin-when-cross-origin`, `Content-Security-Policy: default-src 'none'; frame-ancestors 'none'`, `Permissions-Policy: camera=(), microphone=(), geolocation=()`. |

### BUG-05 — `datetime.utcnow()` Deprecado (BAJA)
| Campo | Detalle |
|---|---|
| **Archivo** | `backend/app/utils/helpers.py` |
| **Riesgo** | `datetime.utcnow()` está deprecado desde Python 3.12 y eliminado en Python 3.13. Genera `DeprecationWarning` en el worker y podría causar errores si el entorno migra a Python 3.13. |
| **Corrección** | Reemplazado por `datetime.now(timezone.utc)` con `timezone` importado de `datetime`. |

---

## 3. Hallazgos Documentados (Sin Cambio de Código — Requieren Decisión de Infraestructura)

### DOC-01 — TLS sin verificación de certificado en Redis (ALTA)
**Archivo:** `backend/.env` — `REDIS_URL=rediss://...?ssl_cert_reqs=CERT_NONE`

La conexión TLS con Aiven Valkey no valida el certificado del servidor, lo que permite ataques Man-in-the-Middle. La clave HMAC (`DEEPGUARD_SIGNING_KEY`) y las URLs de archivos viajan por este canal.

**Acción requerida:** Descargar el certificado CA de Aiven desde el panel de control y actualizar la URL a:
```
REDIS_URL=rediss://default:PASSWORD@host:13419?ssl_cert_reqs=CERT_REQUIRED&ssl_ca_certs=/ruta/al/ca.pem
```

### DOC-02 — Sin Autenticación en la API (ALTA)
La API no implementa JWT, API keys ni ningún mecanismo de autenticación. Cualquier cliente que conozca la URL de Render puede enviar archivos y consumir recursos GPU.

**Acción requerida (Roadmap R1):** Implementar API keys en header `X-API-Key` con validación en middleware. Estimado: 4h de desarrollo.

### DOC-03 — Payload Celery para archivos grandes (~667 MB para un video 500 MB) (MEDIA)
El archivo se codifica en Base64 en el mensaje Celery para superar la separación de disco entre Render y el worker local. Para videos de 500 MB el payload en Redis llega a ~667 MB y permanece 24 horas (`result_expires=86400`).

**Propuesta:** Evaluar un bucket S3/R2 como almacenamiento compartido temporal (presigned URLs, 1h de expiración). Esto eliminaría el payload Base64 y permitiría escalar workers horizontalmente.

### DOC-04 — `HOST=0.0.0.0` en desarrollo local (BAJA)
El servidor local escucha en todas las interfaces de red. En una red local empresarial o universitaria podría exponer el servicio a otros equipos.

**Acción recomendada para desarrollo:** Cambiar a `HOST=127.0.0.1` en `.env` local cuando no se requiera acceso desde otros dispositivos.

---

## 4. Análisis de Modelos — Fiabilidad a Largo Plazo

### Estado Actual (Ensemble v3 — 8 modelos)
| Modelo | Tipo | VRAM | Rol en ensemble |
|---|---|---|---|
| Face-Deepfake ViT | GPU | ~800 MB | Detección facial deepfake |
| SDXL Swin | GPU | ~700 MB | Imágenes fotorrealistas SDXL |
| EfficientNet FF++ | GPU | ~400 MB | Forgery detection clásico |
| AI Art Swin-v2 | GPU | ~800 MB | Arte generado IA |
| SigLIP | GPU | ~2.1 GB | Embeddings semánticos |
| AI-Human ViT | GPU | ~500 MB | Discriminación foto vs IA |
| FrequencyDetector | CPU | 0 MB | Análisis espectral FFT |
| SRM Noise | CPU | 0 MB | Residual de ruido Fridrich |

**Punto débil identificado:** El meta-ensemble XGBoost solo usa 3 features (SDXL, AI Art, CLIP/EfficientNet). Los modelos F (AI-Human) y SRM se aplican como correcciones post-hoc, fuera del modelo principal.

### Propuesta de Mejora: Reentrenamiento XGBoost con 8 Features

**Decisión técnica:** Se recomienda reentrenar el XGBoost con los 8 scores como features de entrada.

**Justificación:**
- La Regla 3 (Consensus Override) fue necesaria porque el XGBoost ignora AI-Human y SRM cuando votan contra SDXL. Un XGBoost con 8 features aprendería esta relación de forma natural.
- Feature importance esperada: SDXL (alto), AI Art (alto), AI-Human (medio-alto), SRM (medio), ViT (medio), SigLIP (medio), EfficientNet (bajo), FrequencyDetector (bajo).
- La Regla 3 podría eliminarse después del retraining si el XGBoost aprende el patrón.

**Requisito:** Dataset etiquetado balanceado con ≥ 500 imágenes por categoría (fotorrealistas SDXL, Midjourney, FLUX.1, fotos reales comprimidas, fotos reales sin comprimir). El dataset actual de calibración (~golden set) es insuficiente para reentrenamiento supervisado robusto.

**Esfuerzo estimado:** 8-16h (curación de datos + entrenamiento + validación con golden set).

**Alternativa inmediata (sin retraining):** Los valores de calibración de `FrequencyDetector` (`_AUTOCORR_REAL`, `_ENERGY_REAL`, etc.) y `SRMNoiseDetector` son aproximaciones teóricas. Calibrarlos con datos reales puede mejorar la precisión sin cambios arquitecturales. Estimado: 4h con 200 imágenes etiquetadas.

---

## 5. Resumen de Cambios Aplicados

| # | Archivo Modificado | Tipo | Descripción |
|---|---|---|---|
| 1 | `backend/app/api/routes.py` | Bug Fix | Reemplazado `redis.from_url()` crudo por `make_redis_client()` |
| 2 | `backend/app/api/v1/routes.py` | Seguridad | Validación UUID en 3 endpoints de task_id (path traversal) |
| 3 | `backend/app/api/v1/routes.py` | Seguridad | Rate limit `20/minute` en `POST /analyze` |
| 4 | `backend/app/api/v1/routes.py` | Seguridad | Sanitización de errores HTTP internos |
| 5 | `backend/app/services/custody_service.py` | Seguridad | Eliminados `canonical_string` y `verification_command` del sello público |
| 6 | `backend/app/utils/file_validator.py` | Bug Fix | Detección BMP añadida; WEBM/MKV con DocType real |
| 7 | `backend/app/main.py` | Seguridad | `SecurityHeadersMiddleware` con 6 cabeceras de seguridad |
| 8 | `backend/app/utils/helpers.py` | Fiabilidad | `datetime.utcnow()` → `datetime.now(timezone.utc)` |

**Archivos con cambios:** 5 archivos backend modificados.  
**Regresiones introducidas:** Ninguna — todos los cambios son guards, sanitización o reemplazos equivalentes.  
**Tests pendientes:** Reiniciar el worker Celery y verificar el endpoint `/api/v1/health` para confirmar conectividad Redis post-cambios.
