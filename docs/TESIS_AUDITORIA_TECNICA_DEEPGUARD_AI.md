# DeepGuard AI — Auditoría Técnica y Memoria de Título

**Documentación técnica exhaustiva del sistema, generada mediante análisis estático completo del repositorio**

---

## Portada

| Campo | Valor |
|---|---|
| **Nombre del proyecto** | DeepGuard AI — Sistema Forense de Detección de Deepfakes |
| **Tipo de documento** | Auditoría técnica integral / Memoria de título |
| **Fecha de generación** | 24 de junio de 2026 |
| **Último commit analizado** | `45576f1` (2026-06-12) |
| **Autor del sistema** | Gabriel (repositorio `Gaboto1/DeepGuard-AI`) |
| **Versión del sistema** | v6.0.0 (ensemble de 8 señales + meta-clasificador XGBoost + LLaVA semántico) |
| **Líneas de código backend (`app/`)** | ~6.091 líneas Python |
| **Archivos fuente (backend + frontend)** | 49 archivos `.py`/`.tsx`/`.ts` en `app/` y `src/` |
| **Repositorios externos consumidos** | 5 modelos de HuggingFace Hub + LLaVA-1.5-7b-hf |

---

## 1. Resumen Ejecutivo

### 1.1 Descripción general

DeepGuard AI es un sistema de detección forense de contenido generado o manipulado por inteligencia artificial (deepfakes), que opera sobre imágenes y video. A diferencia de un clasificador binario tradicional ("real" vs. "falso"), el sistema fue diseñado deliberadamente bajo un paradigma de **evidencia forense graduada**: combina nueve señales de análisis (seis modelos de visión basados en transformers, más tres detectores de señal clásica sin GPU — análisis espectral de frecuencia, residuos de ruido SRM y Error Level Analysis), un meta-clasificador estadístico (XGBoost con calibración de temperatura), cuatro reglas de corrección forense basadas en casos de fallo reales documentados durante el desarrollo, un módulo de inspección semántica mediante un modelo de lenguaje visual (LLaVA-1.5-7b-hf cuantizado a 4 bits), extracción de metadatos EXIF/XMP/IPTC, verificación de procedencia C2PA, y una cadena de custodia criptográfica (SHA-256 + HMAC-SHA256) que sella cada resultado para fines de trazabilidad legal.

El sistema se despliega bajo una **arquitectura híbrida nube + GPU local**: el frontend (Next.js) se sirve de forma estática desde Netlify, la API (FastAPI) corre en Render sin ninguna dependencia de PyTorch ni GPU, y el cómputo pesado de inferencia ocurre en un equipo personal con una GPU NVIDIA RTX 4070 SUPER, conectado a la API mediante una cola de mensajes Celery sobre Redis administrado (Aiven Valkey). Esta decisión de arquitectura responde a una restricción presupuestaria explícita: evitar el costo de GPU en la nube (estimado en USD 350-730/mes en AWS/GCP/Azure según la documentación histórica del proyecto) sin sacrificar la disponibilidad pública del servicio.

### 1.2 Objetivos

El objetivo general del proyecto es **construir y operar un sistema de detección de deepfakes desplegable en producción, con grado de evidencia forense (no un veredicto binario), capaz de operar dentro de las restricciones de un plan gratuito de hosting cloud**, manteniendo la capacidad de cómputo de IA mediante hardware propio.

Los objetivos específicos verificables en el código y la documentación incluyen: (a) maximizar la cobertura de generadores de imagen modernos (Midjourney, SDXL, FLUX, DALL-E, Ideogram) mediante un ensemble de modelos especializados; (b) minimizar falsos positivos sobre fotografía real comprimida o de estilo antiguo, un problema documentado repetidamente a lo largo de las seis fases de evolución del proyecto; (c) proveer trazabilidad y explicabilidad de cada veredicto (desglose de contribución por modelo, mapas de calor Grad-CAM++, explicación textual generada); y (d) garantizar la integridad de la cadena de custodia de cada análisis mediante firma criptográfica.

### 1.3 Alcance

Este documento cubre el análisis técnico completo del repositorio tal como existe en el commit `45576f1`: los nueve módulos de inferencia y corrección forense del backend, los diez servicios de orquestación, la capa de API (dos generaciones de endpoints, `/api/*` legacy y `/api/v1/*` enterprise), la infraestructura Celery/Docker/Redis, los veinte componentes/archivos del frontend Next.js, y la síntesis crítica de once documentos de auditoría y reportes técnicos previos generados durante las seis fases de evolución documentadas del proyecto (mayo-junio de 2026). No se incluye un análisis de los scripts de entrenamiento (`scripts/`) ni de los notebooks de calibración, que están fuera del sistema en producción.

### 1.4 Principales hallazgos

El sistema exhibe un nivel de madurez de ingeniería notablemente alto para un proyecto de título: existe una auditoría de seguridad formal previa con nomenclatura CWE (ocho vulnerabilidades corregidas, cuatro documentadas como deuda pendiente), decisiones de arquitectura explícitamente justificadas con datos cuantitativos, y un historial de iteración basado en evidencia (cada corrección forense documenta un caso real con números concretos). Sin embargo, este análisis identifica una serie de hallazgos no documentados previamente que se detallan en la Sección 13 ("Problemas Detectados"), de los cuales el más relevante es una inconsistencia funcional en el componente `ForensicPanel.tsx` del frontend, que presenta un sello de "Contenido Auténtico — VÁLIDO" de forma incondicional, sin relación con el resultado real del análisis — un riesgo de comunicación potencialmente engañoso en un sistema de propósito forense.

---

## 2. Introducción

### 2.1 Contexto del proyecto

La proliferación de modelos generativos de imagen (difusión latente: Stable Diffusion/SDXL, Midjourney, FLUX, DALL-E, Ideogram) ha alcanzado, hacia 2025-2026, un nivel de fotorrealismo que el World Economic Forum y diversos estudios de percepción humana citan como indistinguible para el ojo humano en más de la mitad de los casos (tasa de acierto humano documentada como inferior al 50% en `docs/INFORME_TECNICO_DEEPGUARD_AI.md`). Este contexto motiva la necesidad de herramientas automatizadas de verificación que no dependan del juicio humano no asistido.

### 2.2 Problema que resuelve

El sistema aborda dos problemas simultáneos: (1) la detección técnica de contenido sintético o manipulado, y (2) la comunicación responsable de esa detección. El segundo problema es tan relevante como el primero en el diseño del sistema: la documentación histórica del proyecto (`docs/REPORT_FORENSIC_UPGRADE.md`) registra un cambio deliberado de filosofía, abandonando los veredictos binarios "REAL/FAKE" en favor de un esquema de cinco niveles de evidencia (`VERY_LOW` a `STRONG`), exactamente para evitar la sobre-afirmación (*overclaiming*) en un dominio donde un falso positivo o negativo puede tener consecuencias legales o reputacionales.

### 2.3 Justificación

La elección de una arquitectura de ensemble múltiple con corrección por reglas de dominio (en lugar de un único modelo de clasificación end-to-end) se justifica por evidencia empírica documentada en el propio repositorio: el primer detector evaluado individualmente (`EfficientNet-B0` entrenado solo en FaceForensics++) mostró un F1 de apenas 13.3% sobre el conjunto de validación interno (golden set) frente a contenido generado por difusión moderna — los detectores especializados en *face-swap* clásico no generalizan a generadores de imagen completos. La estrategia de combinar múltiples especialistas, cada uno fuerte en un subdominio distinto, mitiga esta falta de generalización individual.

### 2.4 Objetivos generales y específicos

Ya enunciados en la Sección 1.2; se reitera aquí que el objetivo de "operar bajo presupuesto cero de infraestructura GPU" no es un detalle incidental sino una restricción de diseño de primer orden que determina directamente la arquitectura híbrida descrita en la Sección 4.

---

## 3. Análisis General del Proyecto

### 3.1 Descripción completa

DeepGuard AI procesa dos tipos de entrada — imágenes (JPG/PNG/WEBP/BMP) y video (MP4/MOV/MKV/WEBM) — a través de un pipeline de hasta once etapas (ver Sección 6.11 para el flujo completo citado por archivo y línea): cómputo de hash SHA-256, verificación de procedencia C2PA, extracción de metadatos forenses, detección de contenido fuera de dominio (afiches/diseño gráfico), detección y recorte de rostro, inferencia paralela de seis modelos de visión, tres señales de análisis clásico sin GPU, combinación mediante meta-clasificador y reglas de corrección, inspección semántica por modelo de lenguaje visual, generación de explicación narrativa, y sellado criptográfico del resultado final.

### 3.2 Funcionalidades principales

- Análisis de imagen individual con mapa de calor Grad-CAM++ de las regiones que influyeron en la decisión.
- Análisis de video frame-by-frame con línea de tiempo de probabilidad y detección de inconsistencia temporal (flujo óptico de Farneback + discrepancia coseno entre embeddings ViT consecutivos).
- Verificación de cadena de custodia forense, consultable de forma independiente vía endpoint dedicado (`GET /api/v1/tasks/{id}/custody`).
- Panel de verificación OSINT (enlaces de búsqueda inversa manual + hash perceptual), sin pretender una verificación automatizada contra bases de datos de noticias.
- Historial de análisis persistido en el navegador (localStorage), sin servidor de persistencia de usuario.

### 3.3 Casos de uso

El sistema está orientado a tres perfiles de uso, inferidos de las decisiones de diseño documentadas: (a) periodistas o verificadores de hechos que necesitan una primera señal de alerta sobre una imagen sospechosa antes de una verificación manual exhaustiva; (b) usuarios técnicos/académicos (el contexto de "memoria de título" del propio repositorio) que requieren explicabilidad del proceso de decisión; y (c) un eventual uso pericial/legal, sugerido por la existencia de la cadena de custodia HMAC-SHA256 y el endpoint de verificación independiente — aunque el sistema no implementa autenticación ni control de acceso, lo cual limita su aptitud real para un caso de uso legal sin una capa adicional de control.

### 3.4 Usuarios objetivo

No existe un sistema de roles, cuentas o permisos en el código revisado — el sistema es de acceso público sin autenticación (ver Sección 11.7). El "usuario objetivo" se infiere por diseño de UX: una persona no técnica que sube un archivo y necesita una explicación narrativa en español comprensible, complementada con paneles de detalle técnico (Ensemble, Metadatos, Verificación, Procedencia C2PA) para quien desee profundizar.

### 3.5 Valor que aporta

El valor diferencial documentado del sistema, frente a una solución de un solo modelo, es la **resiliencia ante el sesgo individual de cada detector**: la auditoría de mayo de 2026 (`docs/REPORT_NEXT_GEN_UPGRADE.md`) documenta un caso real donde dos de los seis modelos de visión (ViT base y SigLIP) alcanzan una tasa de falsos positivos de 96.5% y 100% respectivamente sobre el conjunto de validación — es decir, considerados aisladamente, dos de los seis "expertos" del ensemble son casi inútiles o contraproducentes. El meta-clasificador y el "veto de consenso" (Sección 6.5) existen precisamente para neutralizar este sesgo sin necesidad de eliminar esos modelos del sistema (se mantienen visibles en la interfaz por transparencia, pero excluidos del cómputo del score final).

---

## 4. Arquitectura del Sistema

### 4.1 Arquitectura identificada

La arquitectura general es de **microservicios desacoplados con cómputo distribuido asíncrono**, también descrita en la documentación del proyecto como "arquitectura híbrida nube + GPU local". No es una arquitectura monolítica, ni serverless pura, ni microservicios en el sentido de descomposición por dominio de negocio — es más precisamente un patrón **productor/consumidor (cola de mensajes) con un productor ligero en la nube y un consumidor pesado en hardware propio**.

### 4.2 Patrones arquitectónicos utilizados

| Patrón | Dónde se aplica | Evidencia en código |
|---|---|---|
| **Cola de mensajes (Producer/Consumer)** | API despacha a Celery, worker GPU consume | `backend/app/celery_app.py`, `backend/app/tasks/analysis_tasks.py` |
| **Strangler / API Gateway dual** | Coexistencia de `/api/*` legacy y `/api/v1/*` enterprise en el mismo proceso | `backend/app/main.py:125-126` |
| **Circuit breaker manual / Graceful degradation** | `sync_fallback` cuando Celery/Redis no está disponible en modo local | `backend/app/api/v1/routes.py` función `_process_sync_fallback` |
| **Singleton** | Todos los detectores ML y servicios pesados (`DeepfakeDetector`, `MetaEnsemble`, `FaceDetector`, `ELADetector`, etc.) | `get_instance()` en cada módulo de `backend/app/models/` |
| **Chain of Responsibility / Reglas mutuamente excluyentes** | Las 4 reglas de corrección forense, evaluadas en orden hasta la primera que aplica | `backend/app/utils/forensic_corrections.py:151-291` |
| **Cascada de resiliencia (fallback en capas)** | Lectura de estado de tarea: Redis → disco → estado `pending` por defecto, nunca `None` | `backend/app/api/v1/routes.py`, función `_get_task_result` |
| **Heartbeat / Health check activo** | Verificación de disponibilidad del worker GPU vía clave Redis con TTL, en lugar de `celery inspect ping` | `backend/app/tasks/analysis_tasks.py` (hilo `_heartbeat_loop`), consumido en `backend/app/api/v1/routes.py:502-529` |
| **Strategy / Calibración adaptativa** | Selección de constantes de calibración según formato de imagen (lossy/lossless) en el detector de frecuencia | `backend/app/models/frequency_detector.py:44-58` |
| **Export estático (JAMstack)** | Frontend compilado a HTML/CSS/JS puro sin servidor Node en producción | `frontend/next.config.js` (`output: 'export'`) |

### 4.3 Diagrama de arquitectura (despliegue)

```
                         Usuario (navegador)
                                │
                                ▼
                    ┌───────────────────────┐
                    │   Netlify CDN          │   Frontend estático
                    │   Next.js export        │   (Sin servidor Node)
                    └───────────┬───────────┘
                                │ HTTPS
                                │ POST /api/v1/analyze
                                │ GET  /api/v1/tasks/{id}
                                ▼
                    ┌───────────────────────┐
                    │   Render (cloud)        │   FastAPI, API_ONLY=true
                    │   ~180MB imagen Docker  │   Sin PyTorch/CUDA
                    │   RAM < 100MB           │   Solo valida y despacha
                    └───────────┬───────────┘
                                │ Celery dispatch
                                │ (payload Base64 del archivo)
                                ▼
                    ┌───────────────────────┐
                    │   Aiven Valkey (TLS)    │   Broker Redis administrado
                    │   Cola de prioridad     │   images (prio 10) / videos (prio 5)
                    └───────────┬───────────┘
                                │ Task received
                                │ Heartbeat cada 30s (TTL 90s)
                                ▼
                    ┌───────────────────────┐
                    │   PC Local              │   Worker Celery, --concurrency=1
                    │   RTX 4070 SUPER 12GB   │   9 señales + meta-ensemble + LLaVA
                    │   ~6.8GB VRAM en uso    │   Devuelve resultado vía Redis
                    └───────────────────────┘
```

### 4.4 Flujo de información — pipeline forense completo (imagen)

El flujo se reconstruye con precisión archivo:línea a partir del análisis del código (orquestado en `backend/app/services/image_service.py` y `backend/app/tasks/analysis_tasks.py`):

1. **Recepción y validación** (`api/v1/routes.py:233-371`): valida extensión, tamaño, magic bytes reales (no solo extensión), calcula tiempo estimado, codifica el archivo completo en Base64 dentro de un thread pool dedicado para no bloquear el event loop async.
2. **Despacho a Celery** con `task_id = uuid.uuid4()`, payload incluyendo `file_content_b64` — necesario porque la API (Render) y el worker (PC local) no comparten sistema de archivos.
3. **Reconstrucción del archivo en el worker** (`tasks/analysis_tasks.py:122-296`): decodifica el Base64 y escribe a disco local del worker.
4. **SHA-256 + lectura C2PA pre-neural** (0 VRAM, límite de 100MB de lectura).
5. **Extracción de metadatos EXIF/XMP/IPTC** con detección de firmas de generadores IA conocidas.
6. **Detección OOD** (`models/ood_detector.py:141-222`): cinco señales heurísticas (densidad de bordes Canny, regularidad de texto, compacidad de paleta, píxeles extremos HSV, regiones uniformes 64×64) combinadas con pesos fijos más una regla dura (≥85% píxeles extremos fuerza `ood_score ≥ 0.60`).
7. **Detección de rostro** (MTCNN, margen 15%, confianza mínima 90%).
8. **Señales auxiliares CPU** (una vez sobre la imagen completa): frecuencia espectral FFT (`models/frequency_detector.py`), residuos de ruido SRM (`models/srm_detector.py`), Error Level Analysis (`models/ela_detector.py`).
9. **Inferencia de los seis modelos transformer + combinación meta** (`models/deepfake_detector.py:338-424`, `models/meta_ensemble.py:162-230`), ejecutada dos veces si hay rostro (imagen completa y recorte facial), fusionadas 60/40 a favor del rostro.
10. **Penalización OOD** (tracción hacia 0.5 proporcional a la confianza OOD).
11. **Cuatro reglas de corrección forense** (Sección 6.6), mutuamente excluyentes.
12. **Inspección semántica LLaVA** y fusión calibrada (Sección 6.2.3).
13. **Generación de explicación narrativa** (`utils/helpers.py:117-230`) y sellado de custodia HMAC-SHA256.
14. **Persistencia en disco** (`reports/tasks/`, `reports/custody/`) y liberación del archivo subido tras el periodo de retención configurado.

### 4.5 Comunicación entre módulos

La comunicación es predominantemente **síncrona dentro del proceso worker** (llamadas a función directas entre `image_service.py` y los módulos de `models/`/`utils/`) y **asíncrona entre la API y el worker** (Celery sobre Redis, con serialización JSON exclusiva — sin pickle, mitigando deserialización insegura). No existe comunicación directa entre el frontend y el worker GPU: todo pasa por la API, que actúa como única puerta de entrada.

---

## 5. Tecnologías Utilizadas

| Tecnología | Qué es | Por qué se usa | Ventajas | Desventajas | Función en el proyecto |
|---|---|---|---|---|---|
| **FastAPI** | Framework web Python async | Soporta async/await nativo, validación Pydantic integrada, documentación OpenAPI automática | Alto rendimiento I/O-bound, tipado fuerte, ecosistema maduro | Sin built-in de autenticación/autorización, requiere middleware propio | Expone los endpoints `/api/*` y `/api/v1/*`, valida entradas, despacha tareas |
| **Celery** | Sistema de colas de tareas distribuidas | Permite desacoplar la API (ligera) del cómputo GPU (pesado) en máquinas distintas | Reintentos, colas con prioridad, resultado persistente, maduro y ampliamente documentado | Requiere broker externo (Redis), serialización añade overhead, debugging distribuido más complejo | Transporta las tareas de análisis desde Render hasta el worker GPU local |
| **Redis (Aiven Valkey)** | Almacén clave-valor en memoria | Actúa como broker y backend de resultados de Celery, y como canal de heartbeat | Latencia baja, soporta pub/sub y TTL nativo | Sin persistencia garantizada salvo configuración explícita; en este proyecto los resultados también se persisten en disco como respaldo | Cola de tareas, almacenamiento temporal de resultados, heartbeat del worker |
| **PyTorch + CUDA 12.4** | Framework de deep learning con aceleración GPU | Es el estándar de facto para correr modelos HuggingFace de visión | Ecosistema HuggingFace completo, soporte CUDA maduro | Footprint de memoria alto, no apto para el plan gratuito de Render (de ahí `API_ONLY`) | Motor de inferencia de los 6 modelos transformer y LLaVA |
| **Transformers (HuggingFace)** | Librería de modelos pre-entrenados | Permite cargar y combinar múltiples arquitecturas (ViT, Swin, SigLIP, CLIP) con una API uniforme | Ahorra entrenamiento desde cero, comunidad activa de modelos de detección de IA | Dependencia de disponibilidad de los repos remotos en tiempo de ejecución, sin pinning de versión/hash en el código revisado | Carga de los 5 modelos de clasificación de imagen del ensemble |
| **XGBoost** | Gradient boosting sobre árboles | Meta-clasificador que combina 3 features confiables del ensemble con baja varianza | Robusto a overfitting con `max_depth=2`, soporta regularización L1/L2, rápido en CPU | Requiere reentrenamiento manual si cambia la distribución de los modelos base | Meta-ensemble que determina el score final antes de las correcciones forenses |
| **OpenCV (`cv2`)** | Visión por computador clásica | Detección de bordes (Canny), conversión de espacio de color (HSV) | Muy rápido, sin necesidad de GPU | Dependencia de sistema (`libGL`) en algunos entornos; el código la trata como opcional con fallback | Señales del detector OOD (afiches/diseño gráfico) |
| **SciPy** | Computación científica | Convolución 2D eficiente para los filtros SRM | Implementación en C, mucho más rápida que un loop Python puro | El propio código mantiene un *fallback* manual de doble loop si SciPy no está disponible — explícitamente reconocido como "extremadamente lento" | Filtros de paso alto del detector de residuos de ruido SRM |
| **facenet-pytorch (MTCNN)** | Detección de rostros | Permite el modo de análisis dual cara/imagen completa | Ligero, rápido, ampliamente usado | Import diferido por ser dependencia opcional | Detección y recorte de rostro con margen del 15% |
| **bitsandbytes** | Cuantización de modelos | Permite ejecutar LLaVA-1.5-7b-hf en 4-bit NF4, reduciendo el uso de VRAM de ~14GB a ~6.8GB | Hace viable un modelo de 7B parámetros en una GPU de consumo de 12GB | Pérdida marginal de precisión por la cuantización; mayor latencia de carga inicial | Cuantización del modelo de lenguaje visual para inspección semántica |
| **Next.js 14 (App Router)** | Framework React con SSR/SSG | `output: 'export'` permite generar un sitio 100% estático, ideal para Netlify | Sin servidor Node en producción, despliegue gratuito vía CDN | Pierde funcionalidades de SSR/Image Optimization/API Routes | Toda la interfaz de usuario del sistema |
| **TypeScript (strict)** | Superset tipado de JavaScript | Modela el dominio forense con tipos ricos (niveles de evidencia, consenso, fusión semántica) | Detección de errores en compile-time, autocompletado | El modo `strict` no protege contra los *casts* (`as AnalysisResult`) que el propio código usa para evitar validación runtime del contrato con el backend | Tipado de todo el frontend |
| **Tailwind CSS + Framer Motion** | Utilidades CSS + animación declarativa | Permite construir rápidamente una UI consistente con la paleta "terminal forense" | Desarrollo rápido, animaciones fluidas | Riesgo de duplicar la fuente de verdad del color si se combina con CSS vars e inline styles (ocurre en este proyecto, ver Sección 12) | Estilo visual y micro-interacciones de la interfaz |
| **Recharts** | Librería de gráficos React (SVG) | Visualiza la línea de tiempo de probabilidad por frame en análisis de video | Declarativo, se integra bien con React | Una dependencia adicional para un solo gráfico | `AreaChart` del timeline de video en `ResultCard.tsx` |
| **Docker** | Contenedores | Empaqueta la API para despliegue reproducible en Render | Reproducibilidad, aislamiento de dependencias | El mismo Dockerfile (diseñado explícitamente "sin GPU/torch") se reutiliza para el servicio `worker` en `docker-compose.prod.yml`, una inconsistencia documentada en la Sección 13 | Imagen de despliegue de la API ligera |
| **Nginx** | Servidor web / proxy reverso | Reverse proxy para el despliegue Docker alternativo (no usado en el despliegue real Netlify+Render) | Maduro, eficiente, soporta TLS terminación | Bloque HTTPS comentado por defecto en el `nginx.conf` del repo — requiere configuración manual | Proxy entre frontend y backend en el `docker-compose.prod.yml` |

---

## 6. Estructura del Repositorio y Análisis del Código Fuente

> Esta sección consolida el análisis carpeta por carpeta y archivo por archivo. Por la magnitud del código (~6.100 líneas en `backend/app/`), se reporta cada módulo con su propósito, lógica clave (citando archivo:línea), y se reserva la discusión transversal de fortalezas/debilidades para la Sección 11 (Calidad del Código) y Sección 13 (Problemas Detectados), evitando duplicar el contenido.

### 6.1 Árbol de directorios (resumen funcional)

```
PROYECTO TITULO FINAL/
├── backend/
│   ├── app/
│   │   ├── api/              → Capa HTTP: routes.py (legacy), v1/routes.py (enterprise), schemas.py
│   │   ├── models/            → 7 módulos de inferencia ML/forense (ver 6.2)
│   │   ├── services/          → 10 servicios de orquestación de dominio (ver 6.3)
│   │   ├── tasks/              → analysis_tasks.py: lógica real ejecutada en el worker Celery
│   │   ├── utils/              → forensic_corrections.py, helpers.py, file_validator.py
│   │   ├── celery_app.py       → Configuración de colas, reintentos, timeouts
│   │   ├── config.py            → Settings centralizadas (Pydantic)
│   │   └── main.py              → Entry point FastAPI, middleware, lifespan
│   ├── requirements.txt / requirements-api.txt   → deps completas (GPU) vs ligeras (Render)
│   └── Dockerfile               → Imagen API-only ~180MB
├── frontend/
│   ├── src/app/                 → layout.tsx, page.tsx (SPA de una sola pantalla)
│   ├── src/components/          → 11 componentes (ver 6.4)
│   ├── src/lib/api.ts            → Único cliente HTTP del sistema
│   └── src/types/index.ts        → Modelo de dominio TypeScript (~220 líneas)
├── docs/                        → 11 documentos de auditoría/evolución histórica
├── docker-compose.yml / .prod.yml → Topología local (2 servicios) vs producción (6 servicios)
├── INICIAR LOCAL.bat / INICIAR PAGINA WEB.bat → únicos 2 scripts de arranque en la raíz
├── tools/, scripts/               → generadores de informes y scripts de entrenamiento/benchmark
└── tests/                        → manifiestos de datasets de benchmark (golden_set, extended, massive)
```

### 6.2 Módulo `backend/app/models/` — Señales de inferencia

#### 6.2.1 `deepfake_detector.py` (525 líneas) — núcleo del ensemble GPU

Define la clase wrapper genérica `_HFModel` (líneas 108-221) que envuelve modelos `AutoModelForImageClassification` de HuggingFace con **fallback en cascada** (lista de repos candidatos) y normalización de etiquetas heterogéneas (`_parse`, línea 144) mapeando contra conjuntos globales `FAKE_LABELS`/`REAL_LABELS`. Seis modelos se cargan bajo esta interfaz: A (`prithivMLmods/Deep-Fake-Detector-v2-Model`, ViT), B (`Organika/sdxl-detector`, Swin), C (`Xicor9/efficientnet-b0-ffpp-c23`), D (`haywoodsloan/ai-image-detector-deploy`, Swin v2), E (`prithivMLmods/Deepfake-Detect-Siglip2`), y una sexta clase, `_EfficientNetFF` (líneas 228-320), que a pesar de su nombre histórico implementa en realidad **CLIP ViT-L/14 + regresión logística calibrada** (metodología *UniversalFakeDetect*, Ojha et al. 2023) — un caso de naming engañoso/deuda técnica detectado en este análisis.

La función central `_calibrated_combine` (líneas 338-424) delega el cálculo del score base al meta-ensemble (Sección 6.2.5) y aplica, secuencialmente, hasta cuatro correcciones acotadas (*alpha cap*) basadas en la discrepancia entre cada señal auxiliar y el score combinado: corrección F(AI-Human)+frecuencia si discrepancia > 0.20 (peso máximo 0.18), corrección SRM si discrepancia > 0.25 (peso máximo 0.10), corrección conjunta F+SRM si ambos superan 0.72/0.65 simultáneamente (peso máximo 0.20), y corrección ELA si discrepancia > 0.22 (peso máximo 0.08, la más conservadora). Cada corrección es una mezcla convexa `combined = combined·(1-α) + señal·α`.

Los pesos estáticos `_W_NO_FACE`/`_W_FACE` (líneas 102-103) **no determinan el score real** — se usan únicamente para construir el desglose visual (`EnsembleBreakdown`) que ve el usuario en la pestaña "Ensemble"; el score real proviene del meta-modelo XGBoost. Esta separación entre "pesos mostrados" y "pesos efectivos" es un hallazgo de diseño relevante: la transparencia visual no es un reflejo literal del cálculo interno.

Se detectó además una inconsistencia funcional: el método público `DeepfakeDetector.predict()` (línea 466) no incluye el modelo F en su llamada a `_calibrated_combine`, mientras que `predict_batch()` (línea 489) sí lo hace — ambos coexisten en la misma clase con comportamiento divergente, aunque el pipeline real de producción (`image_service.py`) no usa ninguno de los dos directamente sino su propia orquestación.

#### 6.2.2 `ela_detector.py` (182 líneas) — Error Level Analysis

Implementa la técnica forense clásica de Krawetz (2007): re-comprime la imagen en JPEG a calidad fija (`_ELA_QUALITY=75`, línea 58) y mide la diferencia píxel a píxel con el original. Combina tres sub-señales normalizadas por interpolación lineal entre puntos de calibración empíricos (medias REAL=0.030/AI=0.010, desviación REAL=0.024/AI=0.006, coeficiente de variación entre parches REAL=0.60/AI=0.18): `fake_prob = 0.35·mean_score + 0.50·std_score + 0.15·patch_score` (línea 122-145). Es una señal puramente CPU (sin PyTorch), con manejo explícito del caso degenerado de imagen plana.

#### 6.2.3 `face_detector.py` (105 líneas) — MTCNN

Detección y recorte de rostro con `min_face_size=30`, umbrales en cascada `[0.6, 0.7, 0.7]`, filtro de confianza mínima 90%, margen del 15% alrededor del bounding box y orden por área descendente (línea 49-96). Import diferido de `facenet-pytorch` con manejo de `ImportError` para degradar elegantemente sin esta dependencia.

#### 6.2.4 `frequency_detector.py` (243 líneas) — análisis espectral FFT

Basado en la teoría de que las imágenes naturales siguen una ley de potencia `S(f) ∝ f^(-α)` con `α≈2.0`, mientras GANs/difusión generan anomalías espectrales. Implementa **calibración adaptativa dual** según el formato detectado (líneas 44-58): para JPEG/WEBP (con pérdida), `α_REAL=1.55`/`α_AI=1.15`; para PNG/BMP/TIFF (sin pérdida), `α_REAL=1.80`/`α_AI=1.35` — reconociendo que la compresión JPEG distorsiona el espectro natural. Combina exponente espectral, proporción de alta frecuencia y anisotropía entre cuadrantes: `fake_prob = 0.50·α_score + 0.35·hf_score + 0.15·aniso_score` (línea 169-200).

#### 6.2.5 `meta_ensemble.py` (240 líneas) — meta-clasificador XGBoost

El módulo más crítico desde el punto de vista de la calidad de la decisión final. Define explícitamente `RELIABLE_META_FEATURES = ["sdxl_detector", "ai_art_detector", "efficientnet_ffpp"]` (líneas 42-46), excluyendo deliberadamente ViT (FPR documentado de 96%) y SigLIP (FPR documentado de 100%) del cómputo del meta-modelo, aunque ambos permanecen visibles en la UI por transparencia. Implementa **temperature scaling** (`_apply_temperature`, línea 115, transformación logit estándar) y un **veto de consenso** (`_consensus_veto`, líneas 124-160): si la media de los modelos "robustos" (SDXL + AI-Art) es menor a `VETO_THRESHOLD=0.25` y el meta-modelo discrepa en más de `VETO_MIN_DISCREPANCY=0.35`, el resultado final se recalcula como `robust_mean·0.60 + meta_prob·0.40`. El docstring documenta el caso real que motivó esta regla: una imagen con SDXL=0.01/AI_Art=0.10 (media 0.055) que el meta-modelo, contaminado por la correlación espuria de ViT/SigLIP, puntuaba en 0.68 — el veto la corrige a 0.27.

#### 6.2.6 `ood_detector.py` (248 líneas) — detección fuera de dominio

Cinco señales funcionales puras (sin estado): densidad de bordes Canny, regularidad de texto (periodicidad de proyección horizontal), compacidad de paleta de color, fracción de píxeles extremos en saturación HSV, y fracción de regiones uniformes en bloques de 64×64. Combinadas con pesos `[0.25, 0.15, 0.15, 0.25, 0.20]` respectivamente contra un umbral `OOD_THRESHOLD=0.43` (bajado desde 0.52 según el comentario del código, para capturar mejor diseños reales), más una regla dura que fuerza `ood_score ≥ 0.60` si los píxeles extremos superan el 85%. La penalización resultante (`apply_ood_penalty`) atrae el score hacia 0.5 (máxima incertidumbre), nunca hacia "real" — una decisión de diseño conservadora correcta.

#### 6.2.7 `srm_detector.py` (248 líneas) — residuos de ruido (Steganalysis Rich Models)

Tres filtros de paso alto (Fridrich & Kodovsky 2012) aplicados sobre el canal de luminancia, combinando autocorrelación de lag 1, energía del residuo y desviación de curtosis gaussiana: `fake_prob = 0.50·autocorr + 0.30·energy_inv + 0.20·kurt_dev`. Mantiene un *fallback* manual (doble loop Python puro) si SciPy no está disponible — funcionalmente correcto pero de rendimiento muy pobre en imágenes grandes, un riesgo identificado en la Sección 11.

#### 6.2.8 `utils/forensic_corrections.py` (327 líneas) — reglas de dominio post-hoc

El módulo mejor documentado del repositorio: cada una de las cuatro reglas (OOD-Manipulation Bypass, Compression Veto, Consensus Override, F+SRM Signal Alignment) incluye en su docstring el problema que resuelve, la condición exacta, la fórmula, y **un caso real verificable con números concretos** (la imagen del club deportivo Cobreloa para la Regla 1, una fotografía de Lionel Messi comprimida por redes sociales para la Regla 2, un retrato generado en Midjourney para la Regla 3, y un caso de alineación F+SRM para la Regla 4). Las reglas son mutuamente excluyentes por construcción (`return` inmediato al cumplirse la primera condición), lo cual simplifica el razonamiento pero implica que, si dos condiciones se cumplen simultáneamente, solo la de mayor prioridad en el orden del código se aplica — una decisión de diseño implícita, no declarada como tal en los comentarios.

#### 6.2.9 `utils/helpers.py` (231 líneas) — capa de interpretación

Convierte la probabilidad numérica final en `EvidenceLevel` (5 niveles por umbral fijo), `ModelAgreement` (consenso por desviación estándar) y `UncertaintyLevel` (combinación de entropía normalizada y desviación estándar), y genera el párrafo explicativo final en español. Diseñado explícitamente para **nunca afirmar "real" o "falso" en términos absolutos** (comentario línea 26), coherente con el cambio de filosofía documentado en la Sección 2.2. Se identificó que el diccionario de nombres legibles de modelos (`_NOMBRES_MODELO`, líneas 103-114) no incluye los nombres de las señales más nuevas (`ai_human_detector`, `frequency_spectral`, `srm_noise_detector`, `ela_detector`), generando una explicación menos legible para esas señales si llegan a mostrarse vía esta función.

### 6.3 Módulo `backend/app/services/` — orquestación de dominio

| Servicio | Responsabilidad | Hallazgo clave |
|---|---|---|
| `analysis_service.py` (327 líneas) | Orquestador del modo legado/background-task de FastAPI; mantiene estado de tareas **en memoria de proceso** (`dict` protegido por `asyncio.Lock`) | No persiste entre reinicios ni se comparte entre workers — limitación de diseño explícita frente al pipeline Celery, que sí persiste en Redis/disco |
| `image_service.py` | Orquestador real del pipeline de imagen (ver flujo completo en Sección 4.4) | Es el módulo que efectivamente determina el score final en producción |
| `video_service.py` / `video_temporal_service.py` | Pipeline de video frame-by-frame; consistencia temporal vía embeddings ViT de 768D + flujo óptico de Farneback | Implementa lo que documentos de auditoría anteriores (`SYSTEM_AUDIT_V4.md`) señalaban como ausente ("sin modelo temporal para video") — evidencia de que se resolvió entre v4 y v6 |
| `semantic_inspection_service.py` | Carga LLaVA-1.5-7b-hf cuantizado 4-bit NF4 y aplica `apply_semantic_fusion()` con 3 casos: `correction_up`, `correction_down`, `compression_zone` | Añade ~6.8GB de VRAM adicional; degrada a "ensemble sin corrección semántica" si no está disponible |
| `custody_service.py` | Genera y verifica el sello de cadena de custodia v2 (SHA-256 + HMAC-SHA256) | Tras la auditoría de seguridad previa (SEC-06), ya no expone el *canonical string* públicamente, mitigando forjería |
| `forensic_metadata_service.py` / `metadata_service.py` | Extracción EXIF/XMP/IPTC y detección de firmas de generadores IA en metadatos | Señal complementaria que se fusiona al score (`apply_metadata_risk_to_score`) sin sobreescribirlo |
| `osint_service.py` | Hash perceptual + enlaces de búsqueda inversa manual | Siempre marca `status="manual_review_required"` — no realiza búsqueda automatizada (decisión documentada, no una limitación oculta) |
| `c2pa_service.py` | Lectura del estándar C2PA (Coalition for Content Provenance and Authenticity) | Verificación criptográfica de procedencia, independiente del ensemble de IA |

### 6.4 Módulo `frontend/src/components/`

El frontend se compone de 11 componentes especializados más el cliente HTTP único (`lib/api.ts`) y el archivo de tipos central (`types/index.ts`, ~220 líneas). El componente más complejo es `ResultCard.tsx` (596 líneas), que implementa un medidor circular SVG hecho a mano (`SegmentedGauge`, 48 segmentos discretos) y delega secciones especializadas a `ForensicPanel`, `MetadataPanel`, `OsintPanel` y `C2PAPanel` — un patrón de composición correcto donde cada subpanel recibe solo el *slice* de datos que necesita.

El hallazgo más relevante de esta capa —descrito en detalle en la Sección 13— es que `ForensicPanel.tsx` (líneas 80-187) renderiza un bloque superior fijo titulado "Contenido Auténtico — Firma Digital Validada" con badge verde "VÁLIDO" y tres líneas de log siempre marcadas `[OK]`, **sin ninguna condición que dependa del resultado real del ensemble**. El comentario en el propio código (línea 73) sugiere que este bloque originalmente mostraba una tabla de scores por modelo y fue reemplazado por este sello fijo "para reducir ruido visual" — una regresión funcional no intencional aparente.

El componente `WorkerStatusProvider.tsx` (corregido en esta misma sesión de trabajo, ver historial de conversación) determina la disponibilidad del sistema mediante un *branch* explícito sobre el campo `mode` del endpoint de salud: en modo local (`full-gpu`) deriva el estado de `data.cuda`; en modo producción (`api-only`) usa el heartbeat de workers remotos (`data.workers_online`).

### 6.5 Capa de API — endpoints completos

#### `/api/v1/*` (enterprise, producción)

| Método | Endpoint | Código HTTP | Descripción |
|---|---|---|---|
| `POST` | `/api/v1/analyze` | 202 | Despacho async, rate limit 20/min, valida tamaño/MIME real, codifica Base64, estima tiempo |
| `GET` | `/api/v1/tasks/{task_id}` | 200/202 | Polling con cascada Redis→disco→pending; `task_id` validado por regex UUID v4 (previene path traversal) |
| `GET` | `/api/v1/tasks/{task_id}/custody` | 200/404/422/500 | Verificación independiente de la cadena de custodia forense |
| `GET` | `/api/v1/health` | 200 | Estado de API, Redis, GPU/CUDA (solo en modo local), heartbeat del worker remoto |
| `GET` | `/api/v1/history` | 200 | Historial desde disco (no localStorage) |
| `DELETE` | `/api/v1/tasks/{task_id}` | 200/404/500 | Borra el resultado persistido |

#### `/api/*` (legacy, modo local)

Cinco endpoints equivalentes de generación anterior (`/api/health`, `/api/analyze`, `/api/tasks/{id}`, `/api/history`, `/api/tasks/{id}` DELETE), mantenidos como capa de compatibilidad. Se identificó que este router, al despachar a Celery en modo `API_ONLY`, **no envía** `file_content_b64` (a diferencia de `/api/v1/analyze`), lo que provocaría un fallo determinístico (`ValueError`) en el worker remoto si se usa en la arquitectura híbrida real — ver Sección 13.

### 6.6 Modelos Pydantic (`schemas.py`)

El esquema central, `AnalysisResult`, es deliberadamente un "god object" con casi todos los campos opcionales para acomodar tanto resultados de imagen como de video en el mismo modelo. Incluye los enums `EvidenceLevel` (5 niveles), `ModelAgreement` (3 niveles) y `UncertaintyLevel` (3 niveles, en español — inconsistencia menor de idioma frente al resto de enums en inglés). El campo `chain_of_custody`, el de mayor relevancia legal/forense del sistema, está tipado como `Optional[dict]` genérico en lugar de un modelo Pydantic propio, perdiendo la validación de esquema que sí se aplica al resto de los campos.

---

## 7. Base de Datos

El sistema **no utiliza una base de datos relacional ni documental tradicional**. La persistencia se compone de tres mecanismos:

1. **Redis (Aiven Valkey)**: almacén transitorio de resultados de tareas Celery (`result_expires=86400`, 24 horas) y canal de heartbeat del worker. No es la fuente de verdad permanente.
2. **Sistema de archivos JSON** (`reports/tasks/{task_id}.json`, `reports/custody/{...}.json`): persistencia real de los resultados y sellos de custodia, leída como segundo nivel de la cascada de resiliencia del polling. No hay índices, ni motor de consultas — el acceso es siempre por `task_id` exacto (validado por regex UUID).
3. **localStorage del navegador**: historial de análisis del lado del cliente, sin sincronización entre dispositivos ni backend.

**Evaluación**: la ausencia de una base de datos persistente con motor de consultas es coherente con el volumen y el patrón de acceso del sistema (siempre por clave única, nunca por búsqueda compleja), pero limita la capacidad de generar reportes agregados, analítica histórica, o auditorías a gran escala sin procesar manualmente el directorio de archivos JSON. No existen índices, relaciones, ni mecanismo de backup automatizado más allá de la persistencia del sistema de archivos del host.

---

## 8. Frontend (detalle)

Ver análisis exhaustivo en la Sección 6.4. Se añade aquí la evaluación de arquitectura cliente: el frontend es una **SPA de una sola pantalla** (`page.tsx`) sin enrutamiento adicional, con una máquina de estados explícita de 4 fases (`idle/analyzing/done/error`) gestionada con `useState` y transiciones animadas con Framer Motion (`AnimatePresence mode="wait"`). El único uso de React Context en toda la aplicación es `WorkerStatusProvider` — el resto de la comunicación entre componentes es *prop drilling* de dos niveles (page → UploadZone/ResultCard vía callbacks), una decisión razonable a la escala actual de la aplicación pero que no escalaría bien ante una eventual multiplicación de pantallas.

La normalización del contrato backend→frontend ocurre en `lib/api.ts` (`normalizeV1Response`) mediante un *cast* final (`as AnalysisResult`) sin validación de esquema en tiempo de ejecución (no se usa Zod, Yup ni io-ts) — el tipado estricto de TypeScript documenta la forma esperada del backend pero no la verifica, lo cual es una fuente de fragilidad silenciosa si el backend cambia la forma de un campo anidado.

---

## 9. Backend (detalle)

Ver análisis exhaustivo en las Secciones 6.2, 6.3, 6.5 y 6.6. Se añade aquí la evaluación de la lógica de negocio: el sistema implementa **tres rutas paralelas** que reproducen, con distinto grado de fidelidad, el mismo pipeline forense completo: la tarea Celery (`analysis_tasks.py`, la ruta de producción real), el *fallback* síncrono del router v1 (`_process_sync_fallback`, usado cuando Redis no está disponible en modo local), y el orquestador legado (`analysis_service.py`, usado por el router `/api/*`). Esta triplicación de lógica de negocio es la debilidad de mantenibilidad más significativa identificada a nivel de backend (ver Sección 13.3): cualquier cambio al pipeline de análisis debe replicarse manualmente en hasta tres lugares, con riesgo real de divergencia silenciosa entre rutas.

---

## 10. Seguridad

### 10.1 Controles existentes (verificados en código)

| Control | Implementación | Evidencia |
|---|---|---|
| CORS restringido | Lista explícita de orígenes, no wildcard, compatible con `allow_credentials=True` | `backend/app/config.py` (`ALLOWED_ORIGINS_CSV`), `main.py:116-122` |
| Rate limiting de dos capas | 100/min global, 20/min específico en `/analyze` (GPU-bound) | `main.py:77`, `api/v1/routes.py:232` |
| Validación de archivos en profundidad | Extensión + tamaño + magic bytes reales (no solo extensión) | `utils/file_validator.py` |
| Prevención de path traversal | Regex UUID v4 estricta antes de construir rutas de archivo por `task_id` | `api/v1/routes.py:26-32` |
| Cabeceras de seguridad HTTP | CSP `default-src 'none'`, `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Permissions-Policy` restrictiva | `main.py`, clase `SecurityHeadersMiddleware` |
| No filtración de tracebacks | Manejador global de excepciones devuelve mensaje genérico, loguea internamente | `main.py:141-147` |
| Serialización JSON exclusiva en Celery | Sin pickle, mitiga deserialización insegura | `celery_app.py` (`task_serializer="json"`) |
| Sello de custodia sin exposición del *canonical string* | Corregido en auditoría previa (SEC-06) | `custody_service.py` (no expone el mensaje exacto firmado) |

### 10.2 Hallazgos de seguridad históricos (ya corregidos)

La auditoría DevSecOps documentada en `docs/REPORTE_SEGURIDAD_Y_CAMBIOS.md` (2026-06-08) identificó y corrigió ocho hallazgos con nomenclatura CWE:

| ID | CWE | Severidad | Hallazgo |
|---|---|---|---|
| SEC-03 | CWE-798 | **Alta** | Uso de `redis.from_url()` crudo en endpoint legacy, fallaba silenciosamente con redis-py 6.x sobre TLS |
| SEC-04/05 | CWE-22 | **Media-Alta** | Path traversal vía `task_id` no validado |
| SEC-06 | CWE-200 | **Media** | Exposición pública del *canonical string* firmado del sello de custodia |
| SEC-07 | CWE-209 | **Baja-Media** | Mensajes de error exponían detalles internos (`f"Error: {e}"`) |
| SEC-08 | CWE-770 | **Media** | Rate limit específico de `/analyze` definido en config pero nunca aplicado |
| BUG-03 | CWE-434 | **Baja** | Validación de magic bytes incompleta para `.bmp` |
| BUG-04 | — | **Baja** | Clasificación incorrecta de WEBM como MKV (mismo header EBML) |
| SEC-15 | CWE-693 | **Baja-Media** | Ausencia de cabeceras de seguridad HTTP estándar |

### 10.3 Riesgos pendientes (reconocidos en auditoría previa, sin corrección de código)

| ID | Severidad | Riesgo | Estado |
|---|---|---|---|
| DOC-01 | **Alta** | TLS sin verificación de certificado en Redis (`ssl_cert_reqs=CERT_NONE`) — riesgo MITM sobre el canal que transporta archivos y la clave HMAC | Pendiente — requiere descargar CA de Aiven |
| DOC-02 | **Alta** | Ausencia total de autenticación en la API — cualquiera con la URL puede consumir GPU local sin límite de identidad | Pendiente — propuesta de API key vía header |
| DOC-03 | **Media** | Payload Base64 de Celery alcanza ~667MB para un video de 500MB (overhead 33%), persistido 24h en Redis | Pendiente — propuesta de Object Storage S3/R2 |
| DOC-04 | **Baja** | `HOST=0.0.0.0` en desarrollo local expone el servicio en la red local | Pendiente |

### 10.4 Hallazgos nuevos de este análisis (no documentados previamente)

| Riesgo | Severidad | Descripción |
|---|---|---|
| Sin gate de arranque para clave de firma | **Media** | `DEEPGUARD_SIGNING_KEY` tiene default vacío en `Settings` y default inseguro `change-me-in-production` en `docker-compose.prod.yml`; no hay verificación *fail-fast* a nivel de `config.py` que impida arrancar en producción con una clave default |
| `/docs` y `/redoc` expuestos sin protección | **Media** | Tanto FastAPI como la configuración de nginx exponen la documentación interactiva completa de la API sin ninguna restricción de acceso |
| `chain_of_custody` sin esquema validado | **Baja-Media** | El campo de mayor relevancia legal del sistema es un `dict` genérico, no un modelo Pydantic — pierde la validación de esquema que protege al resto de los campos |
| Filtración moderada de nombres de excepción | **Baja** | Algunos endpoints (`health_v1`, `analyze_async` en su rama 503) incluyen `type(e).__name__` en la respuesta al cliente |
| Hilos de limpieza sin límite acotado | **Baja** | `_schedule_file_cleanup` crea un hilo demonio nuevo por archivo sin pool ni límite superior — riesgo de acumulación bajo carga sostenida (impacto bajo, son hilos durmientes) |

### 10.5 Nivel de riesgo global asignado

**Medio-Alto**, principalmente por la combinación de (a) ausencia total de autenticación en un sistema con pretensión de uso forense/legal y (b) TLS sin verificación de certificado en el canal que transporta tanto los archivos analizados como la clave de firma HMAC. Ambos riesgos están correctamente identificados por el propio equipo en auditorías previas, lo cual reduce el riesgo de "deuda oculta" pero no elimina la exposición mientras no se implementen las correcciones propuestas.

---

## 11. Rendimiento

### 11.1 Cuellos de botella identificados

- **`SRMNoiseDetector._apply_filter` sin SciPy** (`models/srm_detector.py:111-125`): el *fallback* manual implementa convolución 2D mediante doble loop anidado en Python puro — complejidad `O(h·w·kh·kw)` sin vectorización, potencialmente catastrófico en imágenes de alta resolución (4K+) si SciPy no está disponible en el entorno del worker.
- **Inferencia secuencial de seis modelos** (`deepfake_detector.py`): los modelos A-F se ejecutan uno tras otro, no en paralelo ni en batch conjunto, dentro de `_predict_all`. En una GPU de 12GB con ~6.8GB ya ocupados por LLaVA, el paralelismo real está limitado por VRAM disponible, por lo que la secuencialidad es una decisión razonable, aunque no documentada como tal explícitamente.
- **Doble ejecución del ensemble si hay rostro detectado**: el pipeline corre la inferencia completa dos veces (imagen completa + recorte facial) cuando se detecta un rostro, duplicando el costo de cómputo GPU para ese caso.
- **Payload Base64**: el overhead de ~33% sobre el tamaño del archivo (documentado en DOC-03) afecta tanto el ancho de banda entre Render y Aiven Valkey como el tiempo de serialización/deserialización en ambos extremos.

### 11.2 Latencia documentada

Según `docs/INFORME_TECNICO_DEEPGUARD_AI.md`, el pipeline completo de producción para una imagen de ~2MB toma aproximadamente 4.5 segundos, desglosados en: subida 0.3s, despacho Celery 0.1s, SHA-256+EXIF 0.05s, detección OOD 0.1s, ensemble GPU 1.2s, meta-modelo XGBoost 0.01s, **LLaVA semántico 2.8s** (el cuello de botella dominante, el 62% del tiempo total), HMAC 0.001s. La inspección semántica por modelo de lenguaje visual es, por un margen amplio, la etapa más costosa del pipeline.

### 11.3 Escalabilidad de la configuración Celery

`worker_prefetch_multiplier=1` y `--concurrency=1` (`celery_app.py`, `docker-compose.prod.yml`) significan que **un único worker procesa una sola tarea a la vez**, una decisión correcta dado que la VRAM de una GPU no se puede compartir de forma segura entre inferencias concurrentes sin riesgo de *out-of-memory*. Esto implica que la capacidad de procesamiento del sistema completo escala linealmente solo si se añaden más máquinas GPU (workers), no por configuración de concurrencia en una sola máquina. El sistema de colas con prioridad (imágenes=10, videos=5) mitiga la inanición de tareas rápidas detrás de tareas lentas, pero no resuelve el límite estructural de un solo worker activo documentado en la arquitectura actual.

### 11.4 Consumo de recursos

- API en Render: RAM < 100MB documentada (sin PyTorch).
- Worker GPU local: ~6.8GB VRAM de 12.9GB disponibles (ensemble + LLaVA 4-bit).
- Imagen Docker de la API: ~180MB.

---

## 12. Calidad del Código

### 12.1 Legibilidad

Alta en general: nombres de funciones y variables descriptivos, type hints consistentes en Python (`-> Optional[dict]`, `-> tuple[float, dict]`), y un nivel de documentación inline (docstrings con casos reales) inusualmente alto para un proyecto de esta escala, particularmente en `forensic_corrections.py` y `meta_ensemble.py`.

### 12.2 Modularidad y cohesión

Buena separación por capa (modelos / servicios / utilidades / API / tareas), con cada módulo de `models/` enfocado en una sola señal de análisis (alta cohesión funcional). La cohesión se debilita en los servicios de orquestación (`image_service.py`, `_process_sync_fallback`) que concentran lógica de muchas etapas distintas en una sola función extensa.

### 12.3 Acoplamiento

Moderado a alto en puntos específicos: import local (no a nivel de módulo) de `MetaEnsemble` dentro de `_calibrated_combine` para evitar dependencia circular (`deepfake_detector.py:355`); acoplamiento fuerte de `MetaEnsemble` al formato exacto del archivo `.joblib` serializado, sin versionado de esquema; y la triplicación de la lógica de pipeline entre `analysis_tasks.py`, `_process_sync_fallback` y `analysis_service.py` constituye la forma más severa de acoplamiento por duplicación detectada en el sistema.

### 12.4 Mantenibilidad

El mayor riesgo de mantenibilidad identificado es la **proliferación de números mágicos no centralizados**: umbrales de discrepancia, pesos de mezcla convexa, y constantes de calibración (decenas de valores como `0.20`, `0.25`, `VETO_THRESHOLD=0.25`, `OOD_THRESHOLD=0.43`, etc.) están definidos como constantes de módulo en lugar de un sistema de configuración centralizado y versionado. Esto es parcialmente mitigado por la excelente documentación de las reglas de `forensic_corrections.py`, pero persiste en los detectores de señal individuales (`ood_detector.py`, `srm_detector.py`, `frequency_detector.py`), donde los comentarios admiten explícitamente que la calibración fue ajustada de forma manual/reactiva ante casos específicos.

### 12.5 Testabilidad

El backend tiene un diseño favorable a pruebas unitarias (funciones puras en `ood_detector.py`, `forensic_corrections.py` sin dependencias de ML), pero **no se encontraron tests automatizados** que verifiquen los umbrales y casos documentados en los docstrings — una oportunidad clara y de bajo costo de mejora (los números ya están en la documentación, faltaría solo escribir las aserciones). El frontend no tiene ninguna infraestructura de testing (`package.json` no incluye Jest/Vitest/Testing Library).

---

## 13. Buenas Prácticas Aplicadas

| Principio | Evidencia de aplicación | Evidencia de incumplimiento |
|---|---|---|
| **Single Responsibility** | Cada detector de `models/` resuelve una sola señal; cada panel de frontend recibe un slice acotado de datos | `image_service.py` concentra orquestación de muchas etapas en pocas funciones extensas |
| **DRY (Don't Repeat Yourself)** | Centralización de `make_redis_client()` para el parche de TLS, reutilizado en toda la API | Lógica de pipeline triplicada (Celery/sync_fallback/legacy); `BASE_URL` duplicado en 3 archivos frontend; tipo `CustodySeal` duplicado del campo `chain_of_custody` |
| **Fail Safe Defaults** | Degradación elegante ante dependencias opcionales ausentes (OpenCV, SciPy, facenet-pytorch, LLaVA) | Default inseguro de `DEEPGUARD_SIGNING_KEY` sin gate de arranque |
| **Separation of Concerns** | API ligera nunca importa PyTorch en `API_ONLY`; frontend export estático sin servidor | El mismo Dockerfile se usa para roles con requisitos opuestos (API sin GPU / worker con GPU) |
| **Defense in Depth** | Validación de archivos en 4 capas (extensión, tamaño, magic bytes, MIME); rate limiting de 2 capas | Ausencia de autenticación como capa final de control de acceso |
| **Explicabilidad / Transparencia algorítmica** | Fórmula del ensemble visible en UI; explicación narrativa generada; *string* canónico de firma verificable | Bloque "Contenido Auténtico — VÁLIDO" en `ForensicPanel.tsx` no refleja el cálculo real, contradiciendo el principio en ese punto específico |
| **Clean Code (naming)** | Nombres descriptivos en la mayoría del código | `_EfficientNetFF` ya no implementa EfficientNet (implementa CLIP) — naming obsoleto que confunde la lectura del código |

No se identifica un uso deliberado de Domain-Driven Design (no hay agregados, entidades de dominio ricas, ni *bounded contexts* explícitos) — el diseño es más cercano a una arquitectura en capas pragmática (*layered architecture*) que a DDD formal, lo cual es razonable para el tamaño y propósito del proyecto.

---

## 14. Problemas Detectados

| # | Problema | Severidad | Impacto | Solución recomendada |
|---|---|---|---|---|
| 1 | `ForensicPanel.tsx` muestra siempre "Contenido Auténtico — VÁLIDO" sin condicionarlo al resultado real del análisis | **Alta** | Comunicación potencialmente engañosa al usuario en un sistema de propósito forense; el bloque visualmente más prominente del panel principal contradice el principio de explicabilidad del resto del sistema | Condicionar el bloque al `final_probability`/`evidence_level` real, o reemplazarlo por un resumen dinámico coherente con el resultado |
| 2 | Lógica de pipeline forense duplicada en 3 rutas (`analysis_tasks.py`, `_process_sync_fallback`, `analysis_service.py`) | **Alta** | Alto riesgo de divergencia silenciosa entre rutas; cualquier cambio al pipeline requiere sincronización manual en 3 lugares | Extraer un orquestador único compartido (`run_forensic_pipeline()`) consumido por las 3 rutas de entrada |
| 3 | Ausencia de autenticación en toda la API | **Alta** | Cualquiera con la URL puede consumir GPU local sin límite de identidad; inadecuado para un eventual uso pericial/legal | Implementar API key o JWT mínimo, ya propuesto en auditoría previa (DOC-02) |
| 4 | TLS sin verificación de certificado en Redis (`CERT_NONE`) | **Alta** | Riesgo de interceptación del canal que transporta archivos y la clave HMAC | Configurar CA real de Aiven, ya propuesto en auditoría previa (DOC-01) |
| 5 | Mismo Dockerfile "sin GPU/torch" reutilizado para el servicio `worker` (que requiere CUDA) en `docker-compose.prod.yml` | **Media** | El compose de producción, tal como está documentado en el repositorio, no sería funcional para el servicio worker sin una imagen alternativa no incluida | Crear un `Dockerfile.worker` explícito con CUDA/PyTorch, distinto del de la API |
| 6 | Métrica F1=94.7% del informe técnico final no es trazable a ningún benchmark documentado | **Media** | Afecta la solidez de las afirmaciones de rendimiento citadas en la documentación oficial del proyecto | Documentar la metodología exacta y el dataset usado para esa cifra, o corregirla al valor verificable más reciente (88.7% XGBoost en validación cruzada sobre 512 imágenes) |
| 7 | `README.md` raíz describe el sistema original de un solo modelo, no el ensemble de 8 señales actual | **Media** | Desorienta a cualquier nuevo colaborador o evaluador que lea primero el README | Reescribir el README para reflejar la arquitectura v6.0.0 (parcialmente abordado en esta misma sesión de trabajo con la sección de modos de operación) |
| 8 | Endpoint legacy `/api/analyze` no envía `file_content_b64` al despachar a Celery en modo `API_ONLY` | **Media** | Fallo determinístico (`ValueError`) si se usa este endpoint en la arquitectura híbrida real | Igualar el comportamiento al de `/api/v1/analyze`, o deprecar formalmente el router legacy |
| 9 | Tipos duplicados entre frontend y backend (`CustodySeal` local vs. `chain_of_custody` inline; `HealthResponse` desactualizada respecto al payload real de `/api/v1/health`) | **Baja-Media** | Riesgo de desincronización silenciosa entre lo que el backend envía y lo que el frontend espera | Generar tipos TypeScript desde los modelos Pydantic (ej. `pydantic-to-typescript` u OpenAPI codegen) |
| 10 | Sin tests automatizados en backend ni frontend | **Media** | Cambios futuros no tienen red de seguridad de regresión, a pesar de que los casos de prueba ya están documentados en los docstrings de `forensic_corrections.py` | Escribir tests unitarios mínimos para las 4 reglas forenses y el meta-ensemble (los valores ya están documentados) |
| 11 | Progreso simulado/cosmético en `AnalysisProgress.tsx` (8 etapas y timestamps interpolados, no reales) | **Baja** | El usuario puede percibir información de progreso que no corresponde fielmente al estado real del backend | Reportar etapas reales vía el campo `stage` que ya existe en el backend (`_enriquecer_estado`, `api/v1/routes.py`) |
| 12 | Hilos de limpieza de archivos sin pool acotado (`_schedule_file_cleanup`) | **Baja** | Acumulación de hilos durmientes bajo carga sostenida (impacto de memoria bajo) | Usar un `ThreadPoolExecutor` con límite, o una tarea Celery programada (`celery beat`) en lugar de hilos ad-hoc |
| 13 | Naming engañoso: `_EfficientNetFF` implementa CLIP, no EfficientNet | **Baja** | Confunde la lectura del código a futuros mantenedores | Renombrar la clase a algo como `_CLIPProbeDetector` |
| 14 | Fallback manual de convolución 2D sin SciPy es extremadamente lento (doble loop Python) | **Baja-Media** | Riesgo de degradación severa de rendimiento en imágenes de alta resolución si SciPy no está disponible en el entorno del worker | Garantizar SciPy como dependencia obligatoria (no opcional) dado que ya es así en la práctica, o vectorizar el fallback con NumPy puro |

---

## 15. Propuestas de Mejora

### 15.1 Corto plazo (días, bajo riesgo)

1. Corregir el bloque de "Contenido Auténtico" en `ForensicPanel.tsx` para que refleje el resultado real (Problema #1).
2. Añadir tests unitarios para las 4 reglas de `forensic_corrections.py` usando los casos numéricos ya documentados en los docstrings (Problema #10).
3. Actualizar `README.md` para reflejar la arquitectura v6.0.0 (Problema #7, parcialmente iniciado en esta sesión).
4. Igualar el comportamiento de `/api/analyze` y `/api/v1/analyze` respecto al envío de `file_content_b64`, o deprecar el primero formalmente (Problema #8).
5. Añadir un *gate* de arranque (*fail-fast*) que impida iniciar el worker en producción con `DEEPGUARD_SIGNING_KEY` vacía o igual al valor de ejemplo.

### 15.2 Mediano plazo (semanas)

1. Extraer un orquestador único del pipeline forense, consumido por las 3 rutas de entrada actuales, eliminando la duplicación de lógica de negocio (Problema #2).
2. Implementar autenticación mínima (API key) en ambas generaciones de la API (Problema #3, DOC-02).
3. Configurar verificación de certificado TLS real para la conexión a Redis (Problema #4, DOC-01).
4. Migrar el payload de archivos de Celery desde Base64 inline hacia Object Storage (S3/R2) con URLs prefirmadas (DOC-03), reduciendo el overhead de ~33% y el tamaño de los mensajes en Redis.
5. Generar los tipos TypeScript del frontend automáticamente desde los modelos Pydantic del backend (Problema #9), eliminando la clase de bugs por desincronización manual de contratos.
6. Reemplazar el progreso simulado de `AnalysisProgress.tsx` por el estado real ya disponible en el backend (Problema #11).

### 15.3 Largo plazo (meses, requiere investigación/reentrenamiento)

1. Reentrenar el meta-ensemble XGBoost incorporando las 8-9 señales completas (en vez de solo 3), evaluando si el "Consensus Override" manual puede simplificarse o eliminarse con un modelo mejor calibrado.
2. Expandir el conjunto de validación ("golden set") más allá de las 20-512 imágenes actuales hacia un conjunto de validación robusto y estratificado por categoría, con un conjunto de prueba *held-out* nunca usado para ajustar umbrales — actualmente las 4 reglas forenses están calibradas reactivamente sobre casos puntuales, con riesgo de sobreajuste.
3. Incorporar cobertura de generadores no soportados actualmente: anime/arte digital y GAN clásico (ProGAN/StyleGAN), identificados como brechas reconocidas desde la fase de investigación inicial (`AI_DETECTOR_RESEARCH.md`) y nunca resueltas.
4. Evaluar la migración del meta-modelo o de alguna señal hacia un esquema de versionado de modelo explícito (firma de esquema en el `.joblib`), eliminando el acoplamiento implícito actual entre `MetaEnsemble` y el formato exacto del archivo serializado.

---

## 16. Escalabilidad Futura

### 16.1 Cómo crecería el sistema

El cuello de botella estructural más relevante para escalar el volumen de análisis es el **worker único (`--concurrency=1`)** atado a una sola GPU física. El crecimiento horizontal del sistema requeriría sumar más máquinas con GPU como workers Celery adicionales (cada una consumiendo de la misma cola de prioridad en Aiven Valkey), lo cual la arquitectura actual ya soporta sin cambios de diseño — Celery está diseñado nativamente para múltiples workers consumiendo la misma cola. El riesgo en ese escenario de crecimiento es económico, no técnico: cada GPU adicional implica o bien hardware propio adicional, o la renuncia a la restricción de "costo cero" que motivó la arquitectura híbrida en primer lugar.

### 16.2 Riesgos de escalar tal como está

- El payload Base64 (Problema/DOC-03) escala mal con el tamaño de archivo y el volumen de tareas concurrentes en Redis — sería el primer límite práctico ante un aumento sostenido de tráfico de video.
- La ausencia de autenticación (Problema #3) se vuelve más riesgosa a medida que el sistema gane visibilidad pública, al no poder discriminar ni limitar el consumo de GPU por usuario/origen.
- La persistencia en archivos JSON sin índice (Sección 7) no escalaría bien hacia analítica histórica o reportes agregados a gran volumen; en ese escenario sería razonable introducir una base de datos ligera (SQLite para empezar, PostgreSQL si el volumen lo justifica) exclusivamente para metadatos de tareas, sin tocar el almacenamiento de archivos pesados.

### 16.3 Arquitecturas recomendadas para la siguiente etapa

Migrar el almacenamiento de archivos a Object Storage con URLs prefirmadas (ya identificado por el propio equipo), introducir autenticación de API, y — solo si el volumen de uso lo justifica — evaluar autoscaling horizontal de workers GPU mediante un proveedor de GPU *on-demand* (RunPod, Vast.ai) activado condicionalmente cuando la cola exceda un umbral, preservando el worker local como recurso de costo base y los workers cloud como capacidad de desborde (*burst*).

---

## 17. Conclusiones

### 17.1 Hallazgos principales

DeepGuard AI es un sistema de ingeniería sustancialmente más maduro que el README de su propio repositorio sugiere a primera lectura. La arquitectura híbrida nube/GPU-local resuelve con criterio una restricción presupuestaria real, y el pipeline de decisión —ensemble de nueve señales, meta-clasificador con exclusión deliberada de modelos poco confiables, veto de consenso, y cuatro reglas de corrección forense documentadas con casos reales— refleja un proceso de iteración basado en evidencia, no en suposiciones de diseño aisladas. La existencia de una auditoría de seguridad formal previa, con nomenclatura CWE y deuda pendiente explícitamente reconocida, es en sí misma una señal de madurez de proceso poco común en proyectos de esta escala.

### 17.2 Fortalezas

Separación de responsabilidades entre API ligera y cómputo GPU; resiliencia de polling ante fallos de red intermitentes; trazabilidad documental excepcional de las decisiones de calibración forense; tipado de dominio expresivo en TypeScript; y una postura consistente de comunicación de incertidumbre forense (evidencia graduada en vez de veredictos binarios) que atraviesa tanto el backend como el frontend, con la notable excepción puntual descrita en el Problema #1.

### 17.3 Debilidades

Triplicación de la lógica de negocio del pipeline; ausencia total de autenticación; TLS sin verificación de certificado en el canal Redis; una inconsistencia funcional de comunicación visual en el panel forense principal; y una proliferación de números mágicos de calibración sin un mecanismo central de versionado, mitigada parcialmente por la calidad de la documentación inline existente.

### 17.4 Evaluación global

El sistema es **apto para demostración técnica y defensa académica**, y se aproxima a un nivel de aptitud para producción real con restricciones, condicionado a resolver los hallazgos de severidad alta identificados en la Sección 14 (autenticación, TLS, duplicación de pipeline, y la inconsistencia del panel forense). Esta misma conclusión es consistente con el veredicto explícito documentado por el propio equipo en `docs/REPORT_AUDIT_FINAL.md`: *"apto para despliegue con reservas... no debe presentarse como detector infalible"* — un juicio que este análisis independiente corrobora con evidencia adicional y más reciente.

---

## 18. Anexos

### 18.1 Árbol completo del proyecto (archivos versionados)

```
.gitignore
INICIAR LOCAL.bat
INICIAR PAGINA WEB.bat
README.md
backend/
  .dockerignore  .env.example  .env.production.example  .env.worker.example  Dockerfile
  app/
    __init__.py  main.py  config.py  celery_app.py
    api/  __init__.py  routes.py  schemas.py
      v1/ __init__.py  routes.py
    models/ __init__.py  deepfake_detector.py  ela_detector.py  face_detector.py
             frequency_detector.py  meta_ensemble.py  ood_detector.py  srm_detector.py
    services/ __init__.py  analysis_service.py  c2pa_service.py  custody_service.py
                forensic_metadata_service.py  image_service.py  metadata_service.py
                osint_service.py  semantic_inspection_service.py  video_service.py
                video_temporal_service.py
    tasks/ __init__.py  analysis_tasks.py
    utils/ __init__.py  file_validator.py  forensic_corrections.py  helpers.py
  audit_full.py  audit_tasks.py  e2e_test.py  enterprise_check.py
  requirements.txt  requirements-api.txt
  test_pipeline_robustness.py  test_routing_fix.py  test_semantic_fusion.py  try_ff.py
docker-compose.yml  docker-compose.prod.yml
docker/nginx.conf
docs/ (11 documentos de auditoría histórica + informes .docx)
frontend/
  .env.production  .env.production.example  Dockerfile  netlify.toml
  next-env.d.ts  next.config.js  package.json  package-lock.json
  postcss.config.js  tailwind.config.ts  tsconfig.json
  public/_redirects
  src/
    app/ globals.css  layout.tsx  page.tsx
    components/ AnalysisProgress.tsx  C2PAPanel.tsx  ForensicPanel.tsx  HistorySection.tsx
                 MetadataPanel.tsx  Navbar.tsx  OsintPanel.tsx  ResultCard.tsx
                 UploadZone.tsx  WorkerStatusProvider.tsx
    lib/api.ts
    types/index.ts
scripts/ (entrenamiento, benchmark, descarga de datasets — 20 scripts)
setup.ps1  setup.sh
tests/ (manifiestos de golden_set, benchmark_extended, benchmark_massive)
tools/ gc.py  generar_informe.py  generar_informe_cto.py  generar_informe_word.py  v2_verify.py
```

### 18.2 Dependencias clave detectadas

**Backend (GPU completo)**: `torch`, `torchvision`, `transformers`, `bitsandbytes`, `xgboost`, `joblib`, `facenet-pytorch`, `opencv-python`, `scipy`, `numpy`, `Pillow`, `fastapi`, `celery`, `redis`, `slowapi`, `pydantic`, `pydantic-settings`, `loguru`, `python-magic`.

**Backend (API ligera, Render)**: `fastapi`, `celery`, `redis`, `slowapi`, `pydantic`, `pydantic-settings`, `loguru`, `python-magic` — explícitamente sin `torch`/`transformers`/`opencv`.

**Frontend**: `next` (14.0.4), `react`/`react-dom` (18.2), `axios`, `framer-motion`, `lucide-react`, `react-dropzone`, `recharts`; dev: `typescript`, `tailwindcss`, `eslint`.

### 18.3 Configuraciones relevantes

- `API_ONLY` (booleano): interruptor maestro de modo local-GPU vs. cloud-API, sin detección automática de entorno.
- `DEEPGUARD_SIGNING_KEY`: clave HMAC de la cadena de custodia, obligatoria en el worker (verificación en tiempo de ejecución), sin verificación equivalente a nivel de `Settings`.
- `REDIS_URL`/`REDIS_BACKEND`: deben coincidir exactamente entre la API (Render) y el worker (local) para que ambos consuman la misma cola.
- `RATE_LIMIT_PER_MINUTE=20`: variable de configuración cuyo valor efectivo está hardcodeado directamente en el decorador del endpoint (`@_limiter.limit("20/minute")`) en lugar de leerse de `settings`.

### 18.4 Requisitos de calidad observados vs. ausentes

| Requisito de calidad | Estado |
|---|---|
| Documentación de decisiones de arquitectura | **Presente y robusta** (11 documentos históricos con casos reales) |
| Auditoría de seguridad formal | **Presente** (CWE, severidad, estado de corrección) |
| Tests automatizados (backend) | **Ausente** |
| Tests automatizados (frontend) | **Ausente** |
| Versionado de esquema de modelos serializados (`.joblib`) | **Ausente** |
| Autenticación de API | **Ausente** |
| Validación runtime del contrato API (frontend) | **Ausente** (se confía en *casts* de TypeScript) |
| Logging estructurado | **Presente** (`loguru` en todo el backend) |
| Manejo de fallos de dependencias opcionales | **Presente y consistente** (degradación elegante en todos los detectores) |

---

*Documento generado mediante análisis estático exhaustivo del código fuente del repositorio `PROYECTO TITULO FINAL` (DeepGuard AI), commit `45576f1`. Todas las afirmaciones cuantitativas y de comportamiento citan archivo y línea aproximada de origen; donde la información proviene de documentación histórica del proyecto en lugar de inspección directa de código, se indica explícitamente la fuente.*
