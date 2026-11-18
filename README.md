# DeepScan — Verificación de imágenes y video

Detecta si una imagen o un video fue generado o manipulado por inteligencia
artificial, e informa **la fuerza de la evidencia** —no un «real» o «falso»—
junto con lo que la sostiene y un informe sellado que no puede alterarse
después.

**En vivo:** <https://gaboto1.github.io/DeepGuard-AI/>

Proyecto de título. Todas las cifras de este documento están medidas y
declaran de dónde salen; el registro completo está en
[`reports/MEJORA_ENSEMBLE_v4.md`](reports/MEJORA_ENSEMBLE_v4.md).

---

## Qué hace

| | |
|---|---|
| **Análisis** | Seis detectores especializados, un meta-ensemble que aprende a combinarlos (tres cabezales LightGBM: fotografía, obra gráfica y rostro) y una lectura semántica de la escena con LLaVA-1.5-7B |
| **Resultado** | Cinco bandas de evidencia (muy baja, baja, inconclusa, moderada, fuerte), desglose por detector, mapa de atención y metadatos forenses |
| **Cadena de custodia** | Cada informe se firma con HMAC-SHA256 sobre la huella SHA-256 del archivo, el score y la marca de tiempo |
| **Planes** | Gratuito (5 análisis al día, sin registro), Profesional y Pericial; cobro en modo demostración. Ver [`reports/MODELO_DE_NEGOCIO.md`](reports/MODELO_DE_NEGOCIO.md) |

## Cifras medidas

| | valor | procedencia |
|---|---|---|
| Falsas alarmas sobre fotografía auténtica | **0,9 %** | fuera de muestra: 1.000 fotos de LFW e ImageNet |
| Imágenes de IA señaladas | **84,9 %** | fuera de muestra: FLUX y DALL·E 3, generadores nunca vistos |
| AUC | **0,995** | fuera de muestra |
| Deepfake facial señalado | **95,0 %** | dentro de muestra (FaceForensics++) |
| Tiempo por imagen | **~32 s** de mediana | GPU dedicada; ~5 s el ensemble y el resto el análisis semántico |

**Límites conocidos.** Sobre fotografía moderna de alta resolución «en la
calle» (Reddit) las falsas alarmas suben al 14 %. El cabezal facial está
entrenado con intercambio de rostro y no reconoce rostros enteramente
sintéticos. Es un análisis probabilístico: orienta una verificación, no
reemplaza un peritaje.

## Arquitectura

```
GitHub Pages (Next.js estático)
        │  HTTPS
        ▼
API FastAPI en Render (API_ONLY: no carga modelos)
        │  cola de tareas
        ▼
Redis en Upstash (broker y resultados)
        │
        ▼
Worker Celery con GPU local (RTX 4070 SUPER): seis detectores + meta-ensemble + LLaVA
```

La página funciona solo mientras el worker está encendido: es el componente de
cómputo del despliegue, no un entorno de pruebas.

---

## Compuerta de tipo de contenido (v3)

El detector de arte IA (modelo D) responde a la pregunta *"¿generó una IA esta
obra?"*, que no es la pregunta forense *"¿fue manipulada esta fotografía?"*.
Como además concentraba el 91% de la importancia del meta-modelo, el porcentaje
final era en la práctica su sola opinión.

Antes de combinar los detectores, una compuerta CLIP zero-shot clasifica la
imagen como **fotografía** u **obra gráfica** (ilustración, pintura, render):

| Tipo de contenido | Cabezal del meta-ensemble | Detector de arte IA |
|---|---|---|
| Fotografía | `meta_classifier.joblib` | participa en el score |
| Obra gráfica | `meta_classifier_noart.joblib` | **excluido**, se reporta aparte |

La exclusión es completa: también se aplica a las reglas de corrección forense,
para que el score de arte IA no reentre por esa vía. La API devuelve
`content_type` y `ai_art_indicator`, y la UI muestra ese indicador en un panel
propio marcado como *fuera del cálculo*.

La compuerta reutiliza el CLIP ViT-L/14 que ya carga el modelo C: 0 VRAM extra.
Es complementaria al detector OOD, que es heurístico y busca afiches y texto
denso, no tipo de contenido.

Validación (150 img/grupo, AUC foto-vs-arte = 0.973):

| Conjunto | `artwork_probability` |
|---|---|
| COCO (foto natural) | 0.097 |
| FF++ real (rostro en video) | 0.028 |
| FF++ fake (deepfake) | 0.046 |
| sdturbo_sports (IA fotorrealista) | 0.103 |
| DiffusionDB (arte IA) | 0.881 |

El deepfake facial y la imagen IA fotorrealista quedan del lado *fotografía*:
la compuerta separa por tipo de contenido, no por autoría.

---

## Modos de operación (Producción vs Local)

El backend opera en dos modos controlados por la variable `API_ONLY` (`backend/.env`):

| | `API_ONLY=true` (Producción — Render) | `API_ONLY=false` (Local — desarrollo) |
|---|---|---|
| Modelos GPU | No se cargan (cero imports de PyTorch) | Se cargan en el lifespan de FastAPI |
| Procesamiento | Despacha a Celery → workers GPU vía Redis (Upstash) | Intenta Celery si hay Redis disponible; si no, ejecuta el análisis en el mismo proceso (`sync_fallback`) |
| Resultados/historial | Reports JSON en `reports/tasks/` + custodia en `reports/custody/` | Igual — mismos directorios locales, sin tocar datos de producción |
| Frontend | `NEXT_PUBLIC_API_URL` apunta a la API de Render (`frontend/.env.production`) | `NEXT_PUBLIC_API_URL=http://localhost:8000` (`frontend/.env.local`) |

Esto permite levantar el stack completo en `localhost` (`INICIAR LOCAL.bat` o `uvicorn` + `npm run dev`) sin depender de Redis/Celery en la nube ni afectar las colas o el historial de producción — el endpoint `/` y `/api/v1/health` exponen el campo `mode` para verificar en qué modo está corriendo la instancia.

El worker GPU local (`INICIAR PAGINA WEB.bat`) siempre usa `API_ONLY=false` y se conecta al Redis de producción (Upstash) para consumir tareas reales — es el componente de cómputo del despliegue en producción, no un modo de prueba.

Si el worker o la API reportan que Redis no responde, ver `docs/RUNBOOK_REDIS_DOWN.md` para el procedimiento de recuperación.

---

## Puesta en marcha

**Worker GPU (lo que hace funcionar la página):** doble clic en
`INICIAR PAGINA WEB.bat`. Comprueba el entorno, que no haya otro worker y la
VRAM libre antes de arrancar, y guarda la salida en `reports/worker.log`.
Tarda 2–4 minutos en cargar los modelos.

> Cierra navegadores y juegos que usen la GPU antes de arrancarlo. Con la VRAM
> ocupada, LLaVA se ejecuta en CPU y cada análisis pasa de ~30 segundos a
> decenas de minutos; el worker lo avisa con `VRAM INSUFICIENTE` en el log.

**Todo en local:** `INICIAR LOCAL.bat` levanta la API y el frontend en
`http://localhost:3000`.

**Variables de entorno:** ver `backend/.env.example`. Las claves
(`DEEPGUARD_SIGNING_KEY`, `DEEPGUARD_BILLING_KEY`) nunca van al repositorio.

**Tras cambiar el backend:** la API de Render no se redespliega sola; hay que
hacer *Manual Deploy* en su panel.

## Pruebas

```
cd backend
venv\Scripts\python -m pytest -q
```

La batería y las herramientas de medición (`scripts/eval_heldout.py`,
`scripts/medir_latencia.py`, `scripts/prueba_extremo_a_extremo.py`, …) están
descritas en [`docs/ESTRUCTURA_PROYECTO.md`](docs/ESTRUCTURA_PROYECTO.md).

## Licencia y datos

El repositorio **no declara licencia** todavía.

Los cabezales del meta-ensemble se entrenaron, entre otras fuentes, con
**OpenFake (ComplexDataLab), licencia CC BY-NC 4.0, no comercial**. Para un
proyecto de título no es un problema, pero antes de cobrar por el servicio hay
que reentrenar sin esas filas u obtener otra licencia. Los detectores
preentrenados de HuggingFace tienen sus propias licencias, que también deben
revisarse antes de un uso comercial.
