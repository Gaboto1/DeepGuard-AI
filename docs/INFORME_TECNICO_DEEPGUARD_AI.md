# INFORME TÉCNICO DE ARQUITECTURA E IMPLEMENTACIÓN
## DeepGuard AI — Sistema Global de Detección de Deepfakes
### Proyecto de Título · Ingeniería en Informática · INACAP

---

| Campo | Detalle |
|-------|---------|
| **Proyecto** | DeepGuard AI v6.0 — Sistema Forense de Detección de Deepfakes |
| **Autor** | Gabriel Toro Rojas |
| **Institución** | Instituto Nacional de Capacitación Profesional (INACAP) |
| **Carrera** | Ingeniería en Informática |
| **Versión del sistema** | 6.0.0 — Release de Producción |
| **Fecha de emisión** | 31 de mayo de 2026 |
| **Clasificación** | Documento Técnico — Defensa de Título |

---

## TABLA DE CONTENIDOS

1. [Resumen Ejecutivo y Justificación de Arquitectura](#capítulo-1)
2. [Bitácora Forense de Optimización — Resolución de Errores Críticos](#capítulo-2)
3. [Flujo Operativo Sectorizado y Cadena de Custodia](#capítulo-3)
4. [Topología del Repositorio Purgado v6.0](#capítulo-4)
5. [Métricas de Rendimiento y Validación](#métricas)
6. [Conclusiones de Ingeniería](#conclusiones)

---

<a name="capítulo-1"></a>
## CAPÍTULO 1: RESUMEN EJECUTIVO Y JUSTIFICACIÓN DE ARQUITECTURA

### 1.1 El Problema: La Amenaza de los Deepfakes en la Era de la IA Generativa

El término *deepfake* designa contenido audiovisual sintético generado o manipulado mediante redes neuronales profundas, principalmente Generative Adversarial Networks (GANs) y, más recientemente, modelos de difusión latente (*Stable Diffusion*, *DALL-E*, *Midjourney*). La proliferación de estas técnicas ha generado una crisis de autenticidad digital con impactos documentados en tres dominios críticos:

- **Desinformación política**: manipulación de declaraciones de figuras públicas
- **Fraude financiero**: suplantación de identidad en videollamadas corporativas
- **Abuso de imagen**: generación no consentida de contenido íntimo

Según el *World Economic Forum* (2024), el volumen de contenido deepfake detectado en redes sociales se duplica cada seis meses. Los métodos tradicionales de verificación humana tienen una tasa de acierto inferior al 50% en deepfakes generados con modelos de última generación, estadísticamente equivalente a un lanzamiento de moneda.

**DeepGuard AI** nace como respuesta directa a esta problemática, implementando un pipeline de análisis forense probabilístico capaz de clasificar imágenes y videos con base en evidencia multi-modal: frecuencia espacial, coherencia semántica, metadatos forenses y análisis temporal de consistencia entre fotogramas.

---

### 1.2 Justificación Teórica: Arquitectura Híbrida Desacoplada Nube-Local

#### 1.2.1 El Dilema del Cómputo GPU en la Nube

La inferencia de modelos de Deep Learning de escala media-grande presenta un cuello de botella computacional determinado por el ancho de banda de memoria de la GPU y la capacidad de cómputo paralelo (medida en TFLOPS). Los proveedores de nube ofrecen capacidad GPU bajo los siguientes esquemas de coste aproximado al momento del desarrollo:

| Proveedor | Instancia GPU | VRAM | Costo Mensual (USD) |
|-----------|--------------|------|---------------------|
| AWS | `g4dn.xlarge` (Tesla T4) | 16 GB | ~$380 |
| Google Cloud | `n1-standard-4` + T4 | 16 GB | ~$350 |
| Azure | `NC6s_v3` (Tesla V100) | 16 GB | ~$730 |
| **Hardware propio** | RTX 4070 SUPER | **12 GB** | **$0 (amortizado)** |

La naturaleza académica del proyecto impone una restricción presupuestaria de $0 en infraestructura de cómputo. Esta restricción convierte el uso de GPU en nube en técnicamente inviable para un ciclo de vida de 12+ meses.

#### 1.2.2 La Solución: Desacoplamiento de Capas por Dominio de Responsabilidad

La arquitectura seleccionada sigue el principio de **Separación de Responsabilidades** (*Separation of Concerns*) a nivel de infraestructura, distribuyendo las capas del sistema según su perfil de recursos:

```
┌──────────────────────────────────────────────────────────────┐
│  CAPA DE PRESENTACIÓN        Netlify (CDN global)            │
│  Next.js static export       RAM: ~0 MB (sin servidor)       │
│  100% gratuito               Latencia: < 50ms (edge network) │
└──────────────────────────────────────────────────────────────┘
                         │ HTTPS
┌──────────────────────────────────────────────────────────────┐
│  CAPA DE ORQUESTACIÓN        Render (free tier)              │
│  FastAPI — API_ONLY=true     RAM: < 80 MB                    │
│  Sin PyTorch instalado       CPU: mínima (solo routing)      │
└──────────────────────────────────────────────────────────────┘
                         │ Redis TLS
┌──────────────────────────────────────────────────────────────┐
│  CAPA DE TRANSPORTE          Aiven Valkey (free tier)        │
│  Valkey 7.2.4 (fork Redis)   Protocolo: RESP3 sobre TLS 1.3  │
│  Broker + Result Backend     Persistencia: AOF + RDB         │
└──────────────────────────────────────────────────────────────┘
                         │ Celery Task
┌──────────────────────────────────────────────────────────────┐
│  CAPA DE CÓMPUTO             Hardware local (GPU)            │
│  RTX 4070 SUPER 12 GB VRAM   CUDA 12.4                       │
│  5 modelos + LLaVA 4-bit     6.8 GB VRAM utilizada           │
└──────────────────────────────────────────────────────────────┘
```

**Ventajas arquitectónicas cuantificables:**

1. **Costo operativo**: $0/mes frente a los ~$380-730/mes de alternativas cloud GPU
2. **Latencia de inferencia**: La GPU local elimina la latencia de red en el pipeline de inferencia (round-trip cloud vs. acceso PCIe local)
3. **Flexibilidad de modelos**: Sin restricciones de memoria de contenedor cloud; posibilidad de cargar LLaVA-1.5-7b (7B parámetros, ~5 GB en 4-bit)
4. **Desacoplamiento de fallos**: La caída de la API en Render no interrumpe tareas ya encoladas; el worker local puede seguir procesando de forma autónoma

#### 1.2.3 Componentes de Infraestructura

| Componente | Tecnología | Servicio Cloud | Costo |
|-----------|-----------|---------------|-------|
| Frontend | Next.js 14 + React + TypeScript | Netlify (CDN global) | Gratuito |
| API Gateway | FastAPI 0.104 + Uvicorn | Render (free tier) | Gratuito |
| Message Broker | Aiven Valkey 7.2.4 | Aiven (free tier) | Gratuito |
| Result Backend | Aiven Valkey 7.2.4 | Aiven (free tier) | Gratuito |
| Heavy Worker | Celery 5.3 + PyTorch 2.x | Hardware propio | $0 (amortizado) |
| GPU de inferencia | NVIDIA RTX 4070 SUPER | Hardware propio | $0 (amortizado) |
| **TOTAL MENSUAL** | | | **$0** |

---

### 1.3 Modelo de IA: Ensemble de 5 Modelos Especializados

El corazón del sistema es un **meta-ensemble** XGBoost que combina las predicciones de cinco modelos de Deep Learning, cada uno especializado en un subtipo de manipulación:

| ID | Modelo | Arquitectura | Especialización |
|----|--------|-------------|-----------------|
| A | `prithivMLmods/Deep-Fake-Detector-v2-Model` | ViT (Vision Transformer) | Face-swap, face-reenactment |
| B | `Organika/sdxl-detector` | EfficientNet fine-tuned | Imágenes SDXL fotorrealistas |
| C | `CLIP ViT-L/14 + Linear Probe` | Contrastive Learning | Generalización multi-dominio |
| D | `haywoodsloan/ai-image-detector-deploy` | Swin Transformer v2 | Arte generado por IA |
| E | `prithivMLmods/Deepfake-Detect-Siglip2` | SigLIP | Deepfakes audiovisuales |

El meta-ensemble opera con pesos adaptativos según la presencia de rostro humano en la imagen:

```python
# Pesos del ensemble con rostro detectado
_W_FACE    = [0.30, 0.20, 0.20, 0.15, 0.15]  # ViT tiene mayor peso

# Pesos del ensemble sin rostro (imagen completa)
_W_NO_FACE = [0.20, 0.25, 0.20, 0.20, 0.15]  # SDXL tiene mayor peso
```

Sobre los scores del ensemble opera un **XGBoost** (profundidad=2, regularización L2) con **Temperature Scaling** calibrado a T=0.581, obteniendo:

| Métrica | Valor | Condición de evaluación |
|---------|-------|------------------------|
| F1-Score | 94.7% | Golden set 512 imágenes, split independiente |
| ECE (Error de Calibración) | 0.084 | Post Temperature Scaling |
| FPR (Falsos Positivos) | 10% | Umbral de clasificación 50% |

Complementariamente, el modelo **LLaVA-1.5-7b-hf** (cuantizado en 4-bit NF4 mediante `bitsandbytes`) realiza un análisis semántico forense: evalúa coherencia anatómica, física y textual de la imagen, produciendo un `risk_score` (0-100) que corrige el output del ensemble en casos límite.

---

<a name="capítulo-2"></a>
## CAPÍTULO 2: BITÁCORA FORENSE DE OPTIMIZACIÓN — RESOLUCIÓN DE ERRORES CRÍTICOS

Esta sección documenta los cinco errores más críticos encontrados durante el ciclo de desarrollo e integración del sistema distribuido, con análisis de causa raíz y solución aplicada a nivel de código.

---

### ERROR A: 404 Page Not Found en Netlify

**Contexto de manifestación:** Al desplegar el frontend en Netlify, cualquier navegación directa a la URL `deepguard-ai-inacap.netlify.app` devolvía el error *"Page not found"* de Netlify, no de nuestra aplicación.

#### Causa Raíz Técnica

Next.js ofrece tres modos de output configurables en `next.config.js`:

| Modo | Descripción | Artefacto generado |
|------|------------|-------------------|
| `default` | SSR/ISR con servidor Node.js | Requiere `next start` |
| `standalone` | Servidor Node.js autocontenido | Carpeta `.next/standalone/` con `server.js` |
| `export` | HTML/CSS/JS estático puro | Carpeta `out/` sin servidor |

La configuración inicial usaba `output: 'standalone'`, que genera un servidor Node.js que debe ejecutarse con `node server.js`. Netlify es un servicio de hosting *estático*: **no ejecuta procesos Node.js persistentes**. Al publicar los archivos de `.next/standalone/`, Netlify encontraba únicamente el `server.js` de arranque pero ningún archivo `index.html` servible directamente.

Adicionalmente, al navegar a cualquier ruta en una Single Page Application (SPA), el servidor de archivos estáticos busca un fichero físico en disco. Al no encontrarlo (porque Next.js gestiona el enrutamiento en el cliente), retorna 404. El archivo `_redirects` que tenía la regla `/* /index.html 200` estaba ubicado en la raíz del proyecto frontend, no dentro de la carpeta `public/`, por lo que nunca se copiaba al directorio de output.

#### Solución Aplicada

**Paso 1:** Cambio del modo de compilación en `next.config.js`:

```javascript
// next.config.js — ANTES (erróneo para Netlify)
const nextConfig = {
  output: 'standalone',   // Genera servidor Node.js — incompatible con hosting estático
  async rewrites() { ... }
};

// next.config.js — DESPUÉS (correcto)
const nextConfig = {
  output: 'export',       // Genera carpeta /out con HTML/CSS/JS puro
  trailingSlash: true,    // /about → /about/index.html (compatibilidad CDN)
  images: { unoptimized: true },  // Requerido en modo export estático
};
```

**Paso 2:** Creación de `netlify.toml` en la raíz del frontend:

```toml
[build]
  command   = "npm run build"
  publish   = "out"              # Netlify publica esta carpeta

[build.environment]
  NODE_VERSION        = "20"
  NEXT_PUBLIC_API_URL = "https://deepguard-ai-api.onrender.com"

[[redirects]]
  from   = "/*"
  to     = "/index.html"
  status = 200                  # SPA fallback: todas las rutas → index.html
```

**Paso 3:** Reubicación de `_redirects` a `public/_redirects`:

```
frontend/
├── public/
│   └── _redirects    ← Next.js copia public/ → out/ durante el build
└── _redirects        ← NUNCA llega a out/ (posición incorrecta original)
```

**Resultado:** Netlify ejecuta `npm run build`, obtiene la carpeta `out/` con `index.html`, `_redirects` y todos los chunks de JavaScript, y sirve la SPA correctamente con fallback para el enrutamiento del cliente.

---

### ERROR B: Network Error y Bloqueos CORS

**Contexto de manifestación:** Al intentar analizar una imagen desde `deepguard-ai-inacap.netlify.app`, el browser mostraba en consola: `Access to fetch at 'https://deepguard-ai-api.onrender.com/api/v1/analyze' from origin 'https://deepguard-ai-inacap.netlify.app' has been blocked by CORS policy`.

#### Causa Raíz Técnica

**CORS** (Cross-Origin Resource Sharing) es un mecanismo de seguridad implementado por los navegadores que restringe las peticiones HTTP realizadas desde un origen `(protocolo, dominio, puerto)` a un servidor con un origen diferente. El navegador envía primero una petición *preflight* con método `OPTIONS`, esperando que el servidor responda con las cabeceras:

```http
Access-Control-Allow-Origin: https://deepguard-ai-inacap.netlify.app
Access-Control-Allow-Methods: GET, POST, DELETE, OPTIONS
Access-Control-Allow-Headers: Content-Type, Authorization
```

Si el servidor no incluye estas cabeceras, el browser aborta la petición antes de enviar los datos reales.

El error se producía por **dos causas independientes y simultáneas**:

1. **Render no tenía el dominio de Netlify en `ALLOWED_ORIGINS_CSV`:** El middleware de FastAPI con `CORSMiddleware` solo añade las cabeceras CORS para orígenes listados explícitamente. Al no incluir `https://deepguard-ai-inacap.netlify.app`, el servidor respondía a la petición OPTIONS sin la cabecera `Access-Control-Allow-Origin`.

2. **`NEXT_PUBLIC_API_URL` no estaba definida en Netlify:** Next.js embebe las variables de entorno `NEXT_PUBLIC_*` en el bundle JavaScript en tiempo de *compilación* (no de ejecución). Al compilar sin la variable definida, el cliente usaba el fallback `http://localhost:8000`, lo que significa que los usuarios en producción intentaban conectarse a un servidor que no existe en internet.

#### Solución Aplicada

**Backend — `config.py`:** Valor por defecto actualizado para incluir el dominio de producción:

```python
class Settings(BaseSettings):
    ALLOWED_ORIGINS_CSV: str = (
        "http://localhost:3000,"
        "http://localhost:3001,"
        "http://127.0.0.1:3000,"
        "https://deepguard-ai-inacap.netlify.app"  # ← Añadido
    )
```

**Variable de entorno en Render Dashboard:**
```
ALLOWED_ORIGINS_CSV = https://deepguard-ai-inacap.netlify.app,http://localhost:3000
```

**Frontend — `netlify.toml`:** URL embebida en tiempo de compilación:

```toml
[build.environment]
  NEXT_PUBLIC_API_URL = "https://deepguard-ai-api.onrender.com"
```

**Frontend — `Navbar.tsx`:** El health check del badge usaba `fetch()` estándar que el browser bloqueaba con error CORS. Se migró a `mode: 'no-cors'`:

```typescript
// ANTES: CORS bloqueaba la petición y el badge mostraba "FUERA DE LÍNEA"
const res = await fetch(`${BASE_URL}/api/v1/health`);

// DESPUÉS: no-cors permite la petición sin leer la respuesta
// Si el servidor RESPONDE (aunque sea sin cabeceras CORS) → promesa resuelve → "EN LÍNEA"
// Si el servidor está CAÍDO → promesa rechaza → "FUERA DE LÍNEA"
const res = await fetch(`${BASE_URL}/api/v1/health`, {
  method: 'GET',
  mode:   'no-cors',
  signal: AbortSignal.timeout(35_000),
  cache:  'no-store',
});
setStatus(res.type === 'opaque' || res.ok ? 'online' : 'offline');
```

**Error derivado resuelto — HTTP 500 en `/api/v1/health`:** El endpoint de salud del sistema importaba `torch` incondicionalmente. En Render (`API_ONLY=true`, sin PyTorch instalado), esto causaba un `ModuleNotFoundError` → HTTP 500:

```python
# ANTES — causa ModuleNotFoundError en Render
@router.get("/health")
async def health_v1():
    import torch   # ← Importación incondicional — FALLA en API_ONLY mode
    return JSONResponse({"cuda": torch.cuda.is_available(), ...})

# DESPUÉS — importación condicional según entorno
@router.get("/health")
async def health_v1():
    from app.config import settings as _cfg
    cuda_ok, gpu_name = False, "N/A (API-only mode)"
    if not _cfg.API_ONLY:
        try:
            import torch
            cuda_ok  = torch.cuda.is_available()
            gpu_name = torch.cuda.get_device_name(0) if cuda_ok else "N/A"
        except ImportError:
            pass
    return JSONResponse({"cuda": cuda_ok, "gpu": gpu_name, ...})
```

---

### ERROR C: Congelamiento en 2% con Errores 404 en el Polling

**Contexto de manifestación:** El usuario subía un archivo, la barra de progreso avanzaba al 2% y se detenía indefinidamente. La consola del navegador mostraba `GET https://deepguard-ai-api.onrender.com/api/v1/tasks/{id} 404 Not Found` en bucle.

#### Causa Raíz Técnica

El sistema utiliza un mecanismo de **polling asíncrono** para consultar el estado de las tareas: el frontend envía una petición `GET /api/v1/tasks/{task_id}` cada 1500ms hasta que el estado sea `completed` o `failed`.

La función `_get_task_result()` en el servidor consultaba el estado de la tarea en Celery/Aiven:

```python
def _get_task_result(task_id: str):
    try:
        ar = AsyncResult(task_id, app=celery_app)
        if ar.ready():       # La tarea terminó
            ...
        elif ar.state in ("PROCESSING", "STARTED"):
            ...              # La tarea está en progreso
        else:
            return _enriquecer_estado({"status": "PENDING"})  # ← Estado inicial
    except Exception:
        pass  # ← El except silenciaba el error

    # Búsqueda en disco local de Render
    disk_path = RESULTS_DIR / f"{task_id}.json"
    if disk_path.exists(): ...  # ← Nunca existe en el disco de Render

    return None  # ← None → HTTP 404
```

El problema se manifestaba en la cadena de fallo silencioso:

1. Render intentaba conectarse a Aiven para leer el estado de la tarea (`AsyncResult`)
2. Si la conexión a Aiven fallaba momentáneamente (latencia, cold start), el `except` silenciaba el error
3. Render buscaba el JSON del resultado en su disco local → no existía (el worker lo guarda en su propio disco)
4. La función retornaba `None` → el endpoint devolvía HTTP 404
5. El frontend, al recibir 404, detenía el polling (comportamiento por defecto de Axios con `validateStatus`)

Adicionalmente, la verificación de Redis antes de despachar tareas usaba un timeout de **1 segundo**, insuficiente para un handshake TLS con Aiven (latencia media de 80-200ms):

```python
# ANTES — timeout insuficiente para TLS remoto
_r = redis.from_url(url, socket_connect_timeout=1, socket_timeout=1)
_r.ping()  # TimeoutError → redis_available = False → HTTPException 503
```

#### Solución Aplicada

**Solución 1 — Fallback seguro en `_get_task_result()`:**

```python
def _get_task_result(task_id: str):
    redis_error = None
    try:
        ar = AsyncResult(task_id, app=celery_app)
        if ar.ready():
            if ar.successful():
                return _enriquecer_estado({"status": "SUCCESS", "result": ar.result})
            elif ar.failed():
                return _enriquecer_estado({"status": "FAILED", "error": str(ar.result)})
        elif ar.state in ("STARTED", "PROCESSING", "RETRY"):
            return _enriquecer_estado({"status": ar.state, "progress": ar.info.get("progress", 0)})
        else:
            return _enriquecer_estado({"status": "PENDING"})
    except Exception as e:
        redis_error = str(e)
        logger.debug(f"AsyncResult error: {e}")

    # Búsqueda en disco (worker local pudo haber escrito aquí)
    disk_path = RESULTS_DIR / f"{task_id}.json"
    if disk_path.exists():
        return _enriquecer_estado(json.load(open(disk_path)))

    # ── FALLBACK CRÍTICO ──
    # Si Redis falló y no hay JSON en disco, devolvemos PENDING (202)
    # en lugar de None (404). El frontend continuará el polling.
    # El task_id fue generado por nuestra API → la tarea EXISTE.
    logger.debug(f"Task {task_id[:8]} no encontrada aún — devolviendo PENDING (redis_err={redis_error})")
    return _enriquecer_estado({"status": "PENDING", "task_id": task_id})
```

**Solución 2 — Timeout corregido para TLS remoto:**

```python
# DESPUÉS — timeout compatible con handshake TLS de Aiven
_r = redis.from_url(url, socket_connect_timeout=8, socket_timeout=8)
```

**Solución 3 — Dispatch desacoplado del ping previo:**

```python
# En API_ONLY, Celery siempre intenta el dispatch aunque el ping haya fallado
# (el pool de conexiones de Celery puede tener conexión activa)
if redis_available or _api_only:
    try:
        analyze_image_task.apply_async(
            args=[task_id, str(dest), file.filename],
            kwargs={"file_content_b64": file_content_b64},
            task_id=task_id,
        )
```

---

### ERROR D: FileNotFoundError en el Worker GPU Local

**Contexto de manifestación:** El worker Celery mostraba en consola el error: `FileNotFoundError: Archivo no encontrado: uploads/a1beeb50-4660-442f-aff0-275495df0216.webp`. El análisis nunca se completaba y la tarea alcanzaba el máximo de reintentos (2) antes de marcarse como fallida.

#### Causa Raíz Técnica

La arquitectura híbrida crea una **disjunción de sistemas de archivos**: el servidor de Render y el worker GPU local son máquinas físicas completamente distintas que no comparten ningún volumen de almacenamiento.

```
Render (nube, San Francisco)          PC Local (Santiago, Chile)
├── /opt/render/project/uploads/      ├── C:\...\backend\uploads\
│   └── a1beeb50...webp               │   └── (vacío)
│                                     │
│   Celery.apply_async(               │   def analyze_image_task(file_path):
│     file_path="uploads/a1beeb50..." │     path = Path(file_path)
│   )            ─────────────────────►    if not path.exists():
│                                     │       raise FileNotFoundError  ← AQUÍ
```

El flujo original asumía que API y worker compartían el mismo sistema de archivos, válido para despliegues monolíticos pero incorrecto para arquitecturas distribuidas.

#### Solución Aplicada

La solución implementada serializa el contenido del archivo como **Base64** dentro del payload del mensaje Celery. Esto transforma el archivo binario en una cadena de texto ASCII transportable por Redis, eliminando la dependencia de un sistema de archivos compartido.

**En `v1/routes.py` (API Gateway — Render):**

```python
# El archivo se recibe como bytes en la petición HTTP multipart
content = await file.read()

# Codificación Base64: bytes → string ASCII (incremento de tamaño ~33%)
import base64
file_content_b64 = base64.b64encode(content).decode("ascii")

# El string Base64 viaja dentro del mensaje Celery (campo kwargs)
analyze_image_task.apply_async(
    args=[task_id, str(dest), file.filename],
    kwargs={"file_content_b64": file_content_b64},
    task_id=task_id,
)
```

**En `analysis_tasks.py` (Worker GPU — PC local):**

```python
def analyze_image_task(
    self, task_id: str, file_path: str, filename: str,
    *, include_heatmap: bool = True,
    file_content_b64: str = "",   # ← Nuevo parámetro
) -> dict:

    path = Path(file_path)

    # Si recibimos el archivo en Base64, lo reconstruimos en disco local
    if file_content_b64:
        import base64
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(base64.b64decode(file_content_b64))
        logger.info(f"Archivo reconstruido: {len(file_content_b64)//1024} KB → {path.name}")

    # A partir de aquí el archivo existe en disco local → análisis normal
    if not path.exists():
        raise FileNotFoundError(f"Archivo no encontrado: {file_path}")
```

**Consideración de escalabilidad:** El tamaño máximo de mensaje en Aiven Valkey (configuración free tier) es de 512 MB. Con overhead de codificación Base64 (~33%), el límite efectivo para archivos es de ~384 MB, compatible con imágenes (< 20 MB típicamente) y videos de duración corta.

---

### ERROR E: Out of Memory (OOM) en Render — 512 MB RAM

**Contexto de manifestación:** Los despliegues en Render fallaban durante el proceso de arranque (`startup`) con el error: `Killed` (señal SIGKILL del sistema operativo), seguido por el reinicio automático del contenedor en un bucle indefinido. Los logs de Render mostraban consumos de RAM superiores a 512 MB.

#### Causa Raíz Técnica

El plan gratuito de Render asigna **512 MB de RAM** por servicio. La versión inicial del `main.py` ejecutaba la carga de modelos de IA durante el arranque del servidor (`lifespan`):

```python
# main.py ORIGINAL — Carga modelos en startup
@asynccontextmanager
async def lifespan(app: FastAPI):
    import torch                          # PyTorch: ~500 MB RAM base
    from app.models.deepfake_detector import DeepfakeDetector
    detector = DeepfakeDetector.get_instance()
    detector.load()                       # 5 modelos: ~6.8 GB VRAM
    FaceDetector.get_instance().load()    # MTCNN: ~200 MB RAM
    yield
```

La secuencia de consumo de memoria durante el startup superaba los 512 MB antes de que el servidor pudiera siquiera responder peticiones HTTP, activando el OOM Killer del sistema operativo.

Adicionalmente, `requirements.txt` incluía PyTorch (`torch>=2.x`) que pesa **~2.5 GB** descargado e instalado. El tiempo de build en Render excedía los límites de su plan gratuito.

#### Solución Aplicada

La solución implementa el principio de **Carga Condicional por Entorno** (*Environment-Aware Lazy Loading*), controlado por la variable de entorno `API_ONLY`:

**`config.py` — Variable de control:**

```python
class Settings(BaseSettings):
    # Render → API_ONLY=true (sin GPU, sin PyTorch)
    # PC local → API_ONLY=false (con GPU y modelos)
    API_ONLY: bool = False
```

**`main.py` — Lifespan condicional:**

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.API_ONLY:
        # Modo cloud: arranque en < 3 segundos, RAM < 80 MB
        logger.info("Modo API-only: modelos omitidos (workers GPU remotos)")
    else:
        # Modo local: carga normal de modelos
        import torch
        from app.models.deepfake_detector import DeepfakeDetector
        DeepfakeDetector.get_instance().load()
    yield
```

**`requirements-api.txt` — Dependencias sin GPU (~180 MB instalado vs ~2.5 GB con torch):**

```txt
fastapi==0.104.1
uvicorn[standard]==0.24.0
celery[redis]>=5.3.0
redis>=5.0.0
pydantic>=2.7.0
loguru>=0.7.2
# SIN: torch, transformers, bitsandbytes, accelerate, timm, opencv
```

**`Dockerfile` — Imagen slim para Render:**

```dockerfile
FROM python:3.13-slim          # Base: 125 MB (vs pytorch/pytorch:2.1.2-cuda: 8+ GB)
ENV API_ONLY=true              # Garantiza modo sin GPU en el contenedor
COPY requirements-api.txt .
RUN pip install --no-cache-dir -r requirements-api.txt
```

**Resultado medido post-optimización:**

| Métrica | Antes | Después |
|---------|-------|---------|
| RAM en startup | > 512 MB (OOM) | < 80 MB |
| Tiempo de build | > 20 min (timeout) | ~3 min |
| Tiempo de arranque | N/A (crash) | < 10 s |
| Imagen Docker | ~9 GB | ~185 MB |

---

<a name="capítulo-3"></a>
## CAPÍTULO 3: FLUJO OPERATIVO SECTORIZADO Y CADENA DE CUSTODIA

### 3.1 Diagrama del Viaje de un Archivo

```
FASE 0 — CLIENTE (Navegador del usuario)
────────────────────────────────────────
  Usuario selecciona archivo (ej. imagen.webp)
       │
       ├── Validación local: tipo MIME, tamaño (< 500 MB)
       ├── Generación de Object URL para preview inmediato
       └── Codificación multipart/form-data para transmisión HTTP
       │
       ▼ POST https://deepguard-ai-api.onrender.com/api/v1/analyze

FASE 1 — API GATEWAY (Render, RAM < 80 MB)
─────────────────────────────────────────────
  FastAPI recibe el archivo como bytes en memoria
       │
       ├── Validación 1: nombre de archivo requerido
       ├── Validación 2: tipo MIME real (python-magic, no solo extensión)
       ├── Validación 3: tamaño vs MAX_FILE_SIZE_MB
       ├── Generación de task_id = uuid.uuid4()
       ├── Guardado temporal: uploads/{task_id}.ext (disco efímero de Render)
       ├── Codificación: file_content_b64 = base64.b64encode(content)
       └── Respuesta inmediata: HTTP 202 Accepted + { task_id, poll_url }
       │
       │  apply_async(args=[task_id, path, filename],
       │              kwargs={"file_content_b64": "...base64..."})
       ▼

FASE 2 — MESSAGE BROKER (Aiven Valkey, TLS 1.3)
─────────────────────────────────────────────────
  Mensaje Celery serializado (JSON) encriptado TLS
       │
       ├── Broker: valkey-3b64dccd...aivencloud.com:13419
       ├── Cola destino: "images" (routing key: image.analyze)
       ├── Persistencia: AOF (Append-Only File) — no se pierde si reinicia
       └── TTL resultado: 86400 segundos (24 horas)
       │
       ▼  Task received por worker local

FASE 3 — HEAVY WORKER GPU (PC Local, RTX 4070 SUPER)
──────────────────────────────────────────────────────
  [00%] Celery recibe tarea → init

  [05%] RECONSTRUCCIÓN DEL ARCHIVO
       └── base64.b64decode(file_content_b64) → archivo.write_bytes()
       └── El archivo existe ahora en uploads/ local

  [10%] HUELLA SHA-256 (Cadena de Custodia)
       └── hashlib.sha256(archivo_bytes).hexdigest()
       └── Fija la identidad criptográfica del archivo original

  [15%] METADATOS FORENSES (EXIF/XMP/IPTC)
       └── Extracción con piexif + xml.etree
       └── Detección de firmas: Midjourney, DALL-E, SDXL, FLUX, Firefly...
       └── Análisis de inconsistencias: software, GPS, timestamps

  [25%] DETECCIÓN OOD (Out-of-Distribution)
       └── 5 señales: edge_density, extreme_pixels, uniform_regions,
           palette_compact, text_regularity
       └── Umbral OOD = 0.43 → penalización adaptativa

  [45%] ENSEMBLE 5 MODELOS (GPU — CUDA)
       ├── Detección de rostro MTCNN → crop facial si existe
       ├── Inferencia paralela: ViT + SDXL + CLIP + AiArt + SigLIP
       ├── Pesos adaptativos según presencia/ausencia de rostro
       └── Correcciones forenses: OOD Bypass + Compression Veto

  [65%] META-ENSEMBLE XGBoost + T-SCALING
       └── Features: [sdxl, aiart, clip, sdxl×aiart, mean, std]
       └── Calibración: probability_calibrated = sigmoid(logit/T), T=0.581

  [80%] ANÁLISIS SEMÁNTICO LLaVA-1.5-7b (GPU — 4-bit NF4)
       ├── Prompt forense en español: anatomía, física, artefactos, texto
       ├── Output JSON: { risk_score: 0-100, semantic_observations: "..." }
       └── Fusión semántica: 70% ensemble + 30% LLaVA (con rostro)

  [90%] SELLO HMAC-SHA256 v2 (Cadena de Custodia)
       ├── canonical = "DG-CUSTODY-v2:{task_id}:{sha256}:{score}:{ts}:sem={llava}"
       ├── custody_token = hmac.new(SIGNING_KEY, canonical, sha256).hexdigest()
       └── Vinculación criptográfica: archivo original ↔ resultado forense

  [100%] PERSISTENCIA
       └── Resultado JSON → RESULTS_DIR/{task_id}.json (disco local)
       └── Resultado → Aiven Redis backend (clave: celery-task-meta-{task_id})
       │
       ▼  result almacenado en Aiven

FASE 4 — POLLING DEL FRONTEND (Navegador)
──────────────────────────────────────────
  Frontend hace GET /api/v1/tasks/{task_id} cada 1500ms
       │
       ├── Render consulta: AsyncResult(task_id, app=celery_app) → Aiven
       ├── Estado PENDING  → HTTP 202 → frontend sigue en "Calculando..."
       ├── Estado PROCESSING {progress: 0.65} → barra avanza al 65%
       └── Estado SUCCESS  → HTTP 200 → resultado completo JSON
       │
       ▼  Frontend recibe JSON de análisis

FASE 5 — PRESENTACIÓN (Navegador)
────────────────────────────────────
  ResultCard renderiza:
       ├── Gauge segmentado SVG (48 segmentos, sin glow/shadows)
       ├── Score final con nivel de evidencia
       ├── Barras por modelo (5 modelos + LLaVA)
       ├── Análisis semántico LLaVA (observaciones forenses)
       ├── Tab Metadatos: EXIF/XMP con firmas de generadores IA
       └── Tab Ensemble: tabla Score/Peso/Contribución + sello HMAC
```

---

### 3.2 Cadena de Custodia Criptográfica

El sello de cadena de custodia garantiza la **inmutabilidad forense** del resultado: cualquier alteración posterior del score, timestamp o archivo original invalida el token.

```python
# Versión 2 — incluye score semántico de LLaVA
seal_version  = "DG-CUSTODY-v2"
sem_score_val = int(semantic_score) if semantic_score is not None else -1

canonical = (
    f"{seal_version}:{task_id}:{file_sha256}:"
    f"{final_score:.8f}:{timestamp_unix:.3f}:sem={sem_score_val}"
)

custody_token = hmac.new(
    SIGNING_KEY,          # Variable de entorno — no está en el código
    canonical.encode("utf-8"),
    hashlib.sha256,
).hexdigest()             # 64 caracteres hexadecimales
```

**Verificación independiente:** Cualquier auditor con acceso a `SIGNING_KEY` puede recomputar el HMAC y compararlo contra `custody_token` sin necesidad del sistema DeepGuard AI.

---

<a name="capítulo-4"></a>
## CAPÍTULO 4: TOPOLOGÍA DEL REPOSITORIO PURGADO v6.0

### 4.1 Árbol de Directorios Post-Refactorización

```
PROYECTO TITULO FINAL/
│
├── 📄 .gitignore                    # Excluye: venv/, .env, models/, uploads/,
│                                    #          reports/, .next/, out/, __pycache__/
├── 📄 ESTRUCTURA_PROYECTO.md        # Árbol visual del proyecto para la comisión
├── 📄 INFORME_TECNICO_DEEPGUARD_AI.md  # Este documento
├── 📄 start-backend.bat             # Arranque rápido FastAPI local
├── 📄 start-frontend.bat            # Arranque rápido Next.js local
├── 📄 START CELERY WORKER.bat       # Arranque del worker GPU con verificación Redis
│
├── 📁 frontend/                     # Capa de Presentación (Next.js 14)
│   ├── 📁 src/
│   │   ├── 📁 app/
│   │   │   ├── layout.tsx           # Root layout con CSS variables forenses
│   │   │   ├── page.tsx             # Página única (SPA)
│   │   │   └── globals.css          # Paleta forense: #080C15 base, semáforo riesgo
│   │   ├── 📁 components/
│   │   │   ├── Navbar.tsx           # Badge EN LÍNEA con health check real (no-cors)
│   │   │   ├── UploadZone.tsx       # Drag-and-drop + preview + polling
│   │   │   ├── AnalysisProgress.tsx # Simulador de terminal forense (8 etapas)
│   │   │   ├── ResultCard.tsx       # Gauge SVG segmentado + desglose de modelos
│   │   │   ├── ForensicPanel.tsx    # Tabla ensemble + certificado custodia
│   │   │   ├── MetadataPanel.tsx    # Panel EXIF/XMP/IPTC
│   │   │   ├── OsintPanel.tsx       # Links búsqueda inversa
│   │   │   └── HistorySection.tsx   # Historial localStorage (últimos 50)
│   │   ├── 📁 lib/
│   │   │   └── api.ts               # Cliente Axios con normalización de estados Celery
│   │   └── 📁 types/
│   │       └── index.ts             # AnalysisResult, SemanticAnalysis, CustodySeal...
│   ├── 📁 public/
│   │   └── _redirects               # /* /index.html 200 (SPA fallback Netlify)
│   ├── next.config.js               # output:'export', trailingSlash:true
│   ├── netlify.toml                 # publish='out', NEXT_PUBLIC_API_URL embebida
│   ├── tailwind.config.ts           # Paleta risk-critical/high/medium/low/minimal
│   ├── .env.local                   # URL local (no en Git)
│   ├── .env.production              # URL Render (embebida en build)
│   ├── .env.production.example      # Template documentado para Netlify
│   └── Dockerfile                   # nginx sirviendo /out (alternativa a Netlify)
│
├── 📁 backend/                      # Capa de Orquestación + Worker GPU (Python 3.13)
│   ├── 📁 app/
│   │   ├── main.py                  # FastAPI entry point, lifespan condicional
│   │   ├── config.py                # Settings Pydantic: API_ONLY, REDIS_URL, CORS
│   │   ├── celery_app.py            # Broker Aiven, 3 colas, serialización JSON
│   │   ├── 📁 api/
│   │   │   ├── schemas.py           # Pydantic: AnalysisResult, SemanticAnalysis...
│   │   │   ├── routes.py            # Legacy /api/* (modo local/desarrollo)
│   │   │   └── 📁 v1/
│   │   │       └── routes.py        # /api/v1/* (producción cloud)
│   │   │                            # Incluye: _get_task_result con fallback PENDING
│   │   │                            #          health con import torch condicional
│   │   │                            #          dispatch con base64 payload
│   │   ├── 📁 models/
│   │   │   ├── deepfake_detector.py # Singleton 5 modelos, Grad-CAM, predict_batch
│   │   │   ├── face_detector.py     # MTCNN singleton
│   │   │   ├── meta_ensemble.py     # XGBoost + Temperature Scaling T=0.581
│   │   │   └── ood_detector.py      # 5 señales heurísticas + hard rule
│   │   ├── 📁 services/
│   │   │   ├── analysis_service.py         # Orquestador async (modo local completo)
│   │   │   ├── image_service.py            # Pipeline: OOD→ensemble→correcciones→Grad-CAM
│   │   │   ├── video_service.py            # Frame-by-frame + análisis temporal
│   │   │   ├── video_temporal_service.py   # ViT embeddings + Farneback
│   │   │   ├── semantic_inspection_service.py  # LLaVA singleton + apply_semantic_fusion
│   │   │   ├── forensic_metadata_service.py    # EXIF/XMP + firmas IA
│   │   │   ├── custody_service.py              # SHA-256 + HMAC-SHA256 v2
│   │   │   ├── metadata_service.py             # Metadatos EXIF básicos
│   │   │   └── osint_service.py                # Hash perceptual + links
│   │   ├── 📁 tasks/
│   │   │   └── analysis_tasks.py    # Celery tasks con base64 payload y retry logic
│   │   └── 📁 utils/
│   │       ├── helpers.py           # Evidence levels, forensic explanation en español
│   │       ├── file_validator.py    # MIME real, size, empty check
│   │       └── forensic_corrections.py  # OOD Bypass + Compression Veto
│   ├── 📁 uploads/                  # Archivos temporales (vacío en Git)
│   ├── requirements.txt             # Deps completas GPU (worker local)
│   ├── requirements-api.txt         # Deps sin GPU: FastAPI+Celery+Redis únicamente
│   ├── Dockerfile                   # python:3.13-slim, API_ONLY=true, < 185 MB
│   ├── .env                         # Secretos locales (NO en Git)
│   ├── .env.production.example      # Template Render
│   └── .env.worker.example          # Template worker GPU local
│
├── 📁 reports/                      # Reportes de análisis (vacío en Git)
│   ├── 📁 tasks/                    # JSON resultados por task_id (auto-generado)
│   └── 📁 custody/                  # Sellos HMAC (read-only, chmod 444)
│
└── 📁 models/                       # Pesos de modelos (excluido de Git — varios GB)
    # Se descargan automáticamente desde HuggingFace Hub en el primer arranque
```

### 4.2 Separación de Dependencias por Entorno

```
requirements.txt (worker GPU local — ~8 GB instalado)
├── torch + torchvision + torchaudio  (CUDA 12.4)
├── transformers >= 4.40.0
├── bitsandbytes >= 0.43.0           (cuantización 4-bit NF4)
├── accelerate >= 0.29.0             (device_map="auto")
├── timm >= 0.9.12
├── facenet-pytorch >= 2.5.3         (MTCNN)
├── opencv-python-headless
├── grad-cam >= 1.4.8
└── [+ dependencias web comunes]

requirements-api.txt (Render cloud — ~180 MB instalado)
├── fastapi + uvicorn                (solo routing HTTP)
├── celery[redis] + redis            (dispatch de tareas)
├── pydantic + pydantic-settings     (validación)
└── loguru + slowapi + psutil        (logging y rate limiting)
```

---

<a name="métricas"></a>
## MÉTRICAS DE RENDIMIENTO Y VALIDACIÓN

### Rendimiento del Sistema en Producción

| Etapa | Tiempo (imagen típica 2MB) | Hardware |
|-------|---------------------------|---------|
| Upload HTTP + base64 encoding | ~0.3s | Red internet |
| Dispatch Celery (Aiven TLS) | ~0.1s | Red internet |
| SHA-256 + EXIF/XMP | ~0.05s | CPU worker local |
| OOD Detection | ~0.1s | CPU worker local |
| Ensemble 5 modelos (GPU) | ~1.2s | RTX 4070 SUPER |
| XGBoost Meta-Ensemble | ~0.01s | CPU worker local |
| LLaVA Semántico (GPU 4-bit) | ~2.8s | RTX 4070 SUPER |
| HMAC-SHA256 Custodia | ~0.001s | CPU worker local |
| **TOTAL pipeline** | **~4.5s** | GPU local |

### Validación del Modelo sobre Golden Set

| Métrica | Valor | Significado |
|---------|-------|-------------|
| F1-Score | **94.7%** | Balance precision-recall sobre 512 imágenes |
| ECE | **0.084** | Error de calibración de probabilidades |
| FPR @ 50% umbral | **10%** | Tasa de falsos positivos |
| Temperatura T | **0.581** | Parámetro de calibración post-entrenamiento |
| VRAM total | **6.8 GB / 12.9 GB** | 5 modelos + LLaVA 4-bit en RTX 4070 SUPER |

### Cobertura de Tipos de Manipulación Detectados

| Categoría | Modelos responsables | Tasa detección |
|-----------|---------------------|---------------|
| Face-swap deepfake | ViT (A) + CLIP (C) | ~96% |
| Face-reenactment | ViT (A) + SigLIP (E) | ~91% |
| Imágenes SDXL/Stable Diffusion | SDXL Detector (B) | ~94% |
| Arte IA (Midjourney, Firefly) | AI Art (D) + CLIP (C) | ~89% |
| Fotos reales comprimidas (FP) | Compression Veto + LLaVA | FPR reducido 68% → 10% |
| Afiches híbridos IA (FN) | OOD Bypass + LLaVA | Detección restaurada |

---

<a name="conclusiones"></a>
## CONCLUSIONES DE INGENIERÍA

### Logros Técnicos Principales

El desarrollo de **DeepGuard AI v6.0** demuestra que es factible construir un sistema de detección de deepfakes de grado profesional con **costo operativo nulo en infraestructura**, resolviendo el problema de acceso a cómputo GPU mediante una arquitectura híbrida desacoplada que separa la capa de presentación y orquestación (cloud gratuito) de la capa de inferencia (hardware propio).

Los cinco errores críticos documentados en el Capítulo 2 representan los desafíos inherentes a cualquier sistema distribuido multi-cloud con workers locales heterogéneos. Su resolución requirió comprensión profunda de:

- **Compilación de frameworks frontend** (Next.js output modes, CDN hosting constraints)
- **Seguridad web** (CORS, preflight requests, opaque responses con `no-cors`)
- **Sistemas de colas distribuidas** (Celery state machine, Redis backend TTL)
- **Serialización de datos binarios** (Base64 encoding en payloads JSON de Celery)
- **Optimización de contenedores** (conditional imports, slim base images)

### Principios de Ingeniería Aplicados

| Principio | Aplicación en DeepGuard AI |
|-----------|---------------------------|
| **Separation of Concerns** | 4 capas independientes (presentación, orquestación, transporte, cómputo) |
| **Defense in Depth** | SHA-256 + HMAC + CORS + Rate Limiting + MIME validation |
| **Fail Safe Defaults** | Fallback PENDING en polling → frontend no aborta |
| **Single Responsibility** | API solo valida y despacha; Worker solo infiere |
| **Environment Parity** | `.env.production.example` y `.env.worker.example` documentados |
| **Immutable Infrastructure** | Docker imagen reproducible; `.gitignore` estricto |

### Líneas de Trabajo Futuro

1. **Certificado TLS de Aiven en Celery:** Reemplazar `ssl_cert_reqs=CERT_NONE` por el certificado CA descargado de Aiven, eliminando el warning de seguridad de Celery
2. **Object Storage para archivos grandes:** Implementar S3/R2 como almacenamiento compartido para videos > 50 MB, reemplazando la serialización Base64 que multiplica el tamaño por 1.33
3. **Fine-tuning del meta-ensemble:** Expandir el golden set de validación a 2048+ imágenes con datos de manipulaciones de 2025-2026 (FLUX.1, Ideogram v3)
4. **Autoscaling del worker:** Implementar múltiples workers Celery para análisis paralelo, con soporte de prioridad de cola por tipo de archivo

---

*Documento generado el 31 de mayo de 2026 · DeepGuard AI v6.0.0*
*Carrera: Ingeniería en Informática · INACAP · Proyecto de Título*
